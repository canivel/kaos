"""Harness evaluator — runs a harness candidate against a benchmark.

Each evaluation:
1. Spawns a KAOS agent for the harness
2. Writes the harness source to the agent's VFS
3. Runs the harness against each problem
4. Captures full execution traces (the critical ingredient per the paper)
5. Returns scored results
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import time
import traceback
from typing import Any, TYPE_CHECKING

from kaos.metaharness.harness import HarnessCandidate, EvaluationResult

if TYPE_CHECKING:
    from kaos.core import Kaos
    from kaos.metaharness.benchmarks.base import Benchmark, Problem
    from kaos.router.gepa import GEPARouter

logger = logging.getLogger(__name__)


class HarnessEvaluator:
    """Evaluates harness candidates against a benchmark using KAOS agents."""

    def __init__(
        self,
        afs: Kaos,
        router: GEPARouter,
        benchmark: Benchmark,
        timeout_seconds: int = 300,
    ):
        self.afs = afs
        self.router = router
        self.benchmark = benchmark
        self.timeout_seconds = timeout_seconds

    async def evaluate(
        self,
        harness: HarnessCandidate,
        problems: list[Problem] | None = None,
    ) -> EvaluationResult:
        """Evaluate a harness candidate against the benchmark.

        Args:
            harness: The harness candidate to evaluate.
            problems: Override problem set (default: benchmark search set).

        Returns:
            EvaluationResult with scores, traces, and per-problem breakdown.
        """
        problems = problems or self.benchmark.get_search_set()
        agent_id = self.afs.spawn(
            f"harness-{harness.harness_id[:10]}",
            config={
                "harness_id": harness.harness_id,
                "role": "evaluator",
            },
        )

        # Write harness source to agent's VFS
        self.afs.write(agent_id, "/harness.py", harness.source_code.encode())
        self.afs.set_state(agent_id, "harness_id", harness.harness_id)

        start_time = time.time()
        trace = []
        per_problem = []

        try:
            # Load the harness module dynamically
            run_fn = self._load_harness(harness)

            for problem in problems:
                problem_start = time.time()
                try:
                    output = await asyncio.wait_for(
                        self._run_single(run_fn, problem, agent_id),
                        timeout=self.timeout_seconds / max(len(problems), 1),
                    )
                    scores = self.benchmark.score(problem, output)
                    is_correct = scores.get("accuracy", scores.get("pass_rate", scores.get("f1_score", 0))) > 0.5
                    per_problem.append({
                        "problem_id": problem.problem_id,
                        "correct": is_correct,
                        "scores": scores,
                        "output": _truncate(output, 2000),
                    })
                    # Rich trace entry — the paper's ablation shows raw traces
                    # are the critical ingredient (15+ points over scores-only)
                    trace.append({
                        "type": "problem_eval",
                        "problem_id": problem.problem_id,
                        "input_preview": _truncate(str(problem.input.get("text", problem.input)), 300),
                        "expected": str(problem.expected)[:200],
                        "harness_output": _truncate(output, 1500),
                        "prompt_preview": _truncate(output.get("prompt", ""), 500) if isinstance(output, dict) else "",
                        "prediction": str(output.get("prediction", output.get("prompt", "")))[:200] if isinstance(output, dict) else "",
                        "correct": is_correct,
                        "scores": scores,
                        "context_tokens": output.get("context_tokens", 0) if isinstance(output, dict) else 0,
                        "duration_ms": int((time.time() - problem_start) * 1000),
                    })
                except asyncio.TimeoutError:
                    per_problem.append({
                        "problem_id": problem.problem_id,
                        "correct": False,
                        "scores": {k.lstrip("+-"): 0.0 for k in self.benchmark.objectives},
                        "error": "timeout",
                    })
                    trace.append({
                        "type": "problem_timeout",
                        "problem_id": problem.problem_id,
                    })
                except Exception as e:
                    per_problem.append({
                        "problem_id": problem.problem_id,
                        "correct": False,
                        "scores": {k.lstrip("+-"): 0.0 for k in self.benchmark.objectives},
                        "error": str(e),
                    })
                    trace.append({
                        "type": "problem_error",
                        "problem_id": problem.problem_id,
                        "error": str(e),
                        "traceback": traceback.format_exc()[-500:],
                    })

            # Aggregate scores
            scored_problems = [p["scores"] for p in per_problem if "scores" in p]
            aggregate = self.benchmark.aggregate_scores(scored_problems)
            duration_ms = int((time.time() - start_time) * 1000)

            # Log the evaluation to the agent's VFS
            self.afs.write(
                agent_id,
                "/evaluation/scores.json",
                json.dumps(aggregate, indent=2).encode(),
            )
            self.afs.write(
                agent_id,
                "/evaluation/per_problem.jsonl",
                "\n".join(json.dumps(p) for p in per_problem).encode(),
            )
            self.afs.set_state(agent_id, "scores", aggregate)
            self.afs.complete(agent_id)

            return EvaluationResult(
                harness_id=harness.harness_id,
                scores=aggregate,
                trace=trace,
                per_problem=per_problem,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.afs.fail(agent_id, error=str(e))
            return EvaluationResult(
                harness_id=harness.harness_id,
                scores={},
                trace=trace,
                duration_ms=duration_ms,
                error=f"{type(e).__name__}: {e}",
            )

    async def evaluate_parallel(
        self,
        harnesses: list[HarnessCandidate],
        problems: list[Problem] | None = None,
        max_parallel: int = 4,
    ) -> list[EvaluationResult]:
        """Evaluate multiple harnesses in parallel."""
        semaphore = asyncio.Semaphore(max_parallel)

        async def _eval(h: HarnessCandidate) -> EvaluationResult:
            async with semaphore:
                return await self.evaluate(h, problems)

        return await asyncio.gather(*[_eval(h) for h in harnesses])

    async def _run_single(
        self,
        run_fn: Any,
        problem: Problem,
        agent_id: str,
    ) -> dict:
        """Run a harness's run() function on a single problem."""
        # Call the harness — may be sync or async
        if asyncio.iscoroutinefunction(run_fn):
            result = await run_fn(problem.input)
        else:
            result = await asyncio.get_event_loop().run_in_executor(
                None, run_fn, problem.input
            )

        if not isinstance(result, dict):
            result = {"prediction": str(result)}

        # Log tool call for auditability
        call_id = self.afs.log_tool_call(
            agent_id,
            "harness_run",
            {"problem_id": problem.problem_id},
        )
        self.afs.start_tool_call(call_id)
        self.afs.complete_tool_call(
            call_id,
            {"output": _truncate(result, 500)},
            status="success",
            token_count=result.get("context_tokens"),
        )

        return result

    def _load_harness(self, harness: HarnessCandidate) -> Any:
        """Load a harness's run() function from its source code.

        Injects an `llm(prompt, **kwargs)` callable into the harness module
        so harnesses can call the configured LLM without importing anything.
        """
        module_name = f"_harness_{harness.harness_id[:12]}"
        spec = importlib.util.spec_from_loader(module_name, loader=None)
        module = importlib.util.module_from_spec(spec)

        # Inject llm() callable — harnesses can call llm("prompt") to get a response
        module.llm = self._make_llm_callable()

        exec(compile(harness.source_code, f"<harness:{harness.harness_id[:12]}>", "exec"), module.__dict__)

        if not hasattr(module, "run"):
            raise ValueError("Harness source does not define a run() function")

        return module.run

    def _make_llm_callable(self):
        """Create a sync llm(prompt) callable that uses the configured router.

        Harnesses call: response = llm("classify this text", max_tokens=64)
        Returns the text response as a string.
        """
        router = self.router

        def llm(prompt: str, *, model: str = "", max_tokens: int = 256,
                temperature: float = 0.1) -> str:
            """Call the configured LLM. Returns the response text."""
            import asyncio as _aio

            messages = [{"role": "user", "content": prompt}]
            fallback_model = router.fallback_model
            actual_model = model or fallback_model

            client = router.clients.get(actual_model) or next(iter(router.clients.values()))
            model_cfg = router.models.get(actual_model)
            model_id = model_cfg.model_id if model_cfg else actual_model

            async def _call():
                resp = await client.chat(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if resp.choices:
                    return resp.choices[0].message.content or ""
                return ""

            # Run in the current event loop if possible, else create one
            try:
                loop = _aio.get_running_loop()
                # We're in an async context — run in executor to avoid blocking
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_aio.run, _call())
                    return future.result(timeout=router.models.get(actual_model, type("", (), {"timeout": 600})).timeout)
            except RuntimeError:
                return _aio.run(_call())

        return llm


def _truncate(obj: Any, max_chars: int) -> Any:
    """Truncate an object's string representation for trace storage."""
    if isinstance(obj, str):
        return obj[:max_chars] if len(obj) > max_chars else obj
    if isinstance(obj, dict):
        s = json.dumps(obj)
        if len(s) > max_chars:
            # Return a safe summary — never try to parse a mid-string truncation
            return {"__truncated__": True, "original_size": len(s),
                    "preview": s[:max_chars - 50] + "..."}
        return obj
    return obj
