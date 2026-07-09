"""v0.10 router-provider-reliability (RED-FIRST).

The v0.10 panel verified in source (gepa.py):
  - ModelConfig.timeout silently dropped for openai/anthropic/local clients
  - fallback unreachable at default max_retries=1 (dead config)
  - ProposerStalled/TimeoutError taxonomy erased by the RuntimeError rewrap —
    which silently DEFEATS the v0.9 P0 #11 fix whenever the call goes through
    the router (the search loop's `except ProposerStalled` can never fire)
  - auth errors (401) retried like rate limits
  - json.loads on tool-call arguments unguarded (malformed args crash routing)

These tests drive GEPARouter._call_model with fake clients — no real provider.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kaos.router.gepa import GEPARouter, ModelConfig
from kaos.router.providers import ProposerStalled


def _ok_response(text="hello"):
    """Minimal object satisfying _parse_response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=text, tool_calls=None),
            finish_reason="stop",
        )],
        usage=None,
    )


class FakeClient:
    def __init__(self, error: Exception | None = None, text: str = "ok",
                 hang: bool = False):
        self.error = error
        self.text = text
        self.hang = hang
        self.calls = 0

    async def chat(self, **kw):
        self.calls += 1
        if self.hang:
            await asyncio.sleep(3600)
        if self.error is not None:
            raise self.error
        return _ok_response(self.text)


def _router(n_models=2, max_retries=1) -> GEPARouter:
    models = {
        "primary": ModelConfig(name="primary", provider="local",
                               vllm_endpoint="http://localhost:1/v1",
                               timeout=5.0),
    }
    if n_models > 1:
        models["backup"] = ModelConfig(name="backup", provider="local",
                                       vllm_endpoint="http://localhost:2/v1",
                                       timeout=5.0)
    r = GEPARouter(models=models, fallback_model="backup" if n_models > 1 else "primary",
                   max_retries=max_retries)
    # Speed: no real backoff sleeps in tests.
    r.retry_backoff = 0.0
    return r


# ── timeout forwarding ───────────────────────────────────────────────


class TestTimeoutForwarding:
    def test_local_provider_gets_config_timeout(self):
        models = {"m": ModelConfig(name="m", provider="local",
                                   vllm_endpoint="http://localhost:1/v1",
                                   timeout=555.0)}
        r = GEPARouter(models=models)
        assert getattr(r.clients["m"], "timeout", None) == 555.0, (
            "ModelConfig.timeout silently dropped for local provider"
        )

    def test_openai_provider_gets_config_timeout(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        models = {"m": ModelConfig(name="m", provider="openai",
                                   model_id="gpt-x", timeout=444.0)}
        r = GEPARouter(models=models)
        assert getattr(r.clients["m"], "timeout", None) == 444.0

    def test_anthropic_provider_gets_config_timeout(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        models = {"m": ModelConfig(name="m", provider="anthropic",
                                   model_id="claude-x", timeout=333.0)}
        r = GEPARouter(models=models)
        assert getattr(r.clients["m"], "timeout", None) == 333.0


# ── error taxonomy must survive the router ───────────────────────────


class TestErrorTaxonomy:
    def test_proposer_stalled_passes_through_untouched(self):
        r = _router(n_models=1)
        r.clients["primary"] = FakeClient(error=ProposerStalled("idle 60s"))
        with pytest.raises(ProposerStalled):
            asyncio.run(r._call_model(r.clients["primary"], "primary",
                                      [], [], {}))

    def test_timeout_error_passes_through_untouched(self):
        r = _router(n_models=1)
        r.clients["primary"] = FakeClient(error=TimeoutError("wall 300s"))
        with pytest.raises(TimeoutError):
            asyncio.run(r._call_model(r.clients["primary"], "primary",
                                      [], [], {}))

    def test_generic_error_still_wrapped_actionably(self):
        r = _router(n_models=1)
        r.clients["primary"] = FakeClient(error=ValueError("boom"))
        with pytest.raises(RuntimeError) as ei:
            asyncio.run(r._call_model(r.clients["primary"], "primary",
                                      [], [], {}))
        assert "boom" in str(ei.value)


# ── auth errors: fail fast, don't burn retries ───────────────────────


class TestAuthNotRetried:
    def test_401_not_retried_on_same_client(self):
        r = _router(n_models=1, max_retries=3)
        client = FakeClient(error=RuntimeError("401 Unauthorized: invalid api key"))
        r.clients["primary"] = client
        with pytest.raises(RuntimeError):
            asyncio.run(r._call_model(client, "primary", [], [], {}))
        assert client.calls == 1, (
            f"auth error was retried {client.calls}x — burning retries on a "
            f"credential problem"
        )

    def test_rate_limit_is_retried(self):
        r = _router(n_models=1, max_retries=3)
        client = FakeClient(error=RuntimeError("429 Too Many Requests"))
        r.clients["primary"] = client
        with pytest.raises(RuntimeError):
            asyncio.run(r._call_model(client, "primary", [], [], {}))
        assert client.calls == 3, "retryable error should use all retries"


# ── fallback must actually be reachable ──────────────────────────────


class TestFallbackReachable:
    def test_fallback_fires_at_default_max_retries_1(self):
        """With the shipped default max_retries=1, fallback_model was dead
        config: `if attempt < self.max_retries - 1` is `0 < 0`."""
        r = _router(n_models=2, max_retries=1)
        primary = FakeClient(error=RuntimeError("connection refused"))
        backup = FakeClient(text="from-backup")
        r.clients["primary"] = primary
        r.clients["backup"] = backup
        resp = asyncio.run(r._call_model(primary, "primary", [], [], {}))
        assert resp.content == "from-backup"
        assert backup.calls == 1, "fallback client never invoked"

    def test_no_fallback_when_primary_is_fallback(self):
        r = _router(n_models=1, max_retries=1)
        client = FakeClient(error=RuntimeError("connection refused"))
        r.clients["primary"] = client
        with pytest.raises(RuntimeError):
            asyncio.run(r._call_model(client, "primary", [], [], {}))


# ── wall-clock ceiling for slow-drip transports ──────────────────────


class TestWallClockCeiling:
    def test_hanging_client_hits_router_wall(self):
        """httpx read timeout is between-bytes; a slow-drip server never
        trips it. The router must enforce an absolute wall."""
        models = {"m": ModelConfig(name="m", provider="local",
                                   vllm_endpoint="http://localhost:1/v1",
                                   timeout=0.2)}
        r = GEPARouter(models=models)
        r.retry_backoff = 0.0
        r.wall_margin = 0.1  # test-speed margin over cfg.timeout
        client = FakeClient(hang=True)
        r.clients["m"] = client
        with pytest.raises(TimeoutError):
            asyncio.run(r._call_model(client, "m", [], [], {}))


# ── malformed tool args must not crash routing ───────────────────────


class TestToolArgsGuard:
    def _resp_with_args(self, args):
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[{"id": "t1",
                                 "function": {"name": "fs_write",
                                              "arguments": args}}],
                ),
                finish_reason="tool_calls",
            )],
            usage=None,
        )

    def test_valid_json_args_parse(self):
        out = GEPARouter._parse_response(self._resp_with_args('{"path": "/x"}'))
        assert out.tool_calls[0].input == {"path": "/x"}

    def test_malformed_args_wrapped_as_raw(self):
        out = GEPARouter._parse_response(
            self._resp_with_args('{"path": "/x", TRAILING GARBAGE'))
        assert out.tool_calls[0].input == {"raw": '{"path": "/x", TRAILING GARBAGE'}

    def test_dict_args_pass_through(self):
        out = GEPARouter._parse_response(self._resp_with_args({"a": 1}))
        assert out.tool_calls[0].input == {"a": 1}
