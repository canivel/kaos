"""KAOS-side TransferBench integration config (D5).

The user-facing setup surface: a ``bench:`` section in ``kaos.yaml`` plus a
workspace-scoped token issued in the TransferBench SaaS UI. The token NEVER
lives in a file KAOS writes — it is read from the environment (or injected by
the caller), so a committed kaos.yaml can never leak credentials.

    bench:
      enabled: true
      endpoint: https://api.transferbench.dev        # omit for local-only
      workspace: acme-ml                             # SaaS workspace slug/id
      tier: team                                     # individual | team | enterprise
      publish_scope: auto                            # auto | workspace | public_queue | local
      token_env: KAOS_BENCH_TOKEN                    # env var holding the token

Publish routing (D5, R9-preserving — no tier bypasses admission):
  individual  -> 'public_queue'  (public is the default; submits to the public
                                  ADMISSION QUEUE, never a direct write)
  team        -> 'workspace'     (private-first; admin toggle enables promotion)
  enterprise  -> 'workspace'
``publish_scope: auto`` resolves by tier; an explicit value overrides (but
'public_queue' from a team/enterprise account still requires the org's
allow_public_sharing toggle server-side — the client cannot grant it).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VALID_TIERS = ("individual", "team", "enterprise")
VALID_SCOPES = ("auto", "workspace", "public_queue", "local")

_TIER_DEFAULT_SCOPE = {
    "individual": "public_queue",
    "team": "workspace",
    "enterprise": "workspace",
}


@dataclass
class BenchConfig:
    enabled: bool = False            # default OFF: zero behavior change unless opted in
    endpoint: str | None = None      # None = local-only bench, no network ever
    workspace: str | None = None
    tier: str = "individual"
    publish_scope: str = "auto"
    token_env: str = "KAOS_BENCH_TOKEN"
    local_bench_path: str = "bench.db"
    problems: list[str] = field(default_factory=list)  # config-load warnings

    @property
    def is_remote(self) -> bool:
        return self.enabled and bool(self.endpoint)

    def resolved_publish_scope(self) -> str:
        if self.publish_scope != "auto":
            return self.publish_scope
        if not self.is_remote:
            return "local"
        return _TIER_DEFAULT_SCOPE[self.tier]

    def token(self) -> str | None:
        """The push credential — environment only, never persisted by KAOS."""
        return os.environ.get(self.token_env) or None


def load_bench_config(config_path: str | Path = "kaos.yaml") -> BenchConfig:
    """Parse the ``bench:`` section. Missing file/section = disabled (the loop is
    opt-in; ``bench.enabled: false`` degrades to today's behavior exactly)."""
    import yaml

    cfg = BenchConfig()
    p = Path(config_path)
    if not p.exists():
        return cfg
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        cfg.problems.append(f"kaos.yaml unparseable: {e}")
        return cfg
    section = data.get("bench")
    if not isinstance(section, dict):
        return cfg

    cfg.enabled = bool(section.get("enabled", False))
    cfg.endpoint = section.get("endpoint") or None
    cfg.workspace = section.get("workspace") or None
    cfg.local_bench_path = section.get("local_bench_path", cfg.local_bench_path)
    cfg.token_env = section.get("token_env", cfg.token_env)

    tier = str(section.get("tier", cfg.tier)).lower()
    if tier in VALID_TIERS:
        cfg.tier = tier
    else:
        cfg.problems.append(f"bench.tier {tier!r} invalid (one of {VALID_TIERS}); using 'individual'")

    scope = str(section.get("publish_scope", cfg.publish_scope)).lower()
    if scope in VALID_SCOPES:
        cfg.publish_scope = scope
    else:
        cfg.problems.append(
            f"bench.publish_scope {scope!r} invalid (one of {VALID_SCOPES}); using 'auto'")

    # Guardrails the client can enforce early (the server re-enforces all of them).
    if cfg.is_remote and not cfg.workspace:
        cfg.problems.append("bench.endpoint set but bench.workspace missing")
    if cfg.is_remote and cfg.token() is None:
        cfg.problems.append(
            f"bench.endpoint set but ${cfg.token_env} is not set — generate a token "
            f"in the TransferBench UI for your workspace and export it")
    if any(k in section for k in ("token", "api_key", "secret")):
        cfg.problems.append(
            "a token/secret is written in kaos.yaml — remove it; tokens live in the "
            f"environment (${cfg.token_env}) so committed config can never leak them")
    return cfg
