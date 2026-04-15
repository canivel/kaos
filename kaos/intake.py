"""Intake step — dynamic clarifying questions before an agent runs.

The intake agent analyzes a task description and returns only the clarifying
questions a builder would genuinely need answered before starting. The number
of questions is dynamic — zero is a valid answer for a fully-specified task,
and there is no upper bound hard-coded anywhere.

This module is called by `kaos run --ask`. It is not required for normal
execution; `kaos run` without `--ask` starts the agent immediately with the
provided task, exactly as before.

Flow:
    1. analyze(task, router)          → list[Question]  (0 or more)
    2. ask_interactively(questions)   → dict[str, str]  (user answers)
    3. enrich_task(task, answers)     → str             (task + Q&A appended)
    4. runner.run_agent(agent_id, enriched_task)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from kaos.router.gepa import GEPARouter


INTAKE_SYSTEM_PROMPT = """You are the KAOS intake agent. Your only job is to read a task \
description and identify the clarifying questions a builder genuinely needs answered before \
starting — not a fixed number, only the questions that matter.

Rules:
1. Only flag ambiguities that would materially affect architecture, scope, or integration.
2. Do NOT ask about things that can be reasonably inferred, defaulted, or decided later.
3. Do NOT ask about taste/preferences (fonts, colors, variable names).
4. Some tasks need 0 questions. Some need 5. There is NO fixed count — ask the minimum.
5. If the task is fully specified, return an empty JSON array: []

Return ONLY a JSON array of objects with this shape — no markdown fences, no commentary:
[
  {"question": "<the clarifying question>", "why": "<brief reason it materially matters>"}
]

If no questions are needed, return exactly: []
"""


@dataclass
class Question:
    """One clarifying question from the intake agent."""

    question: str
    why: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"question": self.question, "why": self.why}


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences if the model wrapped output."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json\n or ```\n)
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _extract_json_array(text: str) -> str:
    """Find the first JSON array in the text (for robustness against prose prefixes)."""
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


async def analyze(
    task: str,
    router: GEPARouter,
    force_model: str | None = None,
) -> list[Question]:
    """Call the intake agent and return a list of clarifying questions (0 or more).

    Args:
        task: The task description the user passed to `kaos run`.
        router: A configured GEPARouter.
        force_model: Optional model override for the intake step.

    Returns:
        A list of Question objects. Empty list means the task is fully
        specified and no clarifications are needed.
    """
    messages = [
        {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Task:\n\n{task}\n\nReturn the JSON array now."},
    ]

    config: dict[str, Any] = {"temperature": 0.0, "max_tokens": 1024}
    if force_model:
        config["force_model"] = force_model

    response = await router.route(
        agent_id="intake-agent",
        messages=messages,
        tools=[],
        config=config,
    )

    raw = (response.content or "").strip()
    if not raw:
        return []

    stripped = _strip_code_fences(raw)
    candidate = _extract_json_array(stripped)

    try:
        items = json.loads(candidate)
    except json.JSONDecodeError:
        # Model returned unparseable output. Treat as "no questions" rather
        # than crashing the run — the task will proceed without enrichment.
        return []

    if not isinstance(items, list):
        return []

    questions: list[Question] = []
    for item in items:
        if isinstance(item, dict) and "question" in item:
            questions.append(
                Question(
                    question=str(item["question"]).strip(),
                    why=str(item.get("why", "")).strip(),
                )
            )
        elif isinstance(item, str):
            questions.append(Question(question=item.strip()))
    return questions


def ask_interactively(questions: list[Question]) -> dict[str, str]:
    """Print questions and collect answers from stdin.

    Blank answers are allowed (skipped). Returns a dict of question→answer.
    If the list is empty, returns {} without printing anything.
    """
    if not questions:
        return {}

    n = len(questions)
    noun = "ambiguity" if n == 1 else "ambiguities"
    print(f"\nintake-agent flagged {n} {noun} before proceeding:\n")
    for i, q in enumerate(questions, 1):
        print(f"  {i}. {q.question}")
        if q.why:
            print(f"     \u2192 {q.why}")
        print()

    print("Answer each (blank to skip):\n")
    answers: dict[str, str] = {}
    for i, q in enumerate(questions, 1):
        try:
            ans = input(f"  [{i}] > ").strip()
        except EOFError:
            ans = ""
        if ans:
            answers[q.question] = ans
    return answers


def enrich_task(task: str, answers: dict[str, str]) -> str:
    """Append clarifications to the original task so the runner sees full context."""
    if not answers:
        return task
    lines = [task, "", "Clarifications from user:"]
    for q, a in answers.items():
        lines.append(f"- Q: {q}")
        lines.append(f"  A: {a}")
    return "\n".join(lines)
