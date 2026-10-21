"""The writers' frozen evaluation harness (`scripts/writer_eval.py`, `app.evals`).

The Owner's card of 2026-10-16 («măsurăm întâi»): no playbook or judge change goes live without
a comparison on frozen past days, judged by a stranger who sees only what a viewer sees. These
tests hold the harness to that, on stand-ins only (no vendor, no credit; conftest refuses the
network):

- the case file is read strictly, and a case naming anything but a nightly backup is refused;
- the stranger's view carries no writer note, purpose, part, room code, claim or event id,
  stage direction or role;
- the three question orders are balanced, a pairwise preference that flips is a tie, and the
  kappa is Cohen's;
- the registry refuses any media adapter before a model is asked;
- the variant registry, ``baseline`` first;
- discovery on synthetic scans (before / after the day was written, the serial's memory
  replayed, the golden pairs) and on a real copy, then ``--dry-run``, which asks no model;
- one whole run on a tiny backup with a fake language model: the writer pinned to its model,
  the lesson reading switched off, the checks, the stranger's three orders on a bare identity,
  the pairwise in both orders, the golden pair, the agreement with the Owner's labels, the
  report, the backup untouched and the copies gone.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import Agent, ModelRecord
from app.agents.services import seed_initial_workforce
from app.evals import stranger, variants
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult, LLMProvider
from app.providers.media_base import ImageProvider
from app.providers.registry import ProviderRegistry
from app.publishing.services import seed_default_channels
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_editorial_quality import a_topic
from test_serial_pipeline import YESTERDAY_NOON, a_day, beats_for, episode_answer, roster_names

ROOT = Path(__file__).resolve().parents[1]
BACKUP = "studio-20261015T003018Z.db"


def _harness():
    spec = importlib.util.spec_from_file_location(
        "writer_eval", ROOT / "scripts" / "writer_eval.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["writer_eval"] = module
    spec.loader.exec_module(module)
    return module


we = _harness()


# ---------------------------------------------------------------------------
# The case file
# ---------------------------------------------------------------------------


def frozen_serial(title: str = "The Quiet Desk") -> dict[str, Any]:
    return stranger.frozen_episode(
        title,
        [
            {
                "scene": "The script room at dawn; Sarah at the long desk.",
                "lines": [
                    {"speaker": "Narrator", "text": "The script room, before anyone arrives."},
                    {"speaker": "Sarah (Director)", "text": "Where is the number?"},
                ],
            }
        ],
    )


def frozen_factual(title: str = "The Address Nobody May Buy") -> dict[str, Any]:
    return stranger.frozen_script(
        title,
        [{"narration": "One web address can never be bought.", "visual_description": "A padlock."}],
    )


def a_case_file(path: Path, cases: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    return path


def serial_case(**extra: Any) -> dict[str, Any]:
    return {
        "id": "serial-2026-10-14",
        "kind": "serial",
        "backup": BACKUP,
        "log_id": "log-1",
        "writer_model": "gpt-oss:120b",
        "reference": {
            "kind": "serial",
            "id": "e1",
            "text_key": "episode:e1",
            "view": frozen_serial(),
        },
        **extra,
    }


def test_a_case_file_is_read_and_selected(tmp_path):
    cases = [
        serial_case(),
        {
            "id": "factual-be6dfc6d",
            "kind": "factual",
            "backup": BACKUP,
            "topic_id": "t1",
            "target_seconds": None,
            "reference": None,
        },
        {
            "id": "golden-serial-2026-10-14-editorial",
            "kind": "golden_pair",
            "backup": BACKUP,
            "a": {"kind": "serial", "text_key": "episode:a", "view": frozen_serial("A")},
            "b": {"kind": "serial", "text_key": "episode:b", "view": frozen_serial("B")},
            "expected": "b",
        },
    ]
    loaded = we.load_cases(a_case_file(tmp_path / "cases.json", cases))

    assert [case["id"] for case in loaded] == [case["id"] for case in cases]
    assert [c["id"] for c in we.select_cases(loaded, "factual-be6dfc6d", 0)] == ["factual-be6dfc6d"]
    assert len(we.select_cases(loaded, None, 2)) == 2
    with pytest.raises(we.EvalError, match="necunoscute"):
        we.select_cases(loaded, "serial-1999-01-01", 0)


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"kind": "poem"}, "tipul"),
        ({"log_id": None}, "log_id"),
        ({"backup": "studio.db"}, "copie de noapte"),
        ({"backup": "studio-20261002T134827Z-premigrare.db"}, "copie de noapte"),
        ({"reference": {"kind": "serial", "view": frozen_serial()}}, "text_key"),
        ({"reference": {"text_key": "episode:x", "view": {"kind": "film"}}}, "tip"),
        ({"target_seconds": 5000}, "target_seconds"),
    ],
)
def test_a_malformed_case_is_refused(tmp_path, change, words):
    with pytest.raises(we.EvalError, match=words):
        we.load_cases(a_case_file(tmp_path / "cases.json", [serial_case(**change)]))


def test_a_missing_file_or_a_doubled_id_is_refused(tmp_path):
    with pytest.raises(we.EvalError, match="--discover"):
        we.load_cases(tmp_path / "none.json")
    with pytest.raises(we.EvalError, match="repetate"):
        we.load_cases(a_case_file(tmp_path / "cases.json", [serial_case(), serial_case()]))
    pair = {
        "id": "golden-x",
        "kind": "golden_pair",
        "backup": BACKUP,
        "a": {"kind": "serial", "text_key": "episode:a", "view": frozen_serial()},
    }
    with pytest.raises(we.EvalError, match="textul b"):
        we.load_cases(a_case_file(tmp_path / "pair.json", [pair]))


def test_the_live_database_is_never_a_backup(tmp_path):
    (tmp_path / "backups").mkdir()
    (tmp_path / "studio.db").write_bytes(b"live")
    with pytest.raises(we.EvalError):
        we.backup_file(tmp_path / "backups", "../studio.db")
    with pytest.raises(we.EvalError, match="nu există"):
        we.backup_file(tmp_path / "backups", BACKUP)


# ---------------------------------------------------------------------------
# What the stranger sees
# ---------------------------------------------------------------------------


def test_the_serial_view_carries_only_what_a_viewer_gets():
    beats = [
        {
            "beat_number": 1,
            "part": "hook",
            "location": "director_suite",
            "scene": "The penthouse at night; Sarah at her desk.",
            "lines": [
                {"speaker": "Narrator", "text": "The penthouse, past midnight."},
                {
                    "speaker": "Sarah (Director)",
                    "text": "We ship at dawn.",
                    "direction": "whispering, a writer's note",
                },
            ],
            "background": ["Kael (Video Editor)"],
            "event_ids": ["evt-4242"],
            "characters": ["Sarah (Director)"],
        },
        {
            "part": "button",
            "location": "script_room",
            "scene": "The script room; an empty chair.",
            "lines": [{"speaker": "Kael (Video Editor)", "text": "Dawn came early."}],
            "event_ids": ["evt-4343"],
        },
    ]
    view = stranger.serial_view("Dawn Ship", beats)
    shown = view.render()
    prompt = stranger.question_prompt(view, stranger.ORDERS[0])

    for words in ("The penthouse at night", "We ship at dawn.", "Dawn came early.", "Dawn Ship"):
        assert words in shown
    assert 'NARRATOR (voice-over): "The penthouse, past midnight."' in shown
    assert 'Sarah: "We ship at dawn."' in shown
    for note in (
        "hook",
        "button",
        "director_suite",
        "script_room",
        "evt-4242",
        "whispering",
        "(Director)",
        "Video Editor",
        "beat_number",
    ):
        assert note not in shown, note
        assert note not in prompt.split("</video>")[0], note
    assert shown.startswith("TITLE: Dawn Ship")
    assert view.moments[1].start == view.moments[0].end  # rough times, beat after beat


def test_the_factual_view_shows_the_card_and_hides_purposes_and_claims():
    scenes = [
        {
            "narration": "Two sums, and one of them is tiny.",
            "visual_description": "",
            "purpose": "EVIDENCE",
            "scene_kind": "DATA_CARD",
            "claim_ids": ["claim-xyz"],
            "card": {
                "title": "Climate finance",
                "bars": [
                    {
                        "label": "Promised",
                        "value": 100.0,
                        "unit": "bn USD",
                        "claim_id": "claim-abc",
                    },
                    {"label": "Paid", "value": 12, "unit": "bn USD", "claim_id": "claim-abc"},
                ],
                "highlight": "Paid",
            },
        },
        {
            "narration": "So who pays the rest?",
            "visual_description": "A village seen from above, rain on the roofs.",
            "purpose": "CTA",
            "scene_kind": "LIVE",
            "claim_ids": ["claim-xyz"],
        },
    ]
    frozen = stranger.frozen_script("Who Pays", scenes)
    shown = stranger.view_of(frozen).render()

    assert "A chart titled «Climate finance»: Promised 100 bn USD; Paid 12 bn USD" in shown
    assert "(highlighted: Paid)" in shown
    assert "A village seen from above" in shown
    for note in ("EVIDENCE", "CTA", "DATA_CARD", "LIVE", "claim-xyz", "claim-abc", "purpose"):
        assert note not in shown, note
        assert note not in json.dumps(frozen) or note in ("DATA_CARD", "LIVE"), note


# ---------------------------------------------------------------------------
# Orders, pairs, agreement
# ---------------------------------------------------------------------------


def test_the_three_orders_are_balanced():
    orders = stranger.ORDERS
    count = len(stranger.QUESTIONS)
    assert len(orders) == 3
    assert all(sorted(order) == list(range(count)) for order in orders)
    positions = {question: [order.index(question) for order in orders] for question in range(count)}
    for places in positions.values():
        assert len(set(places)) == len(orders)  # never the same place twice
        assert 5 / 3 - 1e-9 <= sum(places) / len(places) <= 7 / 3 + 1e-9
    assert len({order[0] for order in orders}) == len(orders)  # a different opener each time
    assert len({order[-1] for order in orders}) == len(orders)  # and a different closer
    prompt = stranger.question_prompt(stranger.serial_view("T", []), orders[2])
    asked = [line.split("]")[0].split("[")[1] for line in prompt.splitlines() if "] " in line]
    assert asked == [stranger.QUESTIONS[index].key for index in orders[2]]
    with pytest.raises(ValueError):
        stranger.question_prompt(stranger.serial_view("T", []), (0, 0, 1, 2, 3))


def test_answers_are_read_and_averaged_per_question():
    answer = stranger.StrangerAnswer.model_validate(
        {
            "answers": [
                {"id": "[orient]", "answer": "da", "why": "We see the room."},
                {"id": "story", "answer": "yes", "why": " Someone wants a number. "},
                {"id": "finish", "answer": False, "why": "x" * 900},
                {"id": "ending", "answer": "no"},
                {"id": "surprise", "answer": "No."},
            ]
        }
    )
    by_key = answer.by_key()
    assert by_key["orient"].answer is True and by_key["finish"].answer is False
    assert len(by_key["finish"].why) == stranger.WHY_CHARS
    with pytest.raises(ValueError):
        stranger.StrangerAnswer.model_validate({"answers": [{"id": "orient", "answer": "yes"}] * 5})
    with pytest.raises(ValueError):
        stranger.QuestionAnswer.model_validate({"id": "orient", "answer": "maybe"})

    yes = dict.fromkeys(stranger.QUESTION_KEYS, True)
    combined = stranger.combine([yes, {**yes, "finish": False}, None, {**yes, "finish": False}])
    assert combined["orders_answered"] == 3 and combined["orders_asked"] == 4
    assert combined["questions"]["finish"]["yes_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert combined["questions"]["finish"]["majority"] is False
    assert combined["questions"]["orient"]["majority"] is True
    assert combined["score"] == pytest.approx(4 + 1 / 3, abs=1e-3)
    assert stranger.combine([None, None])["score"] is None


def test_a_pairwise_preference_that_flips_is_a_tie():
    outcome = stranger.pairwise_outcome
    assert outcome("A", "B") == "new"  # new shown first and chosen; shown second, chosen again
    assert outcome("B", "A") == "reference"
    assert outcome("A", "A") == stranger.TIE  # whichever came first won: position, not taste
    assert outcome("B", "B") == stranger.TIE
    assert outcome(None, "A") == stranger.INCOMPLETE
    assert outcome("A", "B", x="a", y="b") == "a"
    assert stranger.PairwiseAnswer.model_validate({"choice": "Video B.", "why": "w"}).choice == "B"
    with pytest.raises(ValueError):
        stranger.PairwiseAnswer.model_validate({"choice": "both"})


def test_cohen_kappa_and_the_agreement_with_the_owner():
    kappa = stranger.cohen_kappa
    assert kappa([True, True, False, False], [True, False, False, False]) == 0.5
    assert kappa([True, False], [False, True]) == -1.0
    assert kappa([True, False, True], [True, False, True]) == 1.0
    assert kappa([True, True], [True, True]) is None  # chance agreement certain: undefined
    assert kappa([], []) is None
    with pytest.raises(ValueError):
        kappa([True], [True, False])

    judge = {
        "episode:1": {"orient": True, "story": True, "finish": None},
        "episode:2": {"orient": False, "story": True},
        "script:3": {"orient": True},
    }
    owner = {
        "episode:1": {"orient": True, "story": False, "finish": True},
        "episode:2": {"orient": False, "story": True},
        "episode:9": {"orient": True},
    }
    found = stranger.agreement(judge, owner)
    assert found["texts"] == ["episode:1", "episode:2"]
    assert found["questions"]["orient"] == {"n": 2, "agree": 2, "percent": 100.0, "kappa": 1.0}
    assert found["questions"]["story"]["n"] == 2 and found["questions"]["story"]["agree"] == 1
    assert found["questions"]["finish"]["n"] == 0  # the judge had no majority
    assert found["pooled"]["n"] == 4 and found["pooled"]["agree"] == 3


# ---------------------------------------------------------------------------
# The registry holds language models only
# ---------------------------------------------------------------------------


class FakeLLM(LLMProvider):
    """A language model that answers by the shape of what it is asked, and remembers it."""

    def __init__(self, episode: str = "", script: str = "", kind: str = "ollama") -> None:
        self.kind = kind
        self.episode = episode
        self.script = script
        self.calls: list[dict[str, Any]] = []

    async def health_check(self) -> HealthResult:
        return HealthResult("HEALTHY")

    async def list_models(self) -> list:
        return []

    async def generate(
        self, model, prompt, *, system=None, max_tokens=None, temperature=None, extra=None
    ) -> GenerateResult:
        self.calls.append({"model": model, "prompt": prompt, "system": system, "extra": extra})
        return GenerateResult(self._answer(prompt), 120, 60, None)

    def _answer(self, prompt: str) -> str:
        if "[orient]" in prompt:
            asked = [
                line.split("]")[0].split("[")[1]
                for line in prompt.splitlines()
                if line[:1].isdigit() and "] " in line
            ]
            # «finish» is yes only when it is asked second: the orders must be averaged.
            return json.dumps(
                {
                    "answers": [
                        {
                            "id": key,
                            "answer": "yes"
                            if key in ("orient", "story") or (key == "finish" and index == 1)
                            else "no",
                            "why": f"Because of the {key}.",
                        }
                        for index, key in enumerate(asked)
                    ]
                }
            )
        if '<video id="A">' in prompt:
            first = prompt.split('<video id="B">')[0]
            choice = "A" if "BETTER" in first else "B" if "BETTER" in prompt else "A"
            return json.dumps({"choice": choice, "why": "The first one holds."})
        if "ALLOWED_NAMES:" in prompt:
            return self.episode
        if "AFIRMAȚII VERIFICATE" in prompt:
            return self.script
        return "Nimic de raportat."

    def systems(self, marker: str) -> list[str | None]:
        return [call["system"] for call in self.calls if marker in call["prompt"]]


class RunPodChat(FakeLLM):
    """A language model by its methods, a GPU vendor by its name."""


class AnImageAdapter(ImageProvider):
    pass


AnImageAdapter.__abstractmethods__ = frozenset()  # an image vendor, as far as the registry sees


def a_registry(*adapters: Any) -> ProviderRegistry:
    registry = ProviderRegistry()
    for index, adapter in enumerate(adapters):
        registry.register(f"p{index}", adapter)
    return registry


def test_the_registry_must_hold_no_media_adapter():
    we.assert_no_media_adapter(a_registry(FakeLLM(), FakeLLM()))
    we.assert_no_media_adapter(ProviderRegistry())
    image = AnImageAdapter()
    for adapter in (image, RunPodChat(), FakeLLM(kind="elevenlabs"), object()):
        with pytest.raises(we.MediaAdapterFound, match="nu se întreabă nimic"):
            we.assert_no_media_adapter(a_registry(FakeLLM(), adapter))


def test_the_live_studios_lock_is_seen_without_taking_it(tmp_path):
    from app.workflows.worker import acquire_worker_lock

    lock = tmp_path / "studio.lock"
    assert we.lock_held(lock) is False  # no file, no studio
    held = acquire_worker_lock(lock)
    assert held is not None
    try:
        assert we.lock_held(lock) is True
        assert any("lacătul" in reason for reason in we.live_studio(lock))
    finally:
        held.release()
    assert we.lock_held(lock) is False
    again = acquire_worker_lock(lock)  # asking took nothing: the studio could still start
    assert again is not None
    again.release()


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def test_the_variant_registry():
    from app.story import services as story_services

    assert "baseline" in variants.names()
    assert variants.variant("baseline").name == "baseline"
    with pytest.raises(ValueError, match="cunoscute: .*baseline"):
        variants.variant("no-such-variant")
    with pytest.raises(ValueError, match="există deja"):
        variants.register(
            variants.Variant(
                "baseline", "again", lambda: variants.replaced(story_services, "SHOW_TONE", "x")
            )
        )
    with pytest.raises(ValueError):
        variants.register(variants.Variant(" spaced", "bad name", lambda: None))  # type: ignore

    before = variants.fingerprint("serial")
    tone = story_services.SHOW_TONE
    with variants.replaced(story_services, "SHOW_TONE", tone + " Louder."):
        inside = variants.fingerprint("serial")
        assert story_services.SHOW_TONE.endswith("Louder.")
    assert story_services.SHOW_TONE == tone
    assert inside["brief_sha256"] != before["brief_sha256"]
    assert inside["identity_sha256"] == before["identity_sha256"]
    assert variants.fingerprint("serial") == before
    assert variants.fingerprint("factual")["brief_sha256"] != before["brief_sha256"]
    with pytest.raises(AttributeError):
        with variants.replaced(story_services, "NO_SUCH_NAME", 1):
            pass
    with pytest.raises(ValueError):
        variants.fingerprint("poem")

    name = f"test-{uuid4().hex[:8]}"
    registered = variants.register(
        variants.Variant(
            name,
            "a louder tone",
            lambda: variants.replaced(story_services, "SHOW_TONE", tone + " Louder."),
        )
    )
    try:
        with variants.variant(name).install():
            assert story_services.SHOW_TONE.endswith("Louder.")
        assert story_services.SHOW_TONE == tone
    finally:
        variants._VARIANTS.pop(registered.name)


# ---------------------------------------------------------------------------
# Discovery on scans
# ---------------------------------------------------------------------------


def _episode(log_id, title, status, created, verdict, continuity=None, beats=None):
    return {
        "log_id": log_id,
        "title": title,
        "status": status,
        "created_at": created,
        "verdict": verdict,
        "beats": beats or [{"scene": "A room.", "lines": [{"speaker": "Sarah", "text": "Hi."}]}],
        "continuity": continuity or {},
    }


def _scan(
    logs, episodes, *, continuity=None, advanced=(), judged=None, topics=None, scripts=None
) -> dict[str, Any]:
    return {
        "logs": logs,
        "episodes": episodes,
        "drafted": {},
        "advanced": list(advanced),
        "judged": judged or {},
        "runs": [],
        "continuity": continuity,
        "topics": topics or {},
        "scripts": scripts or {},
        "writer_model": "gpt-oss:120b",
    }


def test_discovery_proposes_the_days_the_topics_and_the_golden_pairs():
    day_one = {"business_date": "2026-10-14", "status": "CLOSED", "closed_at": "x", "projected": 4}
    day_two = {"business_date": "2026-10-15", "status": "CLOSED", "closed_at": "y", "projected": 4}
    plan = {"premise": "p", "status": "KEPT", "judged_in": "e3"}
    approved_one = _episode(
        "L1",
        "Twenty-Eight Rewrites",
        "APPROVED",
        "2026-10-15T05:02:00+00:00",
        "PASS",
        {
            "summary": "s1",
            "business_date": "2026-10-14",
            "next_episode": plan,
            "threads_opened": ["Who brings the number?"],
        },
    )
    episodes_late = {
        "e1": _episode("L1", "Twenty-Eight Notes", "REJECTED", "2026-10-15T05:00:00+00:00", "PASS"),
        "e2": approved_one,
        "e3": _episode(
            "L2",
            "Blocked Log",
            "APPROVED",
            "2026-10-15T22:06:00+00:00",
            "PASS",
            {"summary": "s2", "business_date": "2026-10-15"},
        ),
    }
    scans = {
        "studio-20261015T003018Z.db": _scan(
            {"L1": day_one},
            {},
            continuity=None,
            topics={
                "T1": {
                    "title": "Kelvin",
                    "created_at": "2026-10-05",
                    "thesis": True,
                    "supported": 3,
                }
            },
        ),
        "studio-20261016T015919Z.db": _scan(
            {"L1": day_one, "L2": day_two},
            episodes_late,
            continuity={
                "version": 3,
                "canon_episode_number": 2,
                "threads_json": [],
                "recurring_json": [],
                "summaries_json": [],
            },
            advanced=[("2026-10-15T05:03:00+00:00", "e2"), ("2026-10-15T23:07:00+00:00", "e3")],
            judged={"e1": {"total": 26}, "e2": {"total": 38}},
            topics={
                "T1": {
                    "title": "Kelvin",
                    "created_at": "2026-10-05",
                    "thesis": True,
                    "supported": 3,
                }
            },
            scripts={
                "s1": {
                    "topic_id": "T1",
                    "version": 1,
                    "status": "APPROVED",
                    "created_at": "2026-10-15T10:00:00+00:00",
                    "target": 30,
                    "title": "Kelvin's Floor",
                    "verdict": "PASS",
                    "scenes": [{"narration": "Zero is not zero."}],
                }
            },
        ),
    }
    proposal = we.propose_cases(scans, "2026-10-14")
    cases = {case["id"]: case for case in proposal["cases"]}

    first = cases["serial-2026-10-14"]
    assert first["backup"] == "studio-20261015T003018Z.db" and first["state"] == "before_write"
    assert first["reference"]["id"] == "e2" and first["reference"]["editorial_total"] == 38
    assert first["continuity_before"]["row"]["canon_episode_number"] == 0  # nothing approved yet

    second = cases["serial-2026-10-15"]
    assert second["state"] == "after_write" and second["backup"] == "studio-20261016T015919Z.db"
    memory = second["continuity_before"]
    assert memory["replayed"] == ["e2"]  # approved after the older copy, before this day
    assert memory["row"]["canon_episode_number"] == 1
    assert memory["row"]["summaries_json"][-1]["title"] == "Twenty-Eight Rewrites"
    assert memory["row"]["threads_json"][0]["text"] == "Who brings the number?"
    assert memory["plan_episode"]["id"] == "e2"
    assert memory["plan_episode"]["next_episode"]["status"] == "PLANNED"  # judged only later
    assert "judged_in" not in memory["plan_episode"]["next_episode"]

    factual = cases["factual-T1"]
    assert factual["state"] == "before_write" and factual["target_seconds"] is None
    assert factual["original_target_seconds"] == 30
    assert factual["reference"]["text_key"] == "script:s1"

    golden = cases["golden-serial-2026-10-14-editorial"]
    assert (golden["a"]["id"], golden["b"]["id"], golden["expected"]) == ("e1", "e2", "b")
    assert "26/50 against 38/50" in golden["note"]
    for case in proposal["cases"]:  # the proposal is a case file the harness reads
        we.validate_case(case)


# ---------------------------------------------------------------------------
# A tiny backup, a fake model
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_backup(engine, settings, tmp_path):
    """A studio with one closed serial day and one factual topic, frozen as a nightly backup."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True  # the copy lifts it, not the backup
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    log, event_ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    topic_id = a_topic(engine)
    with Session(engine) as session:
        # The seed's writer model is one the Owner forbade writers (2026-10-15): the harness
        # pins another, as the integrator does with --writer-model.
        available = [
            name
            for name in session.scalars(
                select(ModelRecord.model_name)
                .where(ModelRecord.is_available.is_(True))
                .order_by(ModelRecord.model_name)
            )
            if not we.forbidden_writer(name)
        ]
        writer_model, judge_model = available[0], available[1]
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    engine.dispose()
    backups = tmp_path / "data" / "backups"
    backups.mkdir(parents=True)
    source = Path(settings.database_url.removeprefix("sqlite:///"))
    name = f"studio-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.db"  # taken after the day it holds
    shutil.copyfile(source, backups / name)
    return {
        "backup": name,
        "backups": backups,
        "log_id": log["id"],
        "business_date": log["business_date"],
        "event_ids": event_ids,
        "names": names,
        "topic_id": topic_id,
        "writer_model": writer_model,
        "judge_model": judge_model,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _forbid_the_vault(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the dry run read the vault")

    monkeypatch.setattr(we, "llm_registry", refuse)


def test_discovery_on_a_copy_then_a_dry_run_asks_no_model(tiny_backup, tmp_path, monkeypatch):
    _forbid_the_vault(monkeypatch)
    backups = tiny_backup["backups"]
    before = _sha(backups / tiny_backup["backup"])
    case_file = tmp_path / "config" / "writer_cases.json"
    common = [
        "--backups",
        str(backups),
        "--work",
        str(tmp_path / "work"),
        "--case-file",
        str(case_file),
    ]

    assert we.main(["--discover", "--since", tiny_backup["business_date"], *common]) == 0
    proposal = json.loads(case_file.read_text(encoding="utf-8"))
    kinds = {case["id"]: case for case in proposal["cases"]}
    serial = kinds[f"serial-{tiny_backup['business_date']}"]
    assert serial["log_id"] == tiny_backup["log_id"] and serial["state"] == "no_draft_yet"
    assert kinds[f"factual-{tiny_backup['topic_id'][:8]}"]["topic_id"] == tiny_backup["topic_id"]
    assert proposal["backups_scanned"] == [tiny_backup["backup"]]

    out = tmp_path / "out"
    code = we.main(
        [
            "--dry-run",
            "--writer-model",
            tiny_backup["writer_model"],
            "--judge-model",
            tiny_backup["judge_model"],
            "--out",
            str(out),
            *common,
        ]
    )
    assert code == 0
    (run,) = list(out.iterdir())
    assert run.name.endswith("-baseline-proba")
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    assert results["meta"]["dry_run"] is True
    for result in results["results"]:
        assert "error" not in result, result.get("error")
        assert result["writer"] == {"status": "DRY_RUN"}
        assert result["brief"]["chars"] > 1000  # the brief was built and kept, never sent
        assert result["kernel"] == {"judge": None, "writer": None}
        assert result["copy_prepared"]["autonomy_stopped_lifted"] is True
        assert "runs" not in result
    assert "Ce s-ar întreba" in (run / "report.md").read_text(encoding="utf-8")
    assert _sha(backups / tiny_backup["backup"]) == before
    assert not any(path.is_file() for path in (tmp_path / "work").rglob("*"))


def test_a_run_refuses_while_the_live_studio_holds_its_lock(tiny_backup, tmp_path):
    from app.workflows.worker import acquire_worker_lock

    case_file = a_case_file(tmp_path / "cases.json", [serial_case(log_id=tiny_backup["log_id"])])
    held = acquire_worker_lock(tiny_backup["backups"].parent / "studio.lock")
    assert held is not None
    try:
        code = we.main(
            [
                "--backups",
                str(tiny_backup["backups"]),
                "--case-file",
                str(case_file),
                "--work",
                str(tmp_path / "work"),
                "--out",
                str(tmp_path / "out"),
            ]
        )
    finally:
        held.release()
    assert code == 3
    assert not (tmp_path / "out").exists()


def test_kimi_never_writes(tmp_path):
    case_file = a_case_file(tmp_path / "cases.json", [serial_case()])
    code = we.main(
        [
            "--writer-model",
            "kimi-k3",
            "--case-file",
            str(case_file),
            "--dry-run",
            "--backups",
            str(tmp_path),
        ]
    )
    assert code == 2
    assert we.forbidden_writer("kimi-k3:cloud") and not we.forbidden_writer("gpt-oss:120b")


def test_a_whole_run_on_a_tiny_backup_with_a_fake_model(tiny_backup, tmp_path, monkeypatch):
    from app.media import prompt_agent

    backups = tiny_backup["backups"]
    backup = tiny_backup["backup"]
    before = _sha(backups / backup)
    script = json.dumps(
        {
            "title": "The address nobody may buy",
            "core_message": "One web address is reserved so nobody can own it.",
            "hook": "There is one address nobody may buy.",
            "ending": "Reserved by the registry itself.",
            "cta": "Which reserved address surprised you?",
            "cta_kind": "COMMENT",
            "scenes": [
                {
                    "narration": "There is one web address on earth nobody may buy.",
                    "visual": "A browser bar, a cursor blinking.",
                    "purpose": "HOOK",
                    "kind": "LIVE",
                    "claim_ids": ["c1"],
                },
                {
                    "narration": "Because the registry reserved it, so no company can hold it.",
                    "visual": "A registry page, a padlock closing.",
                    "purpose": "PAYOFF",
                    "kind": "LIVE",
                    "claim_ids": ["c2"],
                },
                {
                    "narration": "Which reserved address surprised you most?",
                    "visual": "The browser bar again.",
                    "purpose": "CTA",
                    "kind": "LIVE",
                    "claim_ids": ["c1"],
                },
            ],
        }
    )
    model = FakeLLM(
        episode=episode_answer(beats_for(tiny_backup["event_ids"], tiny_backup["names"])),
        script=script,
    )
    seen_providers: list[set[str]] = []

    def fake_registry(engine, vault_key, provider_ids):
        wanted = set(provider_ids)
        seen_providers.append(wanted)
        registry = a_registry()
        for provider_id in wanted:
            registry.register(provider_id, model)
        we.assert_no_media_adapter(registry)
        return registry, {"connections_not_read": 0, "registered": sorted(wanted), "missing": []}

    monkeypatch.setattr(we, "llm_registry", fake_registry)

    def no_lessons(*_args, **_kwargs):
        raise AssertionError("the Director read prompt lessons during the evaluation")

    monkeypatch.setattr(prompt_agent, "reconcile_prompt_lessons", no_lessons)

    serial_ref = frozen_serial("The Quiet Desk")
    cases = [
        {
            "id": "serial-day",
            "kind": "serial",
            "backup": backup,
            "log_id": tiny_backup["log_id"],
            "writer_model": "kimi-k3",  # overridden by --writer-model, never asked
            "reference": {
                "kind": "serial",
                "id": "ref1",
                "text_key": "episode:ref1",
                "view": serial_ref,
            },
        },
        {
            "id": "factual-topic",
            "kind": "factual",
            "backup": backup,
            "topic_id": tiny_backup["topic_id"],
            "target_seconds": 20,
            "reference": {
                "kind": "factual",
                "id": "s0",
                "text_key": "script:s0",
                "view": frozen_factual(),
            },
        },
        {
            "id": "golden-pair",
            "kind": "golden_pair",
            "backup": backup,
            "a": {"kind": "serial", "text_key": "episode:ga", "view": frozen_serial("Worse cut")},
            "b": {"kind": "serial", "text_key": "episode:gb", "view": frozen_serial("BETTER cut")},
            "expected": "b",
        },
    ]
    case_file = a_case_file(tmp_path / "cases.json", cases)
    labels = tmp_path / "owner_labels.json"
    labels.write_text(
        json.dumps(
            {
                "version": 1,
                "labels": {
                    "episode:ref1": {
                        "orient": "da",
                        "story": "da",
                        "finish": "nu",
                        "ending": "nu",
                        "surprise": "nu",
                    },
                    "episode:gb": {"orient": True, "story": False, "finish": None},
                },
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    code = we.main(
        [
            "--backups",
            str(backups),
            "--case-file",
            str(case_file),
            "--labels",
            str(labels),
            "--work",
            str(tmp_path / "work"),
            "--out",
            str(out),
            "--writer-model",
            tiny_backup["writer_model"],
            "--judge-model",
            tiny_backup["judge_model"],
        ]
    )
    assert code == 0
    (run,) = list(out.iterdir())
    data = json.loads((run / "results.json").read_text(encoding="utf-8"))
    results = {result["id"]: result for result in data["results"]}
    for result in results.values():
        assert "error" not in result, result.get("error")

    serial = results["serial-day"]
    assert serial["writer"]["status"] == "DRAFTED"
    assert serial["writer_model"] == tiny_backup["writer_model"]
    assert serial["checks"] and serial["checks_summary"]["total"] >= 5
    assert {check["name"] for check in serial["checks"]} >= {"grounding", "length", "cast"}
    assert serial["stranger_new"]["orders_answered"] == 3
    # «finish» was yes only when asked second: once in three orders, averaged, not voted away.
    assert serial["stranger_new"]["questions"]["finish"]["yes_rate"] == pytest.approx(
        1 / 3, abs=1e-3
    )
    assert serial["stranger_new"]["score"] == pytest.approx(2 + 1 / 3, abs=1e-3)
    assert serial["stranger_reference"]["score"] is not None
    assert serial["pairwise"]["outcome"] == "tie"  # the fake always picks A: a flip
    tasks = [run_["task_type"] for run_ in serial["runs"]]
    assert tasks.count("stranger_judgement") == 6 and tasks.count("stranger_pairwise") == 2
    writer_runs = [r for r in serial["runs"] if r["task_type"] == "write_episode"]
    assert writer_runs and {r["model"] for r in writer_runs} == {tiny_backup["writer_model"]}
    assert all(r["prompt_tokens"] == 120 and r["latency_s"] is not None for r in serial["runs"])
    judge_runs = [r for r in serial["runs"] if r["task_type"].startswith("stranger")]
    assert {r["model"] for r in judge_runs} == {tiny_backup["judge_model"]}
    assert {r["identity_version"] for r in judge_runs} == {stranger.IDENTITY_VERSION}
    assert serial["fingerprint"]["brief_sha256"] == variants.fingerprint("serial")["brief_sha256"]

    # The judge's identity is bare; the writer's is the studio's own.
    assert set(model.systems("[orient]")) == {stranger.STRANGER_SYSTEM}
    assert set(model.systems('<video id="A">')) == {stranger.STRANGER_SYSTEM}
    writer_systems = model.systems("ALLOWED_NAMES:")
    assert writer_systems and all("STANDING RULES" in (s or "") for s in writer_systems)
    for call in model.calls:
        if "[orient]" in call["prompt"] or '<video id="A">' in call["prompt"]:
            assert "ALLOWED_NAMES" not in call["prompt"] and "event_ids" not in call["prompt"]
            assert '"part"' not in call["prompt"] and "claim_ids" not in call["prompt"]
    pinned = {call["model"] for call in model.calls if "ALLOWED_NAMES:" in call["prompt"]}
    assert pinned == {tiny_backup["writer_model"]}

    factual = results["factual-topic"]
    assert factual["writer"]["status"] == "DRAFTED" and factual["target_seconds"] == 20
    names = {check["name"]: check for check in factual["checks"]}
    assert names["answer_is_an_object"]["passed"] and names["cites_only_verified_claims"]["passed"]
    assert names["every_scene_cites_a_claim"]["passed"]
    assert "review.has_hook" in names and "under_the_180_s_wall" in names
    assert factual["stranger_new"]["orders_answered"] == 3

    golden = results["golden-pair"]
    assert golden["pairwise"]["outcome"] == "b" and golden["matches_expected"] is True
    assert golden["stranger_a"]["score"] is not None and "writer" not in golden

    totals = data["totals"]
    assert totals["drafted"] == 2 and totals["golden_matching"] == 1
    assert totals["pairwise"]["tie"] == 2 and totals["calls"] == len(
        [r for result in results.values() for r in result["runs"]]
    )
    agreement = data["meta"]["agreement"]
    assert agreement["texts"] == ["episode:gb", "episode:ref1"]
    assert agreement["questions"]["orient"]["n"] == 2
    assert agreement["questions"]["finish"]["n"] == 1  # an empty label is not counted
    report = (run / "report.md").read_text(encoding="utf-8")
    for heading in (
        "## Pe scurt",
        "## Pe cazuri",
        "## Perechile de aur",
        "## Acordul cu Proprietarul",
        "## Fiecare apel",
        "## Ce au primit scriitorii",
    ):
        assert heading in report, heading

    # Two providers asked for at most (writer, judge); the backup untouched; no copy left.
    assert all(len(wanted) <= 2 for wanted in seen_providers)
    assert _sha(backups / backup) == before
    assert not any(path.is_file() for path in (tmp_path / "work").rglob("*"))

    # And the Owner's form, from the same frozen texts.
    page, text_form = we.write_form(we.load_cases(case_file), tmp_path / "forms", 15)
    html = page.read_text(encoding="utf-8")
    for question in stranger.QUESTIONS:
        assert question.ro in html
    assert 'data-key="episode:gb"' in html and "Generează owner_labels.json" in html
    markdown = text_form.read_text(encoding="utf-8")
    assert "BETTER cut" in markdown and "event_ids" not in markdown


def test_the_copy_is_prepared_on_the_copy_only(engine):
    """The autonomy stop, an agent left thinking and a dead run are cleared, and a serial day's
    memory is put back, plan stub included, in the database the harness is handed."""
    seed_initial_workforce(engine)
    log, _ids = a_day(engine, YESTERDAY_NOON())
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
        agent = session.scalar(select(Agent))
        agent.runtime_state = "THINKING"
    case = {
        "kind": "serial",
        "continuity_before": {
            "from_backup": BACKUP,
            "replayed": ["e-old"],
            "row": {
                "version": 4,
                "canon_episode_number": 2,
                "threads_json": [],
                "recurring_json": ["the espresso"],
                "summaries_json": [
                    {"episode_number": 2, "episode_id": "e-old", "title": "Old", "summary": "s"}
                ],
            },
            "plan_episode": {
                "id": "e-old",
                "log_id": log["id"],
                "title": "Old",
                "created_at": "2026-10-15T05:02:00+00:00",
                "next_episode": {"premise": "p", "status": "PLANNED"},
            },
        },
    }
    changed = we.prepare_copy(engine, case)

    assert changed["autonomy_stopped_lifted"] is True and changed["agents_made_idle"] >= 1
    assert changed["plan_episode_stub"] == "e-old"
    from app.story.services import get_continuity

    memory = get_continuity(engine)
    assert memory["canon_episode_number"] == 2 and memory["recurring"] == ["the espresso"]
    with engine.connect() as connection:
        status = connection.execute(
            text(
                "SELECT json_extract(continuity_json, '$.next_episode.status') "
                "FROM story_episode WHERE id = 'e-old'"
            )
        ).scalar()
    assert status == "PLANNED"
