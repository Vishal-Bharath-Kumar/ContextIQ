"""Shared LiteLLM-backed local Ollama chain helpers for agent nodes."""

from __future__ import annotations

import os
from typing import Any

import litellm


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


class LiteLLMChain:
    """Minimal async chain wrapper compatible with the node/test call sites.

    Accepts LangChain prompt templates and output parsers but executes the
    underlying completion through LiteLLM against a local Ollama endpoint.
    """

    def __init__(
        self,
        prompt: Any,
        parser: Any,
        *,
        model_id: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
        api_base: str | None = None,
    ) -> None:
        self._prompt = prompt
        self._parser = parser
        self._model_id = model_id
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        self._api_base = api_base or get_ollama_base_url()

    async def ainvoke(self, variables: dict[str, Any], config: dict[str, Any] | None = None) -> Any:
        messages = [
            {
                "role": _message_role(message.type),
                "content": _message_content(message.content),
            }
            for message in self._prompt.format_messages(**variables)
        ]
        callbacks = []
        if config is not None:
            callbacks = list(config.get("callbacks") or [])

        response = await litellm.acompletion(
            model=self._model_id,
            api_base=self._api_base,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout=self._timeout_s,
            callbacks=callbacks,
        )
        content = response.choices[0].message.content or ""
        if self._parser is None:
            return content
        parse = getattr(self._parser, "parse", None)
        if callable(parse):
            return parse(content)
        invoke = getattr(self._parser, "invoke", None)
        if callable(invoke):
            return invoke(content)
        return content


def _message_role(message_type: str) -> str:
    return {
        "human": "user",
        "ai": "assistant",
        "system": "system",
        "tool": "tool",
    }.get(message_type, "user")


def _message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in content)
    return str(content)