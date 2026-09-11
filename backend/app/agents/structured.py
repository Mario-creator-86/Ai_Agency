"""Answer, or think and then answer.

Ollama generation asks for thinking off, so a model's whole token budget goes to its visible
answer — which is right for a model that then answers plainly (qwen3.5 verifies a claim in
seventy tokens). Some models do the opposite: asked not to think, they narrate their
reasoning into the answer instead — the Director on `glm-5.3` wrote twelve thousand tokens
of inventory and reached the JSON only as the budget ran out; asked a second time to
"just format it", it narrated again. Such a model answers cleanly only when it is allowed
to think natively, where the reasoning stays out of the visible text.

So a structured answer is asked for twice at most: once with thinking off; if no object
validates, once more with the model's own thinking on and the same budget. No model is
named here: the studio learns each one from what it does.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine

from app.agents.identity import parse_structured
from app.agents.services import run_agent_task
from app.providers.registry import ProviderRegistry

logger = logging.getLogger("studio.structured")

#: Models observed to answer only with their own thinking on — kept as a record of what the
#: studio learned this process, readable in a debugger or a log; no model is assumed anything.
NATIVE_THINKING_MODELS: set[str] = set()

NATIVE_THINKING = {"think": True}
#: The first attempt also asks the provider to constrain the output to JSON. A model that
#: answers plainly (qwen3.5 did, in 133 tokens) is held to the object; one that narrates
#: regardless (glm-5.3 did, even so) is caught by the parse and gets its second attempt.
JSON_ONLY = {"format": "json"}


def structured_run[T: BaseModel](
    engine: Engine,
    registry: ProviderRegistry,
    agent_id: str,
    task_type: str,
    prompt: str,
    template_version: str,
    correlation_id: str,
    schema: type[T],
    schema_hint: str,
    *,
    summary: str | None = None,
    max_tokens: int,
    temperature: float = 0.1,
    format_tokens: int = 0,
) -> tuple[T | None, dict[str, Any], dict[str, Any] | None]:
    """Run the task; when no object validates, run it once more with native thinking.

    Returns (parsed or None, the first run, the second run or None). ``schema_hint`` and
    ``format_tokens`` are kept for callers; the second attempt is the same prompt.
    """
    del schema_hint, format_tokens
    attempts: list[dict[str, Any]] = []
    parsed: T | None = None
    for attempt in (0, 1):
        native = attempt == 1
        result = run_agent_task(
            engine,
            registry,
            agent_id,
            task_type,
            prompt,
            template_version + ("+think" if native else ""),
            correlation_id,
            summary=(
                summary
                if attempt == 0
                else f"{summary or task_type} (a doua încercare, cu gândire proprie)"
            ),
            max_tokens=max_tokens,
            temperature=temperature,
            emit_message=False,
            extra=NATIVE_THINKING if native else JSON_ONLY,
        )
        attempts.append(result)
        text = result.get("output_text") or ""
        if result["status"] != "SUCCEEDED" or not text.strip():
            break
        candidate = parse_structured(text, schema)
        if isinstance(candidate, schema):
            parsed = candidate
            if native and result.get("model_name"):
                NATIVE_THINKING_MODELS.add(str(result["model_name"]))
            break
        if native:
            break  # thought natively and still no object: nothing more to try today
        logger.info(
            "structured_answer_narrated",
            extra={"task_type": task_type, "model": result.get("model_name")},
        )
    first = attempts[0]
    second = attempts[1] if len(attempts) > 1 else None
    return parsed, first, second
