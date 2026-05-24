from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import AsyncOpenAI


CODE_BLOCK_PATTERN = re.compile(
    r"```[ \t]*(?P<language>[A-Za-z0-9_+-]*)?[^\S\r\n]*(?:\r?\n)?(?P<code>.*?)```",
    re.IGNORECASE | re.DOTALL,
)


class LLMError(RuntimeError):
    """Raised when an async LLM provider call fails cleanly."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model_name: str
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 30.0
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    extracted_code_blocks: list[str]
    input_tokens: int = 0
    output_tokens: int = 0


class AsyncLLMManager:
    """Small non-blocking LLM client facade for OpenAI, Anthropic, and Ollama."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.provider = config.provider.lower().strip()
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_seconds),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            headers=config.extra_headers,
        )
        self._openai_client: AsyncOpenAI | None = None

        if self.provider in {"openai", "ollama"}:
            self._openai_client = AsyncOpenAI(
                api_key=config.api_key or "ollama",
                base_url=config.base_url,
                http_client=self._http_client,
            )
        elif self.provider != "anthropic":
            raise ValueError(f"unsupported LLM provider '{config.provider}'")

    async def aclose(self) -> None:
        await self._http_client.aclose()

    async def __aenter__(self) -> "AsyncLLMManager":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def generate_response(
        self,
        system_prompt: str,
        active_context: list[str],
    ) -> LLMResponse:
        messages = self._build_openai_messages(system_prompt, active_context)

        try:
            if self.provider in {"openai", "ollama"}:
                response = await asyncio.wait_for(
                    self._generate_openai_compatible(messages),
                    timeout=self.config.timeout_seconds,
                )
            else:
                response = await asyncio.wait_for(
                    self._generate_anthropic(system_prompt, active_context),
                    timeout=self.config.timeout_seconds,
                )
        except asyncio.TimeoutError as exc:
            raise LLMError(
                f"{self.provider} request exceeded {self.config.timeout_seconds:.0f}s timeout"
            ) from exc
        except Exception as exc:
            raise LLMError(f"{self.provider} request failed: {exc}") from exc

        return response

    async def _generate_openai_compatible(
        self,
        messages: list[dict[str, str]],
    ) -> LLMResponse:
        if self._openai_client is None:
            raise LLMError("OpenAI-compatible client was not initialized")

        completion = await self._openai_client.chat.completions.create(
            model=self.config.model_name,
            messages=messages,
        )
        text = completion.choices[0].message.content or ""
        usage = completion.usage

        return LLMResponse(
            text=text,
            extracted_code_blocks=extract_python_code_blocks(text),
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        )

    async def _generate_anthropic(
        self,
        system_prompt: str,
        active_context: list[str],
    ) -> LLMResponse:
        if not self.config.api_key:
            raise LLMError("Anthropic provider requires api_key")

        base_url = self.config.base_url or "https://api.anthropic.com"
        payload = {
            "model": self.config.model_name,
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": "\n\n".join(active_context) if active_context else "Continue.",
                }
            ],
        }
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        response = await self._http_client.post(
            f"{base_url.rstrip('/')}/v1/messages",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        text_parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        text = "\n".join(part for part in text_parts if part)
        usage = data.get("usage", {})

        return LLMResponse(
            text=text,
            extracted_code_blocks=extract_python_code_blocks(text),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    @staticmethod
    def _build_openai_messages(
        system_prompt: str,
        active_context: list[str],
    ) -> list[dict[str, str]]:
        user_context = "\n\n".join(active_context).strip() or "No active context is available."
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_context},
        ]


def extract_python_code_blocks(markdown_text: str) -> list[str]:
    blocks: list[str] = []
    for match in CODE_BLOCK_PATTERN.finditer(markdown_text):
        language = (match.group("language") or "").strip().lower()
        code = normalize_code_block(match.group("code"))
        if not code:
            continue
        if language in {"", "python", "py"} or code.startswith("def "):
            blocks.append(code)
    return blocks


def normalize_code_block(code: str) -> str:
    cleaned = code.strip()
    cleaned = cleaned.replace("\\\\n", "\n")
    cleaned = cleaned.replace("\\n", "\n")
    cleaned = cleaned.replace("\\t", "    ")
    cleaned = cleaned.replace('\\"', '"')
    cleaned = cleaned.replace("\\'", "'")
    return cleaned.strip()
