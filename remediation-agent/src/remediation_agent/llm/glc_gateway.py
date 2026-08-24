"""A LangChain-compatible chat model backed by session-17's multi-provider
fallback chain, reused by direct import of `glc.providers` (glc_v5) --
`GroqProvider`, `CerebrasProvider`, `OllamaProvider`, etc., every one a thin
`BaseProvider` subclass with a lightweight constructor and an async `chat()`
method. `glc/__init__.py` and `glc/providers.py` import nothing beyond
`httpx` + stdlib at module load, so this is the same "import the
self-contained piece" reuse this project already applies to
`s17code.coding.*` -- not the full glc_v5 HTTP service.

Deliberately NOT reused: `glc_v5`'s own `/v1/chat` FastAPI route
(`glc/routes/chat.py`). That route layers semantic caching, routing policy,
budget admission, OpenTelemetry spans and per-call metering on top of the
same provider classes -- all real, all irrelevant to "ask a model for one
patch," and all of it would mean this project depends on a separately
running, database-backed service for something a single Python import
already does. This project was also explicitly told to ignore cost/budget
concerns; importing the budget-admission route would work against that.

`LLM_ORDER` (and every provider's own `*_API_KEY`/`*_MODEL` variable) is read
directly, unchanged, from the exact env vars session-17's own gateway
uses -- "inherit from session-17" taken literally, not reinvented under a
`REMEDIATION_`-prefixed name. `ollama` -- a fully local, genuinely
open-weight model -- is first in the shipped default order; the rest are
hosted fallbacks, in the same relative order already configured, not
filtered or reordered here.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

DEFAULT_ORDER = ["ollama", "gemini", "nvidia", "groq", "cerebras", "openrouter", "github"]


def _build_providers() -> dict[str, Any]:
    """One instance per provider that has its required env var(s) set.
    Mirrors glc_v5's own `build_providers()` (glc/providers.py), minus the
    `cache_store`/rate-limit-registry coupling that function has -- this
    project never asks for Gemini's explicit prompt caching, so
    `cache_store=None` is never actually dereferenced.
    """
    from glc.providers import (
        CerebrasProvider,
        GeminiProvider,
        GitHubProvider,
        GroqProvider,
        NvidiaProvider,
        OllamaProvider,
        OpenRouterProvider,
    )

    out: dict[str, Any] = {}
    if ollama_model := os.getenv("OLLAMA_MODEL"):
        out["ollama"] = OllamaProvider(ollama_model, os.getenv("OLLAMA_URL", "http://localhost:11434"))
    if key := os.getenv("GEMINI_API_KEY"):
        out["gemini"] = GeminiProvider(key, os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), None)
    if key := os.getenv("NVIDIA_API_KEY"):
        out["nvidia"] = NvidiaProvider(key, os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"))
    if key := os.getenv("GROQ_API_KEY"):
        out["groq"] = GroqProvider(key, os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    if key := os.getenv("CEREBRAS_API_KEY"):
        out["cerebras"] = CerebrasProvider(key, os.getenv("CEREBRAS_MODEL", "qwen-3-235b-a22b-instruct-2507"))
    if key := os.getenv("OPEN_ROUTER_API_KEY"):
        out["openrouter"] = OpenRouterProvider(
            key, os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
        )
    if key := os.getenv("GITHUB_ACCESS_TOKEN"):
        out["github"] = GitHubProvider(key, os.getenv("GITHUB_MODEL", "gpt-4o-mini"))
    return out


def _to_canonical_tool(tool: Any) -> dict[str, Any]:
    """LangChain tool -> glc.providers' canonical shape.

    `glc.providers`' own `_translate_tools` methods (one per provider class)
    all read `name`/`description`/`input_schema` from whatever's passed in
    `tools=...` -- an Anthropic-shaped canonical form each provider then
    translates into its own native tool-calling format. LangChain's
    `convert_to_openai_tool` produces the adjacent OpenAI shape
    (`{"type": "function", "function": {"name", "description",
    "parameters"}}`); remapping `parameters` -> `input_schema` is the entire
    translation needed, since both are just "the JSON schema for the tool's
    arguments" under a different key name.
    """
    openai_tool = convert_to_openai_tool(tool)
    fn = openai_tool["function"]
    return {
        "name": fn["name"],
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
    }


def _lc_message_to_canonical(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": message.content}
    if isinstance(message, ToolMessage):
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if isinstance(message, AIMessage):
        canonical: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            # `arguments` must be the raw dict, NOT a pre-serialized JSON
            # string: glc.providers.OpenAICompatProvider._translate_messages
            # does `json.dumps(tc.get("arguments") or {})` itself when
            # replaying an assistant tool call back into conversation
            # history. Passing an already-stringified value here made that
            # call double-encode it -- a JSON string containing escaped JSON
            # text -- which is exactly what produced the malformed/truncated
            # payloads every provider choked on in a multi-turn tool loop
            # (Ollama: "can't find closing '}'"; Gemini: "expected Struct,
            # got a string"; NVIDIA: a garbled Python-list-repr fragment
            # leaking into a JSON string value). A single-turn call never
            # exercises this path at all, which is why it looked fine in
            # isolation.
            canonical["tool_calls"] = [
                {"id": tc["id"], "name": tc["name"], "arguments": tc["args"]}
                for tc in message.tool_calls
            ]
        return canonical
    raise TypeError(
        f"unsupported message type for the glc gateway: {type(message).__name__} "
        "(SystemMessage is handled separately, not here -- see _agenerate)"
    )


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


class GLCGatewayChatModel(BaseChatModel):
    """Tries each provider in `order` in turn, using the first that's both
    configured (required env var present) and succeeds. A provider-level
    exception (network error, non-2xx response, etc.) falls through to the
    next provider rather than failing the whole call -- the same behavior
    session-17's own `/v1/chat` route describes for `LLM_ORDER` failover.
    """

    order: tuple[str, ...] = tuple(DEFAULT_ORDER)
    max_tokens: int = 1600
    temperature: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "glc-gateway"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        # BaseChatModel requires this to exist, but nothing in this project
        # calls a chat model synchronously -- every caller awaits ainvoke()
        # (see strategies/base.py's docstring: a strategy must never bridge
        # its own async work onto a fresh event loop to fake a sync call,
        # since that blocks the shared loop every other concurrently-running
        # unit and job depends on. Faking a sync path here via asyncio.run()
        # would be exactly that bridge, just moved one layer down.
        raise NotImplementedError(
            "GLCGatewayChatModel is async-only; call ainvoke()/agenerate(), not invoke()/generate()."
        )

    async def _agenerate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        providers = _build_providers()
        order = [name for name in self.order if name in providers] or list(providers)
        if not order:
            raise RuntimeError(
                "no glc provider is configured -- set at least one of OLLAMA_MODEL, "
                "GEMINI_API_KEY, NVIDIA_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY, "
                "OPEN_ROUTER_API_KEY, GITHUB_ACCESS_TOKEN in the environment"
            )

        # System content travels as a separate `system_blocks` argument to
        # provider.chat(), never as a role="system" entry in `messages` --
        # glc.providers' own chat() signature extracts it that way
        # (_flatten_system), so a system message left in `messages` would
        # never reach the model at all.
        system_text = "\n\n".join(
            str(m.content) for m in messages if isinstance(m, SystemMessage)
        ) or None
        canonical_messages = [
            _lc_message_to_canonical(m) for m in messages if not isinstance(m, SystemMessage)
        ]

        tools = kwargs.get("tools")
        canonical_tools = [_to_canonical_tool(t) for t in tools] if tools else None
        # glc.providers.OpenAICompatProvider.chat() only puts `tool_choice`
        # in the request body `if tool_choice is not None` -- omitting it
        # entirely leaves whether to actually use structured tool-calling up
        # to the provider's own default. Observed concretely: NVIDIA's
        # endpoint, given tools with no explicit tool_choice, described a
        # tool call as a JSON blob in plain response text instead of
        # emitting it as a real tool_calls entry -- unparseable by any
        # caller expecting either a tool call or a text answer. Defaulting
        # to "auto" whenever tools are present (and honoring an explicit
        # choice if the caller set one) asks every provider for the same
        # behavior instead of leaving it ambiguous.
        tool_choice = kwargs.get("tool_choice")
        if tool_choice is None and canonical_tools:
            tool_choice = "auto"

        last_error: Exception | None = None
        for name in order:
            provider = providers[name]
            try:
                result = await provider.chat(
                    canonical_messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    tools=canonical_tools,
                    tool_choice=tool_choice,
                    system_blocks=system_text,
                )
            except Exception as exc:  # noqa: BLE001 -- a provider-level failure, try the next
                logger.debug("glc provider %r failed, trying next: %s", name, exc)
                last_error = exc
                continue

            # Provider name + a short content preview only -- never the raw
            # provider object or request/response headers, so this can't
            # repeat the API-key-in-URL leak the httpx INFO logs caused.
            logger.debug(
                "glc provider %r responded: %d tool_calls, content preview=%r",
                name,
                len(result.get("tool_calls") or []),
                (result.get("text") or "")[:200],
            )

            tool_calls = [
                {
                    "name": tc["name"],
                    "args": _safe_json_loads(tc.get("arguments")),
                    "id": tc.get("id") or str(uuid.uuid4()),
                }
                for tc in (result.get("tool_calls") or [])
            ]
            ai_message = AIMessage(content=result.get("text") or "", tool_calls=tool_calls)
            return ChatResult(generations=[ChatGeneration(message=ai_message)])

        raise RuntimeError(f"every configured glc provider failed (tried {order}); last error: {last_error}")

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        # Raw LangChain tool objects are bound as-is; _agenerate converts them
        # to glc.providers' canonical shape per call, not here, since bind()
        # just stores kwargs for the eventual _agenerate call.
        return self.bind(tools=list(tools), **kwargs)
