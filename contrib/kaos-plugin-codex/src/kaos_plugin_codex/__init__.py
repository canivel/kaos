"""kaos-plugin-codex — OpenAI Codex CLI as a KAOS model provider.

``codex exec`` is a non-interactive agent runner that authenticates through
``codex login`` (ChatGPT subscription or API key — the user's choice, not
ours). KAOS talks to it exactly like the built-in ``claude_code`` provider
talks to ``claude --print``: the whole conversation is serialized into one
prompt under the shared ``<tool_call>`` protocol, sent on stdin, and the
model's final message is parsed back into an ``LLMResponse``.

Why ``--output-last-message`` instead of stdout: ``codex exec`` prints a
human transcript (sandbox line, echoed prompt, "tokens used" ...) on stdout.
The ``-o FILE`` flag writes *only* the final assistant message, which is the
single thing we need and keeps the tool-call parser honest.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

__version__ = "0.1.0"

DEFAULT_MODEL = "gpt-5.1"
_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")


def find_codex(explicit: str = "") -> str:
    """Resolve the codex executable: explicit arg > $CODEX_EXECUTABLE > PATH > known paths."""
    candidates = [
        explicit,
        os.environ.get("CODEX_EXECUTABLE", ""),
        shutil.which("codex") or "",
        os.path.expanduser("~/.local/bin/codex"),
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise FileNotFoundError(
        "codex CLI not found. Install it (npm i -g @openai/codex) and run "
        "`codex login`, or set CODEX_EXECUTABLE / codex_executable in kaos.yaml."
    )


def build_command(
    exe: str,
    model: str,
    out_file: str,
    *,
    sandbox: str = "read-only",
    cwd: str | None = None,
    reasoning_effort: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Pure function so the exact CLI contract is unit-testable."""
    if sandbox not in _SANDBOXES:
        raise ValueError(f"sandbox must be one of {_SANDBOXES}, got {sandbox!r}")
    cmd = [
        exe, "exec",
        "-m", model,
        "--sandbox", sandbox,
        "--skip-git-repo-check",
        "--ephemeral",
        "--color", "never",
        "-o", out_file,
    ]
    if cwd:
        cmd += ["-C", cwd]
    if reasoning_effort:
        cmd += ["-c", f'model_reasoning_effort="{reasoning_effort}"']
    if extra_args:
        cmd += list(extra_args)
    cmd.append("-")  # read the prompt from stdin
    return cmd


def make_codex_provider(**model_kwargs: Any):
    """Factory called by the router: ``factory(**model_kwargs) -> LLMProvider``.

    ``kaos.router.providers`` lives behind the ``[router]`` extra, so import it
    lazily — the plugin stays loadable on a slim install.
    """
    from kaos.router.providers import (
        LLMProvider,
        LLMResponse,
        ProposerStalled,
        parse_tool_response,
        serialize_conversation,
    )

    class CodexProvider(LLMProvider):
        def __init__(
            self,
            model_id: str = DEFAULT_MODEL,
            timeout: float = 300.0,
            idle_timeout: float = 120.0,
            sandbox: str = "read-only",
            cwd: str | None = None,
            reasoning_effort: str | None = None,
            codex_executable: str = "",
            extra_args: list[str] | None = None,
            **_: Any,  # tolerate router kwargs we don't use (endpoint, api_key_env)
        ) -> None:
            self.model_id = model_id or DEFAULT_MODEL
            self.timeout = float(timeout)          # wall (hard kill)
            self.idle_timeout = float(idle_timeout)  # no new bytes => ProposerStalled
            self.sandbox = sandbox
            self.cwd = cwd
            self.reasoning_effort = reasoning_effort
            self.extra_args = list(extra_args or [])
            self._exe = find_codex(codex_executable)

        # ── LLMProvider contract ─────────────────────────────────────────
        async def chat(
            self,
            model: str,
            messages: list[dict],
            temperature: float = 0.1,   # codex exec has no temperature knob
            max_tokens: int = 4096,     # nor a max_tokens knob; documented no-ops
            tools: list[dict] | None = None,
            tool_choice: str | None = None,
        ) -> LLMResponse:
            prompt = serialize_conversation(messages, tools).encode("utf-8")
            fd, out_path = tempfile.mkstemp(prefix="kaos-codex-", suffix=".md")
            os.close(fd)
            try:
                cmd = build_command(
                    self._exe, model or self.model_id, out_path,
                    sandbox=self.sandbox, cwd=self.cwd,
                    reasoning_effort=self.reasoning_effort,
                    extra_args=self.extra_args,
                )
                await self._run(cmd, prompt)
                text = Path(out_path).read_text(encoding="utf-8", errors="replace")
            finally:
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
            if not text.strip():
                raise RuntimeError(
                    "codex exec produced an empty final message. Check `codex login` "
                    "and that the model id is available on your plan."
                )
            return parse_tool_response(text)

        async def _run(self, cmd: list[str], prompt: bytes) -> None:
            """Run codex with an idle timeout (stall) and a wall timeout (hard kill)."""
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            assert proc.stdin and proc.stdout and proc.stderr
            proc.stdin.write(prompt)
            await proc.stdin.drain()
            proc.stdin.close()

            stderr_chunks: list[bytes] = []

            async def _drain_stderr() -> None:
                while True:
                    chunk = await proc.stderr.read(4096)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)

            drain = asyncio.create_task(_drain_stderr())
            loop = asyncio.get_running_loop()
            start = loop.time()
            try:
                while True:
                    remaining = self.timeout - (loop.time() - start)
                    if remaining <= 0:
                        raise TimeoutError(
                            f"codex exec exceeded wall timeout of {self.timeout:.0f}s"
                        )
                    try:
                        chunk = await asyncio.wait_for(
                            proc.stdout.read(4096),
                            timeout=min(self.idle_timeout, remaining),
                        )
                    except asyncio.TimeoutError:
                        if loop.time() - start >= self.timeout:
                            raise TimeoutError(
                                f"codex exec exceeded wall timeout of {self.timeout:.0f}s"
                            )
                        raise ProposerStalled(
                            f"codex exec produced no output for {self.idle_timeout:.0f}s"
                        )
                    if not chunk:
                        break  # EOF: process is finishing
                await asyncio.wait_for(proc.wait(), timeout=max(5.0, remaining))
            except BaseException:
                if proc.returncode is None:
                    proc.kill()
                    try:
                        await proc.wait()
                    except Exception:
                        pass
                raise
            finally:
                drain.cancel()
                try:
                    await drain
                except (asyncio.CancelledError, Exception):
                    pass
            if proc.returncode != 0:
                err = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"codex exec exited {proc.returncode}: {err[-2000:] or '(no stderr)'}"
                )

        async def close(self) -> None:
            return None

    return CodexProvider(**model_kwargs)


def register(registry) -> None:
    """Called by KAOS. ``registry`` is a ``kaos.plugins.PluginRegistry``."""
    registry.add_provider("codex", make_codex_provider)
