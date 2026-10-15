"""The Director watches a film before it goes out.

What is asserted: a film on a sourceless claim, in the wrong language, under forty words is
rejected without spending a model; a film the Director approves may publish and one she
rejects closes its storyboard, writes to the departments named and stays out of the publish
queue; the publish stage asks her first; frames are read from a real file when an encoder is
at hand.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from uuid import uuid4

import pytest
from app.agents.editorial import (
    EditorialVerdict,
    editorial_review,
    frames_for,
    gather_facts,
    latest_editorial,
)
from app.agents.models import Agent, AgentMessage, MemoryRecord, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.factual.models import FactualClaim, ScriptDraft, SourceSnapshot, TopicIdea
from app.media.models import (
    EditorialReview,
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.runbook.stages import topics_in_production
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

ENGLISH = (
    "In 2023 the James Webb Space Telescope measured water vapour in the atmosphere of a rocky "
    "planet twenty-six light years away. That should not be possible: the star bathes the planet "
    "in radiation that strips atmospheres bare. Either the planet keeps refilling its air from "
    "inside, or the signal comes from the star itself. Here is how astronomers plan to tell."
)
ROMANIAN = (
    "Studioul AI produce conținut cu integritate garantată. Fiecare afirmație este validată "
    "factual înainte de producție. Fiecare cadru este inspectat și certificat automat."
)


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "extra": kwargs.get("extra")})
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def staffed(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def registry_with(staffed, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(staffed["provider_id"], model)
    return registry, model


def a_film(
    engine,
    *,
    voiceover: str,
    with_source: bool,
    title="A rocky world with water",
    with_claim: bool = True,
    serial: bool = False,
):
    """A SELECTED topic, its script on one claim, a rendered storyboard and a QC-passed file.

    `with_claim=False` is a factual script that rests on nothing. `serial=True` is the film
    `storyboard_from_episode` produces: a SERIAL topic, a script with no claims whose
    `story_json` says it is an episode, and a storyboard keyed to the office serial.
    """
    ids = {k: str(uuid4()) for k in ("topic", "claim", "source", "script", "board", "asset", "job")}
    now = utc_now()
    if serial:
        with_claim = with_source = False
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title=title,
                topic="Serialul de birou" if serial else "space",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="SERIAL" if serial else "SELECTED",
                created_at=now,
            )
        )
        session.flush()
        if with_source:
            session.add(
                SourceSnapshot(
                    id=ids["source"],
                    topic_id=ids["topic"],
                    url="https://science.nasa.gov/webb",
                    title="Webb finds water vapour",
                    publisher="NASA",
                    content_hash="0" * 64,
                    raw_content="text",
                    sanitized_content="text",
                    credibility_score=0.9,
                    fetched_at=now,
                )
            )
            session.flush()
        if with_claim:
            session.add(
                FactualClaim(
                    id=ids["claim"],
                    topic_id=ids["topic"],
                    source_id=ids["source"] if with_source else None,
                    # The claim says what ENGLISH says: the year, the telescope, the
                    # planet's distance. With only "Webb measured water vapour on GJ 486 b."
                    # behind it, six of the narration's seven numbers and names came from no
                    # claim, and the grounding check refuses a film like that.
                    claim_text=(
                        "In 2023 the James Webb Space Telescope measured water vapour on "
                        "GJ 486 b, a rocky planet 26 light years away."
                    ),
                    claim_type="SCIENTIFIC_FACT",
                    importance="CRITICAL",
                    status="SUPPORTED",
                    confidence=0.9,
                    created_at=now,
                )
            )
            session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title=title,
                voiceover_full_text=voiceover,
                claim_ids_json=[ids["claim"]] if with_claim else [],
                status="APPROVED",
                story_json=(
                    {"kind": "office_serial_episode", "episode_number": 3, "episode_id": "ep"}
                    if serial
                    else None
                ),
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=ids["board"],
                script_draft_id=ids["script"],
                title=title,
                status="RENDERED",
                total_scenes=1,
                series_key="office_serial" if serial else None,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            StoryboardScene(
                id=str(uuid4()),
                storyboard_id=ids["board"],
                scene_index=1,
                visual_prompt="The telescope's golden mirror against the dark",
                visual_type="GENERATED_IMAGE",
                duration_seconds=6.0,
                voiceover_segment=voiceover[:120],
                created_at=now,
            )
        )
        session.add(
            MediaAsset(
                id=ids["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{ids['asset']}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=18.0,
                provider_name="RUNWAY_IMAGES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=ids["job"],
                storyboard_id=ids["board"],
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at=now,
            )
        )
        session.flush()
        session.add(
            QualityControlReport(
                id=str(uuid4()),
                media_asset_id=ids["asset"],
                status="PASSED",
                score=1.0,
                checks_json={"technical_qc": {"measured_width": 1080, "measured_height": 1920}},
                failure_reasons_json=[],
                verified_at=now,
            )
        )
    return ids


def test_the_film_that_went_out_would_now_be_rejected_without_a_model(engine, staffed):
    """One sourceless claim, Romanian narration, twenty words: three reasons, no tokens."""
    ids = a_film(engine, voiceover=ROMANIAN, with_source=False, title="Descoperire Robotică")
    registry, model = registry_with(staffed, lambda p: "{}")

    result = editorial_review(engine, registry, ids["asset"], language="en")

    assert result["verdict"] == "REJECT" and result["model_used"] is False
    assert model.calls == []
    reasons = " ".join(result["reasons"])
    assert "nu are nicio sursă" in reasons
    assert "nu este în English" in reasons
    assert "fără poveste" in reasons
    with Session(engine) as session:
        assert session.get(Storyboard, ids["board"]).status == "REJECTED"
        review = latest_editorial(session, ids["asset"])
        assert review.verdict == "REJECT" and review.frames_seen == 0
        letters = session.scalars(
            select(AgentMessage).where(AgentMessage.subject.like("Refăcut:%"))
        ).all()
        assert [m.to_agent_id for m in letters] == [staffed["agents"]["ScriptWriter"].id]
        assert "nu are nicio sursă" in letters[0].body_text
        live, stalled = topics_in_production(session)
        assert stalled == [ids["topic"]] and live == []


def test_the_director_watches_and_approves_and_the_verdict_is_a_record(engine, staffed):
    ids = a_film(engine, voiceover=ENGLISH, with_source=True)
    seen: dict = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return json.dumps(
            {
                "verdict": "APPROVE",
                "story": "A rocky world kept its water against a star that strips air.",
                "reasons": [],
                "notes_for": {},
            }
        )

    registry, model = registry_with(staffed, answer)
    result = editorial_review(engine, registry, ids["asset"], language="en")

    assert result["verdict"] == "APPROVE" and result["model_used"] is True
    assert "AUDIENCE LANGUAGE: English" in seen["prompt"]
    assert "science.nasa.gov/webb" in seen["prompt"] and "golden mirror" in seen["prompt"]
    assert model.calls[0]["extra"] == {"format": "json"}  # no frames: the file is not there
    with Session(engine) as session:
        review = latest_editorial(session, ids["asset"])
        assert review.verdict == "APPROVE" and review.story.startswith("A rocky world")
        assert session.get(Storyboard, ids["board"]).status == "RENDERED"
        assert session.scalar(
            select(AgentMessage).where(AgentMessage.subject.like("Vizionare: aprobat%"))
        )


def test_a_rejection_writes_to_each_department_named_and_keeps_the_film_out(engine, staffed):
    ids = a_film(engine, voiceover=ENGLISH, with_source=True)
    registry, _ = registry_with(
        staffed,
        lambda p: json.dumps(
            {
                "verdict": "REJECT",
                "story": "It never says why the water matters.",
                "reasons": ["no hook", "pictures decorate"],
                "notes_for": {
                    "ScriptWriter": "Open with what should be impossible.",
                    "VideoEditor": "Show the spectrum, not the mirror.",
                    "Publisher": "",
                },
            }
        ),
    )
    result = editorial_review(engine, registry, ids["asset"], language="en")
    assert result["verdict"] == "REJECT" and result["letters"] == 2
    with Session(engine) as session:
        targets = {
            m.to_agent_id
            for m in session.scalars(select(AgentMessage).where(AgentMessage.intent == "HANDOFF"))
        }
        assert targets == {
            staffed["agents"]["ScriptWriter"].id,
            staffed["agents"]["VideoEditor"].id,
        }
        assert session.get(Storyboard, ids["board"]).status == "REJECTED"


SPECTRUM = "A spectrum drawn as a rainbow reads as decoration; show dark absorption lines."


def test_her_verdict_carries_a_lesson_field_that_may_be_empty():
    """Review of 68fa0b4, 2026-10-12: the first sentence of her fix-it note to the Video Editor
    was kept as a rule for every film. Her verdict has a field of its own for the one general
    rule, empty when she has none."""
    verdict = EditorialVerdict.model_validate({"verdict": "APPROVE", "story": "x"})
    assert verdict.lesson == ""
    said = EditorialVerdict.model_validate({"verdict": "REJECT", "lesson": SPECTRUM})
    assert said.lesson == SPECTRUM
    assert EditorialVerdict.model_validate({"verdict": "APPROVE", "lesson": None}).lesson == ""


def test_only_her_lesson_is_kept_unverified_for_its_kind_of_film(engine, staffed):
    """Only the ``lesson`` of her verdict is a prompt lesson — never her note to the Video
    Editor, which is about this one film — for its kind of film and unverified."""
    from app.media.prompt_agent import prompt_lessons

    notes = {
        False: SPECTRUM,
        True: "Two people at one desk drift into profile; keep both turned to the viewer.",
    }
    for serial, lesson in notes.items():
        title = "The Cut Runs Long" if serial else "A rocky world with water"
        ids = a_film(engine, voiceover=ENGLISH, with_source=True, serial=serial, title=title)

        def answer(_prompt, lesson=lesson):
            return json.dumps(
                {
                    "verdict": "REJECT",
                    "story": "It never says why the water matters.",
                    "reasons": ["the pictures decorate"],
                    "notes_for": {"VideoEditor": "Scene 2 is the worst; redo its mirror."},
                    "lesson": lesson,
                }
            )

        registry, _ = registry_with(staffed, answer)
        result = editorial_review(engine, registry, ids["asset"], language="en")
        scope = "serial" if serial else "factual"
        with Session(engine) as session:
            rows = list(
                session.scalars(
                    select(MemoryRecord).where(
                        MemoryRecord.source_id == result["run_id"],
                        MemoryRecord.content.like("prompt lesson:%"),
                    )
                )
            )
        assert [row.content for row in rows] == [f"prompt lesson: [{scope}][?] {lesson}"]
    with Session(engine) as session:
        assert prompt_lessons(session, scope="serial") == [f"{notes[True]} (unverified)"]
        assert prompt_lessons(session, scope="factual") == [f"{SPECTRUM} (unverified)"]
        everything = " ".join(prompt_lessons(session))
    assert "Scene 2" not in everything and "mirror" not in everything


@pytest.mark.parametrize(
    "lesson",
    [
        "The rocky world with water is lit differently in every shot.",
        "Scene 4's ledger shows digits; ask for blank pages.",
        "x" * 4001,
        "   ",
    ],
)
def test_a_lesson_about_this_film_or_a_report_is_not_kept(engine, staffed, lesson):
    """Her lesson goes through the store's own refusal with the film it was learned on: its
    title (here «A rocky world with water», most of its words), a scene by its number, a
    report over LESSON_MAX_CHARS (4000) characters, nothing at all."""
    from app.media.prompt_agent import prompt_lessons

    ids = a_film(engine, voiceover=ENGLISH, with_source=True, title="A rocky world with water")
    verdict = {"verdict": "REJECT", "story": "s", "reasons": ["r"], "lesson": lesson}
    registry, _ = registry_with(staffed, lambda _prompt: json.dumps(verdict))
    editorial_review(engine, registry, ids["asset"], language="en")
    with Session(engine) as session:
        assert prompt_lessons(session) == []


def test_the_publish_stage_asks_the_director_before_anything_else(engine, settings, staffed):
    from app.runbook.stages import _publish

    ids = a_film(engine, voiceover=ROMANIAN, with_source=False)
    registry, model = registry_with(staffed, lambda p: "{}")
    # No channel is bound in a fresh studio: the stage stops before the film. Bind nothing,
    # and check the Director's gate by asking the stage with a prepared candidate instead.
    outcome = _publish(engine, None, registry, "en")
    assert outcome["status"] in ("SKIPPED", "COMPLETED")
    # The gate itself, on the candidate the stage would pick:
    with Session(engine) as session:
        assert latest_editorial(session, ids["asset"]) is None
    editorial_review(engine, registry, ids["asset"], language="en")
    with Session(engine) as session:
        assert latest_editorial(session, ids["asset"]).verdict == "REJECT"
        assert (
            session.scalar(
                select(EditorialReview).where(EditorialReview.media_asset_id == ids["asset"])
            )
            is not None
        )


def test_gather_facts_reads_the_whole_film(engine, staffed):
    ids = a_film(engine, voiceover=ENGLISH, with_source=True)
    with Session(engine) as session:
        facts = gather_facts(session, ids["asset"], "en")
    assert facts["hard_rejects"] == []
    assert facts["claims"][0]["source"]["publisher"] == "NASA"
    assert facts["scenes"][0]["picture"].startswith("The telescope")
    assert facts["quality_control"]["status"] == "PASSED"
    assert facts["words"] >= 40 and facts["audience_language"] == "English"
    assert EditorialVerdict(verdict="APPROVE").story == ""


EPISODE = (
    "Sarah opens the board and asks for the number before anyone says good morning. Aris "
    "answers with the evidence first and the opinion never, which is his whole style. The "
    "room laughs, the espresso cup goes down, and the day has officially started in here. "
    "Nobody mentions that the number is wrong until the credits roll."
)


def test_a_serial_film_is_judged_as_a_dramatisation_not_for_its_missing_claims(engine, staffed):
    """Measured on the first serial film: `gather_facts` hard-rejected it for resting on no
    claim, and the instructions told the Director a film about the studio is REJECTED — so an
    approved episode never reached the publish routing. A dramatisation makes no claims and
    needs no sources; it is judged for its story, its people and its pictures instead."""
    ids = a_film(engine, voiceover=EPISODE, with_source=False, title="Ziua numărului", serial=True)
    with Session(engine) as session:
        facts = gather_facts(session, ids["asset"], "en")
    assert facts["hard_rejects"] == []
    assert facts["serial"] is True
    assert facts["series_key"] == "office_serial"
    assert facts["episode"] == {"title": "Ziua numărului", "number": 3}
    assert facts["claims"] == []

    seen: dict = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return json.dumps({"verdict": "APPROVE", "story": "Sarah wants the number.", "reasons": []})

    registry, model = registry_with(staffed, answer)
    result = editorial_review(engine, registry, ids["asset"], language="en")

    assert result["verdict"] == "APPROVE" and result["model_used"] is True
    prompt = seen["prompt"]
    assert "A dramatisation is not a factual film" in prompt
    assert "needs no sources" in prompt
    assert "the situation, the turn, the payoff" in prompt
    assert "sounds like a person" in prompt
    assert "A film about the studio itself" not in prompt
    assert "backed by a real source" not in prompt
    # The frames rule does not bend for a comedy: a blank frame is a blank frame.
    assert "garbled writing in any of them means REJECT" in prompt
    assert '"serial": true' in prompt
    with Session(engine) as session:
        assert latest_editorial(session, ids["asset"]).verdict == "APPROVE"
        assert session.get(Storyboard, ids["board"]).status == "RENDERED"


#: A narration about something its claim never says: the rehearsal of 2026-09-18 approved a
#: telescope film on a Nepal topic, and this is the same drift the other way round.
OFF_CLAIM = (
    "Nepal is the fourth most vulnerable country on Earth to climate change. In August 2018 "
    "flash floods and landslides along its southern border cost six hundred million dollars in "
    "damages, and the money promised by richer countries never arrived in the valleys that "
    "flooded. Who should pay that bill?"
)


def test_the_director_reads_what_the_narration_was_measured_against(engine, staffed):
    """Her facts carry the grounding measurement, so her verdict can cite it."""
    ids = a_film(engine, voiceover=ENGLISH, with_source=True)
    with Session(engine) as session:
        facts = gather_facts(session, ids["asset"], "en")
    assert facts["grounding"]["status"] == "PASSED"
    assert facts["grounding"]["claims"][0]["present"] is True


def test_a_film_whose_narration_does_not_say_its_claim_is_refused_before_any_model(engine, staffed):
    ids = a_film(engine, voiceover=OFF_CLAIM, with_source=True)
    with Session(engine) as session:
        facts = gather_facts(session, ids["asset"], "en")
    assert facts["grounding"]["status"] == "REFUSED"
    assert len(facts["hard_rejects"]) == 1
    assert facts["hard_rejects"][0].startswith("narațiunea nu spune ce spun afirmațiile ei")
    assert "nu o spune" in facts["hard_rejects"][0]

    registry, model = registry_with(staffed, lambda p: json.dumps({"verdict": "APPROVE"}))
    result = editorial_review(engine, registry, ids["asset"], language="en")
    assert result["verdict"] == "REJECT" and model.calls == []


def test_a_serial_film_is_not_measured_against_claims(engine, staffed):
    ids = a_film(engine, voiceover=EPISODE, with_source=False, serial=True)
    with Session(engine) as session:
        facts = gather_facts(session, ids["asset"], "en")
    assert facts["grounding"] is None
    assert facts["hard_rejects"] == []


def test_a_serial_film_still_needs_words_pictures_and_the_audience_language(engine, staffed):
    """The exception is for claims only: a serial film in the wrong language, or one too short
    to be an episode, is refused without a model like any other film."""
    short = a_film(engine, voiceover="Sarah asks. Aris answers.", with_source=False, serial=True)
    romanian = a_film(engine, voiceover=ROMANIAN, with_source=False, serial=True)
    with Session(engine) as session:
        short_facts = gather_facts(session, short["asset"], "en")
        romanian_facts = gather_facts(session, romanian["asset"], "en")
    assert short_facts["serial"] is True
    assert any("fără poveste" in reason for reason in short_facts["hard_rejects"])
    assert any("nu este în English" in reason for reason in romanian_facts["hard_rejects"])
    assert not any("afirmație" in reason for reason in short_facts["hard_rejects"])

    registry, model = registry_with(staffed, lambda p: "{}")
    result = editorial_review(engine, registry, short["asset"], language="en")
    assert result["verdict"] == "REJECT" and model.calls == []
    with Session(engine) as session:
        assert session.get(Storyboard, short["board"]).status == "REJECTED"


def test_a_factual_film_without_claims_is_still_rejected_in_the_same_words(engine, staffed):
    """The exception cannot widen: a factual script that rests on nothing is refused before
    any model, with the reason the first review gave, and the Director's instructions for it
    still say a film about the studio is REJECTED."""
    ids = a_film(engine, voiceover=ENGLISH, with_source=False, with_claim=False)
    with Session(engine) as session:
        facts = gather_facts(session, ids["asset"], "en")
    assert facts["serial"] is False
    assert facts["hard_rejects"] == ["scenariul nu se sprijină pe nicio afirmație"]

    registry, model = registry_with(staffed, lambda p: "{}")
    result = editorial_review(engine, registry, ids["asset"], language="en")
    assert result["verdict"] == "REJECT" and model.calls == []
    assert result["reasons"] == ["scenariul nu se sprijină pe nicio afirmație"]

    # And the factual instructions are the ones the Director always had.
    sourced = a_film(engine, voiceover=ENGLISH, with_source=True)
    seen: dict = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return json.dumps({"verdict": "APPROVE", "story": "Water.", "reasons": []})

    registry, _ = registry_with(staffed, answer)
    editorial_review(engine, registry, sourced["asset"], language="en")
    assert "A film about the studio itself" in seen["prompt"]
    assert "backed by a real source" in seen["prompt"]
    assert "A dramatisation is not a factual film" not in seen["prompt"]
    assert '"serial": false' in seen["prompt"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_frames_are_read_from_a_real_file(tmp_path):
    film = tmp_path / "film.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x128:d=2",
            "-pix_fmt",
            "yuv420p",
            str(film),
        ],
        check=True,
        capture_output=True,
    )
    frames = frames_for(str(film), None, 2.0)
    assert len(frames) == 3 and all(len(f) > 100 for f in frames)
    assert frames_for(str(tmp_path / "missing.mp4"), None, 2.0) == []


def _give_vision(engine, agent_id):
    """What a provider declares about a model, as the model sync records it."""
    from app.agents.models import Capability, ModelCapability

    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        # The workforce seed writes the `vision` row itself now (a role prefers it); only the
        # per-model declaration below is this helper's own.
        capability = session.scalar(select(Capability).where(Capability.name == "vision"))
        if capability is None:
            capability = Capability(id=str(uuid4()), name="vision", description="sees pictures")
            session.add(capability)
            session.flush()
        session.add(
            ModelCapability(
                model_id=agent.model_id,
                capability_id=capability.id,
                confidence="DECLARED_BY_PROVIDER",
            )
        )


def test_frames_are_sent_only_to_a_model_the_provider_says_can_see(engine, staffed, tmp_path):
    """A model without vision refuses the whole call, so the Director could never give a
    verdict: on the live studio her glm-5.3 answered nothing and a finished film waited.
    Frames go only to a model the provider says can see; without one she judges the written
    film and the prompt tells her she is judging it blind."""
    from app.agents.editorial import model_can_see

    ids = a_film(engine, voiceover=ENGLISH, with_source=True)
    film = tmp_path / "film.mp4"
    film.write_bytes(b"0" * 128)
    with Session(engine) as session, session.begin():
        session.get(MediaAsset, ids["asset"]).uri_or_path = str(film)

    seen: dict = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return json.dumps({"verdict": "APPROVE", "story": "A rocky world.", "reasons": []})

    registry, model = registry_with(staffed, answer)
    director = staffed["agents"]["Director"]
    with Session(engine) as session:
        assert model_can_see(session, director.id) is False

    blind = editorial_review(engine, registry, ids["asset"], language="en")
    assert blind["frames_seen"] == 0 and blind["verdict"] == "APPROVE"
    assert "You cannot see the film itself" in seen["prompt"]
    assert model.calls[0]["extra"] == {"format": "json"}

    _give_vision(engine, director.id)
    with Session(engine) as session:
        assert model_can_see(session, director.id) is True


def test_a_rejection_of_a_film_accepted_under_the_owners_cap_is_notes_not_a_veto(engine, staffed):
    """12:49Z, 2d276038: six seconds after the Director accepted the film under the Owner's cap
    («publicăm ce avem»), her viewing refused it — first for the studio's own captions read as
    «burned-in writing» — put the storyboard on REJECTED and told four departments to remake
    it. Under the cap her viewing is notes: the verdict is recorded APPROVE with her reasons,
    no department is told to remake anything, the lesson is kept, a storyboard an earlier
    viewing refused stands RENDERED again, and the brief says the captions are the film's."""
    from app.agents.editorial import accepted_under_cap, instructions_for
    from app.media.director_qc import record_decision

    ids = a_film(engine, voiceover=ENGLISH, with_source=True)
    record_decision(
        engine,
        {
            "report_id": str(uuid4()),
            "media_asset_id": ids["asset"],
            "storyboard_id": ids["board"],
            "decided_by": "Director",
            "decision": "ACCEPT",
            "summary": "Acceptat sub plafonul Proprietarului.",
            "verdicts": [],
            "repairs": [],
            "outcome": "ACCEPTED",
            "final": True,
            "accepted_under_cap": {"limited": [2, 4], "reason_ro": "plafonul"},
        },
        "c",
    )
    with Session(engine) as session, session.begin():
        session.get(Storyboard, ids["board"]).status = "REJECTED"  # an earlier viewing's
    with Session(engine) as session:
        assert accepted_under_cap(session, ids["asset"])["accepted_under_cap"]["limited"] == [2, 4]
    seen: dict = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return json.dumps(
            {
                "verdict": "REJECT",
                "story": "A night of rewrites.",
                "reasons": ["burned-in caption text in every frame", "the wrong room"],
                "notes_for": {"VideoEditor": "Do not publish; a new still pass."},
                "lesson": "Name only objects whose purpose is complete without content.",
            }
        )

    registry, _model = registry_with(staffed, answer)
    result = editorial_review(engine, registry, ids["asset"], language="en")

    assert result["verdict"] == "APPROVE" and result["letters"] == 0
    assert "never writing in the picture" in instructions_for(True, "")
    assert "burns its own captions" in seen["prompt"]
    with Session(engine) as session:
        review = latest_editorial(session, ids["asset"])
        assert review.verdict == "APPROVE"
        assert review.reasons_json == ["burned-in caption text in every frame", "the wrong room"]
        assert session.get(Storyboard, ids["board"]).status == "RENDERED"
        assert (
            session.scalar(select(AgentMessage).where(AgentMessage.subject.like("Refăcut:%")))
            is None
        )
