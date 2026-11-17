"""Codex app-server adapter, ported from TradingMaus (src/thesisdesk/codex.py) and extended.

- Sign-in stays in the user's Codex credential store (`codex login`); this process never sees a token.
- Talks JSON-RPC over stdio to `codex app-server --listen stdio://`.
- Shell, file edits, apps, MCP and web search are disabled; the sandbox is read-only with no network.
- New versus TradingMaus: Nabd's own Python tools are exposed through the app-server's experimental
  `dynamicTools`, so Codex can call them (`item/tool/call`) and the backend computes every figure.
  Every other server request (approvals, user input) is refused.
- Streams `item/agentMessage/delta` text to an `on_event` callback for SSE.

Data notice: with the codex provider, prompts and tool results go to OpenAI under the signed-in ChatGPT plan.
Demo use with open data only; never CBUAE data.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

CLIENT_INFO = {"name": "nabd", "title": "Nabd", "version": "0.1.0"}
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "multi_agent", "hooks", "remote_plugin", "goals", "plugins",
    "browser_use", "browser_use_external", "computer_use", "image_generation", "in_app_browser",
    "skill_search", "tool_suggest", "view_image", "workspace_dependencies", "skill_mcp_dependency_install",
    "plugin_discovery_prefetch", "sleep_tool", "memories",
)

EventCallback = Callable[[str, dict], Any]


class CodexRPCError(RuntimeError):
    def __init__(self, details):
        data = details.get("data", {}) if isinstance(details, dict) else {}
        self.authentication_required = data.get("errorCode") == "Auth" and data.get("statusCode") == 401
        self.code = "authentication_required" if self.authentication_required else "rpc_rejected"
        msg = (
            "Codex sign-in expired; run `codex login`"
            if self.authentication_required
            else f"Codex rejected the request: {details.get('message', '') if isinstance(details, dict) else ''}"
        )
        super().__init__(msg)
        self.details = details


class CodexTurnError(RuntimeError):
    """Safe error summary; never render arbitrary upstream bodies or credentials."""

    def __init__(self, details):
        details = details if isinstance(details, dict) else {}
        raw = details.get("message", "")
        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            body = {}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        self.code = error.get("code") if isinstance(error, dict) else None
        if self.code == "invalid_json_schema":
            message = "Codex rejected the structured response schema (invalid_json_schema)"
        else:
            self.code = details.get("codexErrorInfo") or "turn_failed"
            # Codex's own error text (not an upstream body) is short and safe to show, e.g. "model not supported".
            hint = raw if raw and not body and len(raw) < 200 else ""
            message = f"Codex turn failed ({self.code})" + (f": {hint}" if hint else "")
        super().__init__(message)


def output_schema(model: type[BaseModel]) -> dict:
    """Strict structured output requires every property listed as required and no extra properties."""
    schema = model.model_json_schema()

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object" or "properties" in node:
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def child_environment(codex_home: str | None) -> dict:
    # Do not pass the backend's keys or arbitrary shell environment to the child.
    names = (
        "PATH", "HOME", "USER", "TMPDIR", "LANG", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
        "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SYSTEMROOT",
    )
    env = {k: os.environ[k] for k in names if k in os.environ}
    if codex_home:
        env["CODEX_HOME"] = codex_home
    return env


def profile_extensions(codex_home: str | None) -> list[tuple[str, str]]:
    """MCP servers and plugins configured in the user's Codex profile, which Nabd's sessions must not load."""
    import tomllib
    from pathlib import Path

    path = Path(codex_home or Path.home() / ".codex") / "config.toml"
    try:
        cfg = tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return [(sec, name) for sec in ("mcp_servers", "plugins") for name in (cfg.get(sec) or {})]


@dataclass
class Tool:
    """A backend function Codex may call. `fn` receives the parsed arguments and returns JSON-able data."""

    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any | Awaitable[Any]]

    def spec(self) -> dict:
        return {"type": "function", "name": self.name, "description": self.description,
                "inputSchema": self.parameters}


@dataclass
class TurnResult:
    text: str
    parsed: BaseModel | None
    tool_calls: list[dict]
    ms: int
    model: str | None


class CodexSession:
    def __init__(
        self,
        *,
        codex_bin: str,
        workspace,
        instructions: str,
        tools: list[Tool] | None = None,
        model: str | None = None,
        codex_home: str | None = None,
        timeout_seconds: int = 180,
        web_domains: list[str] | None = None,
    ):
        self.codex_bin = codex_bin
        self.workspace = workspace
        self.instructions = instructions
        self.tools = {t.name: t for t in (tools or [])}
        self.model = model
        self.codex_home = codex_home
        self.timeout_seconds = timeout_seconds
        # Hosted web search, restricted to these domains; None keeps it off.
        self.web_domains = web_domains
        self.process: asyncio.subprocess.Process | None = None
        self.reader: asyncio.Task | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.notifications: asyncio.Queue = asyncio.Queue()
        self.counter = 0
        self.thread_id: str | None = None
        self.lock = asyncio.Lock()
        self._on_event: EventCallback | None = None
        self._tool_calls: list[dict] = []
        self.on_web = None  # optional hook: turns a web search into a numbered evidence item
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ---------- transport ----------
    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "id" in msg and "method" not in msg:
                    future = self.pending.pop(msg["id"], None)
                    if future and not future.done():
                        if "error" in msg:
                            future.set_exception(CodexRPCError(msg["error"]))
                        else:
                            future.set_result(msg.get("result", {}))
                elif "id" in msg:
                    asyncio.create_task(self._server_request(msg))
                else:
                    await self.notifications.put(msg)
        except OSError:
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Codex app-server disconnected"))
            self.pending.clear()
            await self.notifications.put({"method": "disconnected"})

    async def _send(self, msg):
        self.process.stdin.write((json.dumps(msg) + "\n").encode())
        await self.process.stdin.drain()

    async def rpc(self, method, params, wait_s: float = 30):
        self.counter += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[self.counter] = future
        await self._send({"id": self.counter, "method": method, "params": params})
        return await asyncio.wait_for(future, wait_s)

    async def _emit(self, kind: str, data: dict):
        if self._on_event:
            r = self._on_event(kind, data)
            if inspect.isawaitable(r):
                await r

    async def _server_request(self, msg):
        """Only Nabd's own tools are served; approvals and user-input requests are refused."""
        if msg.get("method") != "item/tool/call":
            await self._send({"id": msg["id"], "error": {"code": -32601, "message": "Not available in Nabd"}})
            return
        p = msg.get("params", {})
        name, args, call_id = p.get("tool"), p.get("arguments") or {}, p.get("callId")
        if isinstance(args, str):
            with contextlib.suppress(ValueError):
                args = json.loads(args)
        tool = self.tools.get(name)
        started = time.perf_counter()
        await self._emit("tool.start", {"call_id": call_id, "tool": name, "args": args})
        try:
            if not tool:
                raise KeyError(f"unknown tool {name}")
            out = tool.fn(**args) if isinstance(args, dict) else tool.fn(args)
            if inspect.isawaitable(out):
                out = await out
            ok, payload = True, out
        except Exception as exc:  # the model sees a short error, never a traceback
            ok, payload = False, {"error": f"{type(exc).__name__}: {exc}"[:400]}
        ms = int((time.perf_counter() - started) * 1000)
        record = {"call_id": call_id, "tool": name, "args": args, "ok": ok, "ms": ms, "result": payload}
        self._tool_calls.append(record)
        await self._emit("tool.result", record)
        text = json.dumps(payload, default=str)
        await self._send({"id": msg["id"], "result": {
            "success": ok, "contentItems": [{"type": "inputText", "text": text[:60000]}]}})

    async def _web_search(self, item: dict):
        """Record a hosted web search as evidence, like a tool call, so its sources can be cited and checked."""
        action = item.get("action") or {}
        query = item.get("query") or action.get("query") or ", ".join(action.get("queries") or []) or action.get("url")
        results = []
        for r in (item.get("results") or [])[:8]:
            if isinstance(r, dict):
                results.append({k: r.get(k) for k in ("title", "url", "snippet", "text") if r.get(k)})
        record = {"call_id": item.get("id"), "tool": "web_search", "args": {"query": query}, "ok": True, "ms": 0,
                  "result": {"action": action.get("type"), "results": results}}
        if self.on_web:
            out = self.on_web(record)
            if inspect.isawaitable(out):
                out = await out
            record = out or record
        self._tool_calls.append(record)
        await self._emit("tool.start", {k: record[k] for k in ("call_id", "tool", "args")})
        await self._emit("tool.result", record)

    # ---------- lifecycle ----------
    async def start(self):
        if self.process and self.process.returncode is None:
            return
        args = [self.codex_bin, "app-server", "--listen", "stdio://"]
        # Nabd's own tools only: switch off every built-in tool, plugin, MCP server and agent feature that the
        # user's personal Codex profile may enable.
        for feature in DISABLED_FEATURES:
            args += ["-c", f"features.{feature}=false"]
        web = '"live"' if self.web_domains else '"disabled"'
        for key, value in {"web_search": web, "analytics.enabled": "false"}.items():
            args += ["-c", f"{key}={value}"]
        if self.web_domains:
            args += ["-c", "tools.web_search.allowed_domains=" + json.dumps(self.web_domains)]
        # `-c mcp_servers={}` merges rather than replaces, so switch off each profile server and plugin by name.
        for section, name in profile_extensions(self.codex_home):
            key = name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else f'"{name}"'  # quoting a bare key breaks merge
            args += ["-c", f"{section}.{key}.enabled=false"]
        self.notifications = asyncio.Queue()
        self.process = await asyncio.create_subprocess_exec(
            *args, cwd=self.workspace, env=child_environment(self.codex_home),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,
        )
        self.reader = asyncio.create_task(self._read())
        await self.rpc("initialize", {"clientInfo": CLIENT_INFO, "capabilities": {"experimentalApi": True}})
        await self._send({"method": "initialized", "params": {}})
        if not self.model:
            # The personal profile's model may not be available to this sign-in; use the account default.
            listed = await self.rpc("model/list", {})
            models = listed.get("data", [])
            default = next((m for m in models if m.get("isDefault")), models[0] if models else None)
            self.model = default.get("id") if default else None
        params: dict[str, Any] = {
            "cwd": str(self.workspace), "approvalPolicy": "never", "sandbox": "read-only",
            "developerInstructions": self.instructions, "ephemeral": True,
        }
        if self.tools:
            params["dynamicTools"] = [t.spec() for t in self.tools.values()]
        if self.model:
            params["model"] = self.model
        result = await self.rpc("thread/start", params)
        self.thread_id = result["thread"]["id"]
        self.model = result.get("model") or self.model

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
        self.process = None

    # ---------- one turn ----------
    async def turn(
        self, text: str, *, schema: type[BaseModel] | None = None, on_event: EventCallback | None = None
    ) -> TurnResult:
        async with self.lock:
            started = time.perf_counter()
            self._on_event, self._tool_calls = on_event, []
            try:
                await self.start()
                while not self.notifications.empty():
                    self.notifications.get_nowait()
                params: dict[str, Any] = {
                    "threadId": self.thread_id,
                    "input": [{"type": "text", "text": text}],
                    "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                }
                if schema:
                    params["outputSchema"] = output_schema(schema)
                result = await self.rpc("turn/start", params)
                turn_id = result["turn"]["id"]
                messages: list[str] = []
                last_error = None
                async with asyncio.timeout(self.timeout_seconds):
                    while True:
                        message = await self.notifications.get()
                        method, p = message.get("method"), message.get("params", {})
                        if method == "disconnected":
                            raise RuntimeError("Codex disconnected during the turn")
                        if p.get("threadId") != self.thread_id:
                            continue
                        if method == "error":
                            last_error = p.get("error")
                        elif method == "item/agentMessage/delta" and p.get("turnId") == turn_id:
                            await self._emit("text.delta", {"delta": p.get("delta", "")})
                        elif method == "item/completed" and p.get("turnId") == turn_id:
                            item = p.get("item", {})
                            if item.get("type") == "agentMessage":
                                messages.append(item.get("text", ""))
                            elif item.get("type") == "webSearch":
                                await self._web_search(item)
                        elif method == "turn/completed" and p.get("turn", {}).get("id") == turn_id:
                            if p["turn"].get("status") != "completed":
                                raise CodexTurnError(p["turn"].get("error") or last_error)
                            break
                final = messages[-1] if messages else ""
                parsed = schema.model_validate_json(final) if schema else None
                return TurnResult(final, parsed, list(self._tool_calls),
                                  int((time.perf_counter() - started) * 1000), self.model)
            except BaseException:
                await self.close()
                raise
            finally:
                self._on_event = None
