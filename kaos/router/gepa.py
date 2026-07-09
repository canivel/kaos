"""GEPA Router — Generalized Execution Planning & Allocation.

Routes agent requests to the optimal model based on task complexity,
context length, and available compute.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from kaos.ccr.runner import ModelResponse, ToolCall
from kaos.router.classifier import HeuristicClassifier, LLMClassifier
from kaos.router.context import ContextCompressor
from kaos.router.providers import LLMProvider, ProposerStalled, create_provider
from kaos.router.vllm_client import VLLMClient

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """Configuration for a model backend.

    Supports three provider types:
      - local: vLLM/ollama/llama.cpp (default, uses vllm_endpoint)
      - openai: OpenAI API or any OpenAI-compatible cloud endpoint
      - anthropic: Anthropic Claude API
    """

    name: str
    vllm_endpoint: str = ""
    max_context: int = 32768
    use_for: list[str] = field(default_factory=list)
    provider: str = "local"  # "local" | "openai" | "anthropic"
    model_id: str = ""  # API model ID (e.g. "gpt-4o", "claude-sonnet-4-20250514")
    api_key_env: str = ""  # env var name for API key (e.g. "OPENAI_API_KEY")
    timeout: float = 300.0  # per-call timeout seconds


class GEPARouter:
    """
    Intelligent request routing based on task complexity.

    Uses an LLM classifier (calling local vLLM via raw httpx) to classify
    task complexity and route to the optimal model. Falls back to heuristic
    classification when no classifier model is configured.

    No openai SDK. No litellm. No dspy. Just httpx to your local vLLM.
    """

    def __init__(
        self,
        models: dict[str, ModelConfig],
        routing_table: dict[str, str] | None = None,
        classifier_model: str | None = None,
        fallback_model: str | None = None,
        context_compression: bool = True,
        max_retries: int = 1,
    ):
        self.models = models
        self.fallback_model = fallback_model or next(iter(models))
        self.max_retries = max_retries
        self.context_compression = context_compression
        self.compressor = ContextCompressor()
        # Exponential backoff base between retries of the SAME client
        # (0.5s, 1s, 2s, ...). Tests set 0 for speed.
        self.retry_backoff = 0.5
        # Router-level absolute wall over each call = cfg.timeout + margin.
        # httpx read timeouts are between-bytes, so a slow-drip server never
        # trips them; this ceiling is the safety net. The margin gives
        # providers with their own wall (claude_code, agent_sdk) room to fire
        # first with their richer error taxonomy.
        self.wall_margin = 30.0

        # Routing table: complexity -> model name
        self.routing_table = routing_table or self._build_routing_table()

        # Initialize provider clients — one per model
        self.clients: dict[str, VLLMClient | LLMProvider] = {}
        for name, cfg in models.items():
            if cfg.provider in ("openai", "anthropic"):
                self.clients[name] = create_provider(
                    cfg.provider,
                    api_key_env=cfg.api_key_env,
                    endpoint=cfg.vllm_endpoint or None,
                    timeout=cfg.timeout,
                )
            elif cfg.provider in ("claude_code", "agent_sdk"):
                self.clients[name] = create_provider(
                    cfg.provider,
                    model_id=cfg.model_id,
                    timeout=cfg.timeout,
                )
            else:
                # Default: local vLLM/ollama endpoint
                self.clients[name] = VLLMClient(base_url=cfg.vllm_endpoint,
                                                timeout=cfg.timeout)

        # Initialize classifier: LLM if a classifier model is available, else heuristic
        if classifier_model and classifier_model in models:
            self.classifier = LLMClassifier(
                client=self.clients[classifier_model],
                model=classifier_model,
            )
            self._classifier_is_async = True
            logger.info("Using LLM classifier with model: %s", classifier_model)
        else:
            self.classifier = HeuristicClassifier()
            self._classifier_is_async = False
            logger.info("No classifier model configured, using heuristic classifier")

    def _build_routing_table(self) -> dict[str, str]:
        """Build routing table from model use_for annotations."""
        table = {}
        for name, cfg in self.models.items():
            for use in cfg.use_for:
                if use not in table:
                    table[use] = name
        for complexity in ("trivial", "moderate", "complex", "critical"):
            if complexity not in table:
                table[complexity] = self.fallback_model
        return table

    @classmethod
    def from_config(cls, config_path: str) -> GEPARouter:
        """Create a router from a YAML config file."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        models = {}
        for name, mcfg in config.get("models", {}).items():
            provider = mcfg.get("provider", "local")
            endpoint = mcfg.get("vllm_endpoint") or mcfg.get("endpoint", "")
            if provider == "local" and not endpoint:
                endpoint = "http://localhost:8000/v1"
            models[name] = ModelConfig(
                name=name,
                vllm_endpoint=endpoint,
                max_context=mcfg.get("max_context", 32768),
                use_for=mcfg.get("use_for", []),
                provider=provider,
                model_id=mcfg.get("model_id", name),
                api_key_env=mcfg.get("api_key_env", ""),
                timeout=float(mcfg.get("timeout", 300.0)),
            )

        router_cfg = config.get("router", {})
        return cls(
            models=models,
            classifier_model=router_cfg.get("classifier_model"),
            fallback_model=router_cfg.get("fallback_model"),
            context_compression=router_cfg.get("context_compression", True),
            max_retries=router_cfg.get("max_retries", 1),
        )

    async def route(
        self,
        agent_id: str,
        messages: list[dict],
        tools: list[dict],
        config: dict,
    ) -> ModelResponse:
        """
        Route an inference request to the optimal model.

        1. Classify task complexity (LLM or heuristic)
        2. Select model based on routing table
        3. Compress context if needed
        4. Call model via vLLM
        """
        force_model = config.get("force_model")

        if force_model and force_model in self.models:
            model_name = force_model
        else:
            task_desc = ""
            for msg in reversed(messages):
                if msg.get("role") in ("user", "system"):
                    task_desc = str(msg.get("content", ""))
                    break

            context_length = sum(len(str(m.get("content", ""))) for m in messages)
            tool_count = len(tools)

            if self._classifier_is_async:
                classification = await self.classifier.classify(
                    task_description=task_desc[:500],
                    context_length=context_length,
                    tool_count=tool_count,
                )
            else:
                classification = self.classifier.classify(
                    task_description=task_desc[:500],
                    context_length=context_length,
                    tool_count=tool_count,
                )

            logger.info(
                "Agent %s: task classified as %s (confidence: %.2f, %s)",
                agent_id,
                classification.complexity,
                classification.confidence,
                classification.reasoning,
            )
            model_name = self.routing_table.get(
                classification.complexity, self.fallback_model
            )

        model_config = self.models[model_name]

        if self.context_compression:
            max_tokens = int(model_config.max_context * 0.85)
            messages = self.compressor.compress(messages, max_tokens)

        client = self.clients[model_name]
        return await self._call_model(client, model_name, messages, tools, config)

    @staticmethod
    def _is_auth_error(e: Exception) -> bool:
        """Credential problems don't heal on retry — fail fast."""
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (401, 403):
            return True
        s = str(e).lower()
        return any(marker in s for marker in (
            "401", "403", "unauthorized", "forbidden",
            "invalid api key", "authentication",
        ))

    async def _call_model(
        self,
        client: VLLMClient | LLMProvider,
        model_name: str,
        messages: list[dict],
        tools: list[dict],
        config: dict,
    ) -> ModelResponse:
        """Call a model via any provider, with an honest failure policy:

        - ``ProposerStalled`` / ``TimeoutError`` re-raise UNTOUCHED. The
          meta-harness search loop's survival contract (P0 #11) depends on
          catching these types; the old blanket RuntimeError rewrap silently
          defeated that fix whenever the call went through the router.
        - Auth errors (401/403/invalid key) are never retried on the same
          client — a credential problem doesn't heal on attempt 2.
        - The fallback model is tried AFTER the primary's retries are
          exhausted, independent of max_retries. (Previously fallback lived
          inside `if attempt < max_retries - 1`, which at the shipped default
          max_retries=1 made fallback_model dead config.)
        - Each call runs under an absolute wall of cfg.timeout + wall_margin,
          because httpx read timeouts are between-bytes and a slow-drip
          server never trips them.
        - Retries of the same client back off exponentially.
        """
        candidates = [model_name]
        if self.fallback_model and self.fallback_model != model_name \
                and self.fallback_model in self.clients:
            candidates.append(self.fallback_model)

        last_error: Exception | None = None
        failed_name = model_name
        for idx, cand in enumerate(candidates):
            cand_client = client if cand == model_name else self.clients[cand]
            cand_cfg = self.models.get(cand)
            actual_model = cand_cfg.model_id if cand_cfg and cand_cfg.model_id else cand
            wall = (cand_cfg.timeout if cand_cfg else 300.0) + self.wall_margin
            if idx > 0:
                logger.info("Falling back to %s", cand)

            for attempt in range(max(1, self.max_retries)):
                try:
                    response = await asyncio.wait_for(
                        cand_client.chat(
                            model=actual_model,
                            messages=messages,
                            temperature=config.get("temperature", 0.1),
                            max_tokens=config.get("max_tokens", 4096),
                            tools=tools or None,
                            tool_choice="auto" if tools else None,
                        ),
                        timeout=wall,
                    )
                    return self._parse_response(response)
                except (ProposerStalled, TimeoutError):
                    # Taxonomy the caller depends on — propagate untouched.
                    # (asyncio.TimeoutError IS TimeoutError on 3.11+, so the
                    # router wall surfaces the same way a provider wall does.)
                    raise
                except Exception as e:
                    last_error = e
                    failed_name = cand
                    logger.warning(
                        "Model call attempt %d/%d failed for %s: %s",
                        attempt + 1, max(1, self.max_retries), cand, e,
                    )
                    if self._is_auth_error(e):
                        # Try the next candidate (may use different creds),
                        # but never re-drive the same client.
                        break
                    if attempt < max(1, self.max_retries) - 1 and self.retry_backoff:
                        await asyncio.sleep(
                            min(self.retry_backoff * (2 ** attempt), 8.0)
                        )

        # Build an actionable error message
        err_str = str(last_error)
        hint = ""
        if "Connection" in err_str or "refused" in err_str.lower():
            model_cfg = self.models.get(failed_name)
            endpoint = model_cfg.vllm_endpoint if model_cfg else "unknown"
            hint = f" Is the model server running at {endpoint}?"
        elif self._is_auth_error(last_error) if last_error else False:
            hint = " Check the API key env var in kaos.yaml (api_key_env)."
        elif "timeout" in err_str.lower():
            hint = " Try increasing the timeout in kaos.yaml."
        raise RuntimeError(
            f"Model call failed for '{failed_name}': {last_error}.{hint}"
        )

    @staticmethod
    def _parse_response(response) -> ModelResponse:
        """Parse a ChatCompletion into a ModelResponse."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                raw_args = tc["function"]["arguments"]
                if isinstance(raw_args, dict):
                    parsed_args = raw_args
                else:
                    try:
                        parsed_args = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        # Models occasionally emit malformed JSON args. Don't
                        # crash routing — surface the raw text so the tool
                        # layer (or a future action-realization gate) can
                        # decide what to do with it.
                        parsed_args = {"raw": raw_args}
                tool_calls.append(
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        input=parsed_args,
                    )
                )

        stop_reason = "end_turn"
        if choice.finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif choice.finish_reason == "length":
            stop_reason = "max_tokens"

        usage = None
        if response.usage:
            u = response.usage
            # VLLMClient uses prompt_tokens/completion_tokens; LLMProvider uses input_tokens/output_tokens
            inp = getattr(u, "prompt_tokens", None) or getattr(u, "input_tokens", 0)
            out = getattr(u, "completion_tokens", None) or getattr(u, "output_tokens", 0)
            tot = getattr(u, "total_tokens", None) or (inp + out)
            usage = {
                "prompt_tokens": inp,
                "completion_tokens": out,
                "total_tokens": tot,
            }

        return ModelResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )
