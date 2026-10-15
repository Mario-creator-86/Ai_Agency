"""Answer, or think and then answer.

Local Ollama generation asks for thinking off, so a model's whole token budget goes to its
visible answer — which is right for a model that then answers plainly (qwen3.5 verifies a
claim in seventy tokens). Some models do the opposite: asked not to think, they narrate their
reasoning into the answer instead — the Director on `glm-5.3` wrote twelve thousand tokens
of inventory and reached the JSON only as the budget ran out; asked a second time to
"just format it", it narrated again. Such a model answers cleanly only when it is allowed
to think natively, where the reasoning stays out of the visible text. Ollama Cloud is
therefore asked nothing about thinking at all (`integrations.llm`, 2026-10-15): the first
attempt there already thinks natively, and the second attempt below matters for the rest.

So a structured answer is asked for twice at most: once with thinking off; if no object at all
comes back, once more with the model's own thinking on and the same budget. No model is
named here: the studio learns each one from what it does.

The other failure is an object that came and that the schema refused (2026-10-11, the Director
on kimi-k3): her QC decision was asked five times for the cyclotron film, every first answer a
complete REPAIR refused for a reason longer than 400 characters, every second attempt — the same
words, thinking on — spent its 6,000 tokens on reasoning and answered nothing. The shape alone
is fitted before it is refused now (`identity.fit_to_schema`), so that answer validates the
first time; an object refused for its content (a finding not judged, a layer not open, a REPAIR
nothing of which can be done) is asked again in JSON mode, thinking off, with the refusal quoted
in plain words at the end of the prompt: the model wrote the object once, and what must change
is the content, which it is told.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine

from app.agents.identity import read_structured
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
#: The second attempt after an object the schema refused: the same question, the refusal quoted
#: (`identity.refusal_words`), JSON mode again and thinking off.
REFUSED_NOTE = (
    "\n\nYour previous answer was refused: {errors}. Answer again, same content, within these "
    "rules."
)
#: What the run's template version carries for each kind of second attempt.
THINKING_SUFFIX = "+think"
REFUSED_SUFFIX = "+again"
#: What a refused run's ``error_detail`` says in the caller's note (the run itself succeeded;
#: the studio refused what it said), followed by the refusal in plain words.
REFUSED_WORDS = "răspuns refuzat de forma cerută: "


def _carry_refusal(result: dict[str, Any], refusal: str | None) -> None:
    """A second attempt that gave no object (narration, an empty answer, a failed run) still
    names the first attempt's refusal: callers read the last run, and its note must say what
    was wrong with the answer that was an answer (review of 2026-10-11)."""
    if refusal is None or result.get("refusal"):
        return
    result["refusal"] = refusal
    detail = str(result.get("error_detail") or "").strip()
    result["error_detail"] = (
        f"{detail} {REFUSED_WORDS}{refusal}" if detail else REFUSED_WORDS + refusal
    )


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
    extra: dict[str, Any] | None = None,
    model_id: str | None = None,
) -> tuple[T | None, dict[str, Any], dict[str, Any] | None]:
    """Run the task; when the answer does not validate, run it once more the way its failure
    asks: no object at all, the same prompt with native thinking; an object the schema refused
    even fitted, the prompt with the refusal quoted, thinking off. Two attempts at most.

    Returns (parsed or None, the first run, the second run or None). A run whose object the
    schema refused carries ``refusal`` (the errors in plain words) and, having none of its own,
    an ``error_detail`` that says so — so a caller's waiting note names what was wrong, not
    «răspuns fără forma cerută». ``schema_hint`` and ``format_tokens`` are kept for callers.
    ``model_id`` runs both attempts on that model instead of the agent's own
    (`run_agent_task`), e.g. one that can see the pictures attached.
    """
    del schema_hint, format_tokens
    attempts: list[dict[str, Any]] = []
    parsed: T | None = None
    refusal: str | None = None
    for attempt in (0, 1):
        again = attempt == 1 and refusal is not None
        native = attempt == 1 and refusal is None
        if again:
            asked = prompt + REFUSED_NOTE.format(errors=refusal)
            version = template_version + REFUSED_SUFFIX
            said: str | None = f"{summary or task_type} (a doua încercare, cu motivele refuzului)"
        elif native:
            asked, version = prompt, template_version + THINKING_SUFFIX
            said = f"{summary or task_type} (a doua încercare, cu gândire proprie)"
        else:
            asked, version, said = prompt, template_version, summary
        result = run_agent_task(
            engine,
            registry,
            agent_id,
            task_type,
            asked,
            version,
            correlation_id,
            summary=said,
            max_tokens=max_tokens,
            temperature=temperature,
            emit_message=False,
            extra={**(NATIVE_THINKING if native else JSON_ONLY), **(extra or {})},
            model_id=model_id,
        )
        attempts.append(result)
        text = result.get("output_text") or ""
        if result["status"] != "SUCCEEDED" or not text.strip():
            _carry_refusal(result, refusal)
            break
        candidate, why = read_structured(text, schema)
        if isinstance(candidate, schema):
            parsed = candidate
            if native and result.get("model_name"):
                NATIVE_THINKING_MODELS.add(str(result["model_name"]))
            break
        if why is not None:
            result["refusal"] = why
            if not result.get("error_detail"):
                result["error_detail"] = REFUSED_WORDS + why
        else:
            _carry_refusal(result, refusal)
        if attempt == 1:
            break  # asked twice: nothing more to try today
        refusal = why
        logger.info(
            "structured_answer_invalid",
            extra={
                "task_type": task_type,
                "model": result.get("model_name"),
                "refused": why is not None,
            },
        )
    first = attempts[0]
    second = attempts[1] if len(attempts) > 1 else None
    return parsed, first, second
