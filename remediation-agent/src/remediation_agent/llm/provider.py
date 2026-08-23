"""Pluggable chat-model selection, config/env-driven.

Nothing in the default SCA remediation path calls `get_chat_model()` -- the
deterministic version-bump strategy needs no LLM at all. This module only
matters for the SCA-ambiguous fallback (`settings.enable_sca_llm_fallback`)
and the optional adversarial validator (`settings.enable_adversarial_validation`),
both off by default. Provider SDKs are therefore imported lazily, inside the
function, so simply importing this module never hard-fails on a missing
optional dependency.
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from remediation_agent.config import get_settings


def get_chat_model() -> BaseChatModel:
    """Return a chat model selected by `get_settings().llm_provider`/`.llm_model`.

    Raises RuntimeError with a clear message if the configured provider is
    unsupported or its SDK isn't installed.
    """
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError(
                "REMEDIATION_LLM_PROVIDER=anthropic requires the 'langchain-anthropic' "
                "package. Install it (it's listed as a dependency in pyproject.toml) "
                "or switch REMEDIATION_LLM_PROVIDER to a supported provider."
            ) from exc
        return ChatAnthropic(model=settings.llm_model)

    raise RuntimeError(
        f"unsupported REMEDIATION_LLM_PROVIDER={provider!r}. Supported providers: 'anthropic'."
    )
