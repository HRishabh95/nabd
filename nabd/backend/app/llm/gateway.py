"""One LLM interface for the app, so the provider can switch without touching callers.

codex        ChatGPT sign-in through the Codex CLI. Demo only: prompts go to OpenAI.
azure_openai Azure OpenAI in UAE North, for the CBUAE environment (phase 7).
local        Open-weight model served on premise, OpenAI-compatible (phase 7).
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from ..core.config import get_settings
from ..core.db import store
from .codex_session import CodexSession, EventCallback, Tool, TurnResult


class LLMUnavailable(RuntimeError):
    pass


class Gateway:
    def __init__(self):
        self.settings = get_settings()

    @property
    def provider(self) -> str:
        return self.settings.llm_provider

    def session(self, purpose: str, instructions: str, tools: list[Tool] | None = None,
                web_domains: list[str] | None = None) -> CodexSession:
        if self.provider != "codex":
            raise LLMUnavailable(f"Provider {self.provider!r} is planned for the client environment; use codex")
        s = self.settings
        return CodexSession(
            codex_bin=s.codex_bin,
            workspace=(s.data_dir / "agent-workspaces" / purpose).resolve(),
            instructions=instructions,
            tools=tools,
            model=s.codex_model,
            codex_home=s.codex_home,
            timeout_seconds=s.llm_timeout_seconds,
            web_domains=web_domains,
        )

    async def run(
        self,
        purpose: str,
        instructions: str,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        tools: list[Tool] | None = None,
        on_event: EventCallback | None = None,
        web_domains: list[str] | None = None,
        on_web=None,
        timeout_seconds: int | None = None,
    ) -> TurnResult:
        """One-shot turn in a fresh, ephemeral thread. Logged (no prompt text) for model governance."""
        session = self.session(purpose, instructions, tools, web_domains)
        session.on_web = on_web
        if timeout_seconds:
            session.timeout_seconds = timeout_seconds
        started = time.perf_counter()
        try:
            result = await session.turn(prompt, schema=schema, on_event=on_event)
            store.log_llm(self.provider, result.model, purpose, True, result.ms)
            return result
        except Exception as exc:
            store.log_llm(self.provider, None, purpose, False, int((time.perf_counter() - started) * 1000),
                          type(exc).__name__)
            raise
        finally:
            await session.close()


gateway = Gateway()
