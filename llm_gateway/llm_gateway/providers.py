import os, json, httpx
from typing import AsyncIterator, Optional


class ProviderError(Exception):
    def __init__(self, msg, status=None, retryable=True):
        super().__init__(msg)
        self.status = status
        self.retryable = retryable


class BaseProvider:
    name: str = ""

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def chat(self, messages, max_tokens=2048, temperature=0.7, model=None) -> dict:
        raise NotImplementedError

    async def stream(self, messages, max_tokens=2048, temperature=0.7, model=None) -> AsyncIterator[str]:
        raise NotImplementedError


class OpenAICompatProvider(BaseProvider):
    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _body(self, messages, max_tokens, temperature, model, stream):
        return {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

    async def chat(self, messages, max_tokens=2048, temperature=0.7, model=None):
        body = self._body(messages, max_tokens, temperature, model, False)
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body)
            if r.status_code != 200:
                raise ProviderError(
                    f"{self.name} HTTP {r.status_code}: {r.text[:300]}",
                    status=r.status_code,
                    retryable=(r.status_code != 400 and r.status_code != 401),
                )
            d = r.json()
            usage = d.get("usage") or {}
            return {
                "text": d["choices"][0]["message"]["content"] or "",
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "model": body["model"],
            }

    async def stream(self, messages, max_tokens=2048, temperature=0.7, model=None):
        body = self._body(messages, max_tokens, temperature, model, True)
        async with httpx.AsyncClient(timeout=180) as c:
            async with c.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(), json=body) as r:
                if r.status_code != 200:
                    text = (await r.aread()).decode("utf-8", "ignore")[:300]
                    raise ProviderError(f"{self.name} HTTP {r.status_code}: {text}", status=r.status_code)
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        return
                    try:
                        d = json.loads(payload)
                        delta = d["choices"][0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue


class GroqProvider(OpenAICompatProvider):
    name = "groq"
    def __init__(self, api_key, model):
        super().__init__(api_key, model, "https://api.groq.com/openai/v1")


class CerebrasProvider(OpenAICompatProvider):
    name = "cerebras"
    def __init__(self, api_key, model):
        super().__init__(api_key, model, "https://api.cerebras.ai/v1")


class NvidiaProvider(OpenAICompatProvider):
    name = "nvidia"
    def __init__(self, api_key, model):
        super().__init__(api_key, model, "https://integrate.api.nvidia.com/v1")


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    def __init__(self, api_key, model):
        super().__init__(api_key, model, "https://openrouter.ai/api/v1")

    def _headers(self):
        h = super()._headers()
        h["HTTP-Referer"] = "http://localhost"
        h["X-Title"] = "LLM Gateway"
        return h


class GitHubProvider(OpenAICompatProvider):
    name = "github"
    def __init__(self, api_key, model):
        super().__init__(api_key, model, "https://models.github.ai/inference")


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key, model):
        super().__init__(api_key, model, "https://generativelanguage.googleapis.com/v1beta")

    def _convert(self, messages):
        contents, system = [], None
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                system = content
            else:
                contents.append({"role": "user" if role == "user" else "model", "parts": [{"text": content}]})
        body = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    async def chat(self, messages, max_tokens=2048, temperature=0.7, model=None):
        m = model or self.model
        body = self._convert(messages)
        body["generationConfig"] = {"maxOutputTokens": max_tokens, "temperature": temperature}
        url = f"{self.base_url}/models/{m}:generateContent?key={self.api_key}"
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(url, json=body)
            if r.status_code != 200:
                raise ProviderError(
                    f"gemini HTTP {r.status_code}: {r.text[:300]}",
                    status=r.status_code,
                    retryable=(r.status_code != 400 and r.status_code != 401),
                )
            d = r.json()
            cands = d.get("candidates") or []
            if not cands:
                raise ProviderError(f"gemini no candidates: {json.dumps(d)[:200]}", status=200, retryable=True)
            parts = cands[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            usage = d.get("usageMetadata") or {}
            return {
                "text": text,
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
                "model": m,
            }

    async def stream(self, messages, max_tokens=2048, temperature=0.7, model=None):
        m = model or self.model
        body = self._convert(messages)
        body["generationConfig"] = {"maxOutputTokens": max_tokens, "temperature": temperature}
        url = f"{self.base_url}/models/{m}:streamGenerateContent?alt=sse&key={self.api_key}"
        async with httpx.AsyncClient(timeout=180) as c:
            async with c.stream("POST", url, json=body) as r:
                if r.status_code != 200:
                    text = (await r.aread()).decode("utf-8", "ignore")[:300]
                    raise ProviderError(f"gemini HTTP {r.status_code}: {text}", status=r.status_code)
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    try:
                        d = json.loads(payload)
                        for cand in d.get("candidates") or []:
                            for p in cand.get("content", {}).get("parts", []):
                                t = p.get("text", "")
                                if t:
                                    yield t
                    except Exception:
                        continue


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, model, base_url="http://localhost:11434"):
        super().__init__("", model, base_url)

    async def chat(self, messages, max_tokens=2048, temperature=0.7, model=None):
        m = model or self.model
        body = {
            "model": m,
            "messages": messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=600) as c:
            r = await c.post(f"{self.base_url}/api/chat", json=body)
            if r.status_code != 200:
                raise ProviderError(f"ollama HTTP {r.status_code}: {r.text[:300]}", status=r.status_code)
            d = r.json()
            return {
                "text": d.get("message", {}).get("content", ""),
                "input_tokens": d.get("prompt_eval_count", 0),
                "output_tokens": d.get("eval_count", 0),
                "model": m,
            }

    async def stream(self, messages, max_tokens=2048, temperature=0.7, model=None):
        m = model or self.model
        body = {
            "model": m,
            "messages": messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=600) as c:
            async with c.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                if r.status_code != 200:
                    text = (await r.aread()).decode("utf-8", "ignore")[:300]
                    raise ProviderError(f"ollama HTTP {r.status_code}: {text}", status=r.status_code)
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        t = d.get("message", {}).get("content", "")
                        if t:
                            yield t
                        if d.get("done"):
                            return
                    except Exception:
                        continue


def build_providers():
    out = {}
    if k := os.getenv("GEMINI_API_KEY"):
        out["gemini"] = GeminiProvider(k, os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"))
    if k := os.getenv("NVIDIA_API_KEY"):
        out["nvidia"] = NvidiaProvider(k, os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v3.2"))
    if k := os.getenv("GROQ_API_KEY"):
        out["groq"] = GroqProvider(k, os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    if k := os.getenv("CEREBRAS_API_KEY"):
        out["cerebras"] = CerebrasProvider(k, os.getenv("CEREBRAS_MODEL", "zai-glm-4.7"))
    if k := os.getenv("OPEN_ROUTER_API_KEY"):
        out["openrouter"] = OpenRouterProvider(k, os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"))
    if k := os.getenv("GITHUB_ACCESS_TOKEN"):
        out["github"] = GitHubProvider(k, os.getenv("GITHUB_MODEL", "openai/gpt-4.1-mini"))
    if om := os.getenv("OLLAMA_MODEL"):
        out["ollama"] = OllamaProvider(om, os.getenv("OLLAMA_URL", "http://localhost:11434"))
    return out
