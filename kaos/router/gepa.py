"""GEPA Router — Generalized Execution Planning & Allocation.

Routes agent requests to the optimal model based on task complexity,
context length, and available compute.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from kaos.ccr.runner import ModelResponse, ToolCall
from kaos.router.classifier import HeuristicClassifier, LLMClassifier
from kaos.router.context import ContextCompressor
from kaos.router.providers import LLMProvider, create_provider
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
        max_retries: int = 3,
    ):
        self.models = models
        self.fallback_model = fallback_model or next(iter(models))
        self.max_retries = max_retries
        self.context_compression = context_compression
        self.compressor = ContextCompressor()

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
                )
            elif cfg.provider == "claude_code":
                self.clients[name] = create_provider(
                    "claude_code",
                    model_id=cfg.model_id,
                )
            else:
                # Default: local vLLM/ollama endpoint
                self.clients[name] = VLLMClient(base_url=cfg.vllm_endpoint)

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
            )

        router_cfg = config.get("router", {})
        return cls(
            models=models,
            classifier_model=router_cfg.get("classifier_model"),
            fallback_model=router_cfg.get("fallback_model"),
            context_compression=router_cfg.get("context_compression", True),
            max_retries=router_cfg.get("max_retries", 3),
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

    async def _call_model(
        self,
        client: VLLMClient | LLMProvider,
        model_name: str,
        messages: list[dict],
        tools: list[dict],
        config: dict,
    ) -> ModelResponse:
        """Call a model via any provider (local vLLM, OpenAI, or Anthropic)."""
        # Use model_id for API providers (e.g. "gpt-4o"), model_name for local
        model_config = self.models.get(model_name)
        actual_model = model_config.model_id if model_config and model_config.model_id else model_name

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await client.chat(
                    model=actual_model,
                    messages=messages,
                    temperature=config.get("temperature", 0.1),
                    max_tokens=config.get("max_tokens", 4096),
                    tools=tools or None,
                    tool_choice="auto" if tools else None,
                )
                return self._parse_response(response)
            except Exception as e:
                last_error = e
                logger.warning(
                    "Model call attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    self.max_retries,
                    model_name,
                    e,
                )
                if attempt < self.max_retries - 1:
                    if model_name != self.fallback_model:
                        logger.info("Falling back to %s", self.fallback_model)
                        client = self.clients[self.fallback_model]
                        model_name = self.fallback_model

        raise RuntimeError(
            f"All {self.max_retries} model call attempts failed. Last error: {last_error}"
        )

    @staticmethod
    def _parse_response(response) -> ModelResponse:
        """Parse a ChatCompletion into a ModelResponse."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        input=json.loads(tc["function"]["arguments"]),
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
