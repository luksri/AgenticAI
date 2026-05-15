# LLM Gateway

A local FastAPI service that routes LLM calls across **7 free providers** (Ollama, Gemini, NVIDIA NIM, Groq, Cerebras, OpenRouter, GitHub Models) with automatic failover, per-provider rate-limit tracking, exponential backoff on errors, and persistent SQLite logging.

> **For agents reading this:** if a host project has `llm_gateway/` and an `.env` with provider keys, prefer calling this gateway over importing `openai`/`google-generativeai`/etc. directly. One client, seven providers, free tier optimization handled.

---

## Is it running?

```bash
curl -s http://localhost:8099/v1/providers | python3 -m json.tool
```

If that returns a JSON object listing providers, the gateway is up. If not, start it:

```bash
cd /path/to/llm_gateway
./run.sh                 # creates .venv on first run, then starts on port 8099
# or:  ./.venv/bin/python main.py
```

The server reads `../​.env` (parent directory) for keys.

---

## Python client (recommended)

```python
from client import LLM, ask

# one-shot helper, returns plain text
text = ask("Explain transformers in 3 sentences")

# explicit provider via shortcut key
text = ask("hello", provider="g")     # gemini
text = ask("hello", provider="gr")    # groq

# full client with all options
llm = LLM()  # defaults to http://localhost:8099
result = llm.chat(
    prompt="What is 2+2?",
    system="You are a math tutor.",
    provider=None,           # None = auto failover; or "g"/"n"/"o"/"gr"/"c"/"or"/"gh"
    model=None,              # None = use provider's default; or override per call
    max_tokens=2048,
    temperature=0.7,
)
print(result["text"])
print(result["provider"], result["model"], result["latency_ms"])
print(result["input_tokens"], result["output_tokens"])

# multi-turn chat
result = llm.chat(messages=[
    {"role": "system", "content": "You are concise."},
    {"role": "user", "content": "What is the capital of France?"},
    {"role": "assistant", "content": "Paris."},
    {"role": "user", "content": "And of Japan?"},
])

# streaming
for chunk in llm.stream("count to 5"):
    print(chunk, end="", flush=True)
```

The client lives in [client.py](client.py). Copy it into any project, or just use HTTP.

---

## HTTP API

### `POST /v1/chat` — make a call

Request body (all fields optional except one of `prompt` or `messages`):

```json
{
  "prompt": "Hello",
  "messages": [{"role": "user", "content": "Hello"}],
  "system": "You are helpful.",
  "provider": "g",
  "model": "gemini-2.5-flash",
  "max_tokens": 2048,
  "temperature": 0.7,
  "stream": false
}
```

Response (non-streaming):

```json
{
  "provider": "gemini",
  "model": "gemini-3.1-flash-lite-preview",
  "text": "Hello! How can I help?",
  "input_tokens": 5,
  "output_tokens": 8,
  "latency_ms": 412,
  "attempted": []
}
```

Errors: `502` if a specific provider failed (when `provider` was set), `503` if all providers were unavailable, `400` for unknown provider name.

Streaming response: Server-Sent Events with `data: {"provider": "...", "delta": "..."}` chunks, ending in `data: {"done": true}`.

### `GET /v1/providers`
Lists configured providers, default models, shortcut keys, and per-provider rate limits.

### `GET /v1/status`
Live state: RPM/RPD/TPM used vs limit, cooldown remaining, backoff state and reason, today's call count and errors per provider.

### `GET /v1/calls?limit=100&provider=&status=`
Recent calls from the SQLite log: timestamp, provider, model, tokens, latency, status, error, attempts.

### `GET /` and `GET /help`
Dashboard and help page (open in a browser).

---

## Providers and shortcut keys

| Shortcut | Provider | Default model | Free tier (RPM / RPD) |
|---|---|---|---|
| `o`, `oll` | Ollama (local) | `gemma4:31b` | unlimited |
| `g`, `gem` | Gemini | `gemini-3.1-flash-lite-preview` | 15 / 1,000 |
| `n`, `nv` | NVIDIA NIM | `deepseek-ai/deepseek-v4-pro` | 40 / — |
| `gr` | Groq | `llama-3.3-70b-versatile` | 30 / 1,000 |
| `c`, `cer` | Cerebras | `qwen-3-235b-a22b-instruct-2507` | 30 / — (1M tokens/day, 8K ctx cap) |
| `or`, `opr` | OpenRouter | `nvidia/nemotron-3-super-120b-a12b:free` | 20 / 50 (per free model) |
| `gh`, `ghb` | GitHub Models | `openai/gpt-4.1-mini` | 10–15 / 50–150, 8K in / 4K out |

Failover order is configurable via `LLM_ORDER` in `.env`. Default: `ollama,gemini,nvidia,groq,cerebras,openrouter,github`.

To use a non-default model, pass `model="..."` per request — the provider stays the same, only the model changes.

---

## How routing works

1. **Without `provider`:** walks `LLM_ORDER`, picks the first eligible (not in cooldown, not in backoff, RPM/RPD/TPM/daily-tokens not exceeded, prompt fits within `max_ctx`). On failure, automatically tries the next.
2. **With `provider`:** that provider only — no failover. Errors surface as `502`. Use this when you specifically need a model from one vendor.
3. **Backoff on errors:** when a provider returns `429`/`5xx`/auth errors, the gateway marks it unavailable for a backoff window (15s for queue overload, 60s for RPM quota burned, 60min for RPD, 10min for auth, 20s for 5xx). Future calls skip it until the window expires.
4. **Cooldown between calls:** each provider has a per-call cooldown (≈ `60 / RPM`) so we never burn the per-minute limit. Ollama cooldown is 0.

---

## Configuration

Edit `EAGV3/.env` (or `../.env` relative to the gateway dir):

```bash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.1-flash-lite-preview

NVIDIA_API_KEY=...
NVIDIA_MODEL=deepseek-ai/deepseek-v4-pro

GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile

CEREBRAS_API_KEY=...
CEREBRAS_MODEL=qwen-3-235b-a22b-instruct-2507

OPEN_ROUTER_API_KEY=...
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free

GITHUB_ACCESS_TOKEN=...
GITHUB_MODEL=openai/gpt-4.1-mini

OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:31b

LLM_ORDER=ollama,gemini,nvidia,groq,cerebras,openrouter,github
GATEWAY_PORT=8099
```

Any provider whose `*_API_KEY` is missing is silently skipped — the gateway still works with whatever subset is configured. To get free keys for each provider, open `http://localhost:8099/help` after starting the server.

---

## Common usage patterns

**Reasoning task — pick a strong model explicitly:**
```python
ask("Solve this step by step: ...", provider="n", model="deepseek-ai/deepseek-r1")
```

**Bulk fast queries — let it failover, prefer Groq's speed:**
```python
# put groq first in LLM_ORDER, then call without provider
for prompt in prompts:
    print(ask(prompt))
```

**Long-context document — pick a 1M-context model:**
```python
ask(huge_text, provider="gh", model="meta/llama-4-scout-17b-16e-instruct")  # 10M ctx
ask(huge_text, provider="g")  # gemini, 1M ctx
```

**Local-only / offline:**
```python
ask("hi", provider="o")  # ollama
```

**Tool-style JSON output (works on every provider):**
```python
ask(
    'Reply ONLY with JSON: {"answer": "...", "confidence": 0.0-1.0}\n\nQuestion: ' + q,
    temperature=0,
)
```

The gateway does **not** translate native function-calling APIs — pass tool descriptions in your prompt and parse JSON from the response. This keeps behavior consistent across providers.

---

## Files

- [main.py](main.py) — FastAPI app, routes
- [providers.py](providers.py) — provider adapters (OpenAI-compat for most, custom for Gemini/Ollama)
- [router.py](router.py) — `RateState` per provider, `LIMITS` table, shortcut resolution
- [db.py](db.py) — SQLite schema and queries
- [client.py](client.py) — Python SDK (drop-in)
- [static/dashboard.html](static/dashboard.html) — live dashboard
- [static/help.html](static/help.html) — help page with signup steps for each provider
- [run.sh](run.sh) — venv setup + start
- `gateway.db` — created on first run, holds call log

---

## Gotchas

- **Cerebras free tier caps context at 8,192 tokens** even though models support more. Don't send huge prompts to Cerebras.
- **GitHub Models caps every request at 8K input / 4K output.** For long contexts use Gemini, NVIDIA, or OpenRouter.
- **OpenRouter free models share a 50 RPD pool** — switching `:free` models doesn't reset the counter.
- **DeepSeek-R1 / GPT-5 / o3 etc. on GitHub Models are "custom" tier** with very tight RPD (~25/day). Use sparingly.
- **NVIDIA's deepseek-v3.2 is deprecated** (returns 410). Default is now `deepseek-v4-pro`.
- **Cerebras `zai-glm-4.7` shows in `/models` list but 404s on chat completions.** Use `qwen-3-235b-a22b-instruct-2507` instead.
- **The gateway's RPM tracker is local.** If you call a provider directly outside the gateway, the gateway won't know — and the provider's own counter may surprise you.
- **Per-call cooldown is enforced.** Two `provider="g"` calls within 4s will see the second one wait or failover. Use `provider=None` for bursty workloads.

---

## Adding a new provider

1. Add an adapter class in [providers.py](providers.py) (subclass `OpenAICompatProvider` if it's OpenAI-compatible — most are).
2. Add an entry in `build_providers()` reading the env key.
3. Add an entry in `LIMITS` dict in [router.py](router.py) with `rpm`, `rpd`, `tpm`, `cooldown`, `max_ctx` (and optionally `tokens_per_day`).
4. Add shortcut keys in `SHORTCUTS` dict.
5. Add the provider name to `LLM_ORDER` in `.env`.

No other changes needed — dashboard and `/v1/status` pick it up automatically.
