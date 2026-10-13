"""A factual script may only say what its topic and its claims say.

The rehearsal on a copy of the Owner's data (2026-09-18) selected "Why Nepal Is Being Handed a
Climate Bill It Cannot Pay" and the stand-in writer answered with the James Webb telescope. The
script cited the Nepal claim 0be61855, passed the factual gate (the claim exists and is
SUPPORTED), passed the story review and was approved. These tests hold the computed check that
now stands in that gap, before the storyboard and before anything is bought.

The fixtures are the rehearsal's own rows (topic 00000127 and its SUPPORTED claims, read-only
from the rehearsal's copy) and the two scripts the studio's real model wrote and the studio
approved on 2026-09-12 (f243bf48, the LHC film, and 0000007d, the ATLAS film), copied verbatim.
Everything is local: no model, no vendor, no network.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.factual.grounding import (
    NOT_MEASURED,
    PASSED,
    REFUSED,
    measure_grounding,
    script_grounding,
)
from app.factual.models import FactualClaim, ScriptDraft, SourceSnapshot, StoryReview, TopicIdea
from app.factual.story_review import _script_facts, review_story, story_gate
from app.services import utc_now
from sqlalchemy.orm import Session

# ------------------------------------------------------------------ the rehearsal's rows --

NEPAL_TITLE = "Why Nepal Is Being Handed a Climate Bill It Cannot Pay"
NEPAL_ANGLE = (
    "Open with the phrase viewers just scrolled past — 'climate crisis bill' — and close with "
    "the one number that makes the injustice concrete: how much richer countries owe versus "
    "what they have sent."
)
NEPAL_CLAIMS = {
    "0be61855-bb51-48a6-bdf5-fa923466f98d": (
        "Most of the estimated US$83.3 billion provided to developing countries in 2020 was "
        "targeted at mitigation (US$48.6 billion, or 58%)."
    ),
    "00000000-0000-4000-8000-0000000000b4": (
        "Nepal is globally ranked fourth in terms of vulnerability to climate change."
    ),
    "00000000-0000-4000-8000-000000000085": (
        "Nepal experienced flash floods and landslides in August 2018 across the southern "
        "border, amounting to US$600 million in damages."
    ),
    "00000000-0000-4000-8000-000000000196": (
        "At COP16 in Cancun (2010), developed countries committed to mobilizing jointly US$100 "
        "billion per year by 2020 to address the needs of developing countries, a goal "
        "extended through 2025 at COP21 in Paris (2015)."
    ),
    "00000000-0000-4000-8000-0000000001aa": (
        "According to OECD figures, climate finance provided and mobilized by developed "
        "countries reached US$83.3 billion in 2020 and US$89.6 billion in 2021, meaning the "
        "US$100 billion-per-year-by-2020 target was missed."
    ),
}
REHEARSAL_CLAIM = "0be61855-bb51-48a6-bdf5-fa923466f98d"

#: Script 5ee7e22e, verbatim: what the stand-in wrote on the Nepal topic.
JWST_VOICEOVER = (
    "Most of what the universe is doing happens in light your eyes will never catch, and that "
    "is where this story starts tonight.\n\n"
    "The James Webb telescope observes the universe in infrared light, which is the part of the "
    "spectrum that carries heat rather than colour.\n\n"
    "So the dust that hides a young star from us is no longer a wall, and the picture "
    "underneath it finally arrives.\n\n"
    "Look up tonight and remember that the dark you see is only the part of the sky your eyes "
    "were built for."
)

FAITHFUL = [
    "Nepal is the fourth most vulnerable country on Earth to climate change, and it is being "
    "handed the bill.",
    "In August 2018 flash floods and landslides along its southern border cost US$600 million "
    "in damages.",
    "Back in 2010, at COP16 in Cancun, developed countries promised US$100 billion a year by 2020.",
    "But OECD figures show they reached only US$83.3 billion in 2020, so the target was missed.",
    "And most of that money, US$48.6 billion or 58%, was targeted at mitigation, not at "
    "surviving floods. Who should pay the climate bill?",
]
FAITHFUL_CLAIMS = [
    ["00000000-0000-4000-8000-0000000000b4"],
    ["00000000-0000-4000-8000-000000000085"],
    ["00000000-0000-4000-8000-000000000196"],
    ["00000000-0000-4000-8000-0000000001aa"],
    [REHEARSAL_CLAIM],
]

#: The same film told in other words: numbers written out or rounded, the sentences rebuilt.
PARAPHRASED = [
    "Only three countries are more exposed to a changing climate than Nepal.",
    "Two summers ago? No: in 2018, one August of floods and landslides took six hundred "
    "million dollars from its southern border towns.",
    "The rich world had pledged a hundred billion dollars every year by 2020 — a promise made "
    "in Cancun.",
    "The OECD counted what arrived: about 83 billion in 2020. The goal was missed.",
    "Of that, roughly 49 billion went to mitigation — cutting emissions — which leaves Nepal's "
    "flood bill unpaid.",
]

#: And translated: the studio's audience language is a setting, and a Romanian narration of
#: English claims keeps the numbers, the names and the shared stems.
TRANSLATED = [
    "Nepalul este a patra țară cea mai vulnerabilă la schimbările climatice.",
    "În august 2018, inundațiile și alunecările de teren de la granița de sud au produs "
    "pagube de 600 de milioane de dolari.",
    "În 2010, la COP16 din Cancun, țările dezvoltate au promis 100 de miliarde de dolari pe an "
    "până în 2020.",
    "Cifrele OECD arată doar 83,3 miliarde în 2020: ținta a fost ratată.",
    "Iar 48,6 miliarde, adică 58%, au mers la atenuare (mitigation), nu la adaptare. Cine "
    "plătește factura climatică a Nepalului?",
]

# ------------------------------------------------ the real scripts the studio approved --

LHC = {
    "title": "Why the LHC Upgrade Matters for Dark Matter Searches",
    "angle": "Details how increased collision rates improve chances of detecting dark matter "
    "candidates",
    "claims": {
        "1c436498": "Normal matter accounts for only 5% of the content of the universe.",
        "7d257349": "Dark matter makes up about 27% of the universe.",
        "87a4e1bb": "Dark matter does not interact with the electromagnetic force.",
        "2a7e90ab": "Dark matter is inferred only from its gravitational effects on visible "
        "matter.",
        "c7bc24b1": "Dark energy makes up approximately 68% of the universe.",
        "01e26832": "Dark energy causes a repulsive force that accelerates the expansion of "
        "the universe.",
        "07460856": "Dark matter candidates arise in theories beyond the Standard Model, such "
        "as supersymmetry.",
        "6de16d3b": "Experiments at the Large Hadron Collider may provide direct clues about "
        "dark matter.",
    },
    "voiceover": (
        "Look around. Everything you see—stars, planets, you—is just 5% of the universe.\n\n"
        "The rest? Invisible. 27% is dark matter—holding galaxies together, unseen.\n\n"
        "It doesn’t glow, doesn’t absorb light. It only tugs at stars with gravity.\n\n"
        "And 68%? Dark energy—pushing the universe apart, faster and faster.\n\n"
        "But here’s the problem: dark matter might be made of particles we’ve never seen.\n\n"
        "Theories like supersymmetry predict them—but we need proof.\n\n"
        "That’s where the Large Hadron Collider comes in. Smashing particles at near "
        "light-speed could reveal dark matter’s fingerprints.\n\n"
        "The upgrade? More collisions, more data. A chance to finally catch what’s been hiding "
        "in plain sight."
    ),
}

ATLAS = {
    "title": "How CERN's ATLAS Measured a Higgs Boson in Real Time",
    "angle": "Most viewers picture the Higgs as an abstract idea; the film opens by asking what "
    "a Higgs event actually looks like inside the detector, follows the four-lepton signature, "
    "and ends on the single number that proves the particle appeared and lived for an instant "
    "before decay.",
    "claims": {
        "74ed8f34": "The Higgs field was proposed in 1964 as a new kind of field that fills the "
        "entire Universe and gives mass to all elementary particles.",
        "403ea87f": "The existence of the Higgs mass-giving field was confirmed in 2012 when "
        "the Higgs boson particle was discovered at CERN.",
        "50d42bc1": "Photons do not interact with the Higgs field and therefore have no mass, "
        "while other elementary particles such as electrons, quarks and bosons do interact "
        "with it and acquire mass.",
        "f4774dce": "The ATLAS detector measures 46 m long, 25 m high and 25 m wide, weighs "
        "7,000 tonnes, and is the largest volume particle detector ever constructed.",
        "a87a851d": "ATLAS employs a large magnet system that bends the paths of charged "
        "particles so their momenta can be measured.",
        "161b8df7": "ATLAS uses six different detecting subsystems arranged in layers around "
        "the collision point to record the paths, momentum and energy of particles.",
        "2511434c": "On July 4, 2012, ATLAS and CMS reported evidence for a Higgs-like particle "
        "at a 5-sigma confidence level, with a mass around 125 GeV, about 133 times the proton "
        "mass.",
        "86407bd5": "On 4 July 2012, the ATLAS and CMS collaborations announced the discovery "
        "of a new particle at CERN.",
    },
    "voiceover": (
        "For 48 years, the Higgs field was only an idea on paper.\n\n"
        "The only way to prove it: catch one decaying, live, in a detector.\n\n"
        "So CERN built ATLAS: 46 metres long, 7,000 tonnes.\n\n"
        "Its magnets bend every charged particle's path, and six layered subsystems record "
        "momentum.\n\n"
        "Then four leptons snapped into a single peak at 125 GeV. Theory became fact. Which "
        "should we reconstruct next: top quark or W boson?"
    ),
}

#: The whole-day test's stand-in writes the telescope film for its own infrared topic, where
#: it is exactly right: the same narration is grounded or not by what it rests on.
INFRARED = {
    "title": "Infrared light and what it shows",
    "angle": "What a telescope sees that eyes cannot",
    "claims": {"fact": "The James Webb telescope observes the universe in infrared light."},
    "voiceover": JWST_VOICEOVER,
}


def _measure(title, angle, claims, lines):
    return measure_grounding(
        topic_title=title, topic_angle=angle, claims=claims, voiceover="\n\n".join(lines)
    )


def _cited(ids):
    return {cid: NEPAL_CLAIMS[cid] for cid in ids}


# ------------------------------------------------------------------ the measurement --


def test_the_rehearsals_telescope_film_on_the_nepal_topic_is_refused_with_its_reasons():
    measured = measure_grounding(
        topic_title=NEPAL_TITLE,
        topic_angle=NEPAL_ANGLE,
        claims=_cited([REHEARSAL_CLAIM]),
        voiceover=JWST_VOICEOVER,
    )

    assert measured["status"] == REFUSED
    assert measured["passed"] is False
    reasons = " ".join(measured["reasons"])
    # All three counts, each in Romanian and each naming what is missing.
    assert "Afirmația 0be61855" in reasons and "nu o spune" in reasons
    assert "83.3" in reasons  # the claim's own number is what the narration never says
    assert "nu vorbește despre subiectul" in reasons and "nepal" in reasons
    assert "altă poveste" in reasons and "webb" in reasons
    assert measured["claims"][0]["matched"] == []
    assert measured["topic"]["matched"] == []
    assert measured["foreign"]["share"] == 1.0


def test_a_faithful_script_passes():
    ids = sorted({cid for scene in FAITHFUL_CLAIMS for cid in scene})
    measured = _measure(NEPAL_TITLE, NEPAL_ANGLE, _cited(ids), FAITHFUL)

    assert measured["status"] == PASSED, measured["reasons"]
    assert measured["claims_present"] == measured["claims_cited"] == 5


def test_a_paraphrased_script_passes():
    ids = sorted({cid for scene in FAITHFUL_CLAIMS for cid in scene})
    measured = _measure(NEPAL_TITLE, NEPAL_ANGLE, _cited(ids), PARAPHRASED)

    assert measured["status"] == PASSED, measured["reasons"]


def test_a_translated_script_passes():
    ids = sorted({cid for scene in FAITHFUL_CLAIMS for cid in scene})
    measured = _measure(NEPAL_TITLE, NEPAL_ANGLE, _cited(ids), TRANSLATED)

    assert measured["status"] == PASSED, measured["reasons"]


def test_a_script_that_cites_a_claim_it_never_says_is_refused_naming_that_claim():
    # The faithful film's first two scenes, then a closing line that cites the rehearsal's
    # claim without a word of it: no US$83.3 billion, no 2020, no mitigation.
    lines = FAITHFUL[:2] + ["Who should pay the climate bill Nepal is being handed?"]
    ids = [
        "00000000-0000-4000-8000-0000000000b4",
        "00000000-0000-4000-8000-000000000085",
        REHEARSAL_CLAIM,
    ]
    measured = _measure(NEPAL_TITLE, NEPAL_ANGLE, _cited(ids), lines)

    assert measured["status"] == REFUSED
    assert len(measured["reasons"]) == 1
    reason = measured["reasons"][0]
    assert "Afirmația 0be61855" in reason and "nu o spune" in reason
    assert "83.3" in reason and "mitigation" in reason
    absent = [row["claim_id"] for row in measured["claims"] if not row["present"]]
    assert absent == [REHEARSAL_CLAIM]


@pytest.mark.parametrize("film", [LHC, ATLAS, INFRARED], ids=["lhc", "atlas", "infrared"])
def test_every_script_the_studio_approved_still_passes(film):
    measured = measure_grounding(
        topic_title=film["title"],
        topic_angle=film["angle"],
        claims=film["claims"],
        voiceover=film["voiceover"],
    )
    assert measured["status"] == PASSED, measured["reasons"]


def test_a_script_it_cannot_measure_says_so_and_does_not_pass():
    for claims, voiceover in (
        ({}, JWST_VOICEOVER),
        ({REHEARSAL_CLAIM: None}, "\n".join(FAITHFUL)),
        (_cited([REHEARSAL_CLAIM]), "   "),
    ):
        measured = measure_grounding(
            topic_title=NEPAL_TITLE, topic_angle=NEPAL_ANGLE, claims=claims, voiceover=voiceover
        )
        assert measured["status"] == NOT_MEASURED
        assert measured["passed"] is False
        assert "nu a putut fi măsurată" in measured["reasons"][0]


# ------------------------------------------------ the adversary's cases, 2026-09-19 --

FOURTH = "00000000-0000-4000-8000-0000000000b4"
FLOODS = "00000000-0000-4000-8000-000000000085"
PLEDGE = "00000000-0000-4000-8000-000000000196"


@pytest.mark.parametrize(
    "voiceover",
    [
        # A voiceover is written to be read aloud, and a writer spells numbers out. Measured
        # before the fix: "six hundred million" was read as a 6 and a 100, neither in any claim,
        # and the film was refused as "someone else's story" (share 0.75 and 1.0).
        "Nepal ranks fourth in the world for climate vulnerability. In August of twenty "
        "eighteen, flash floods and landslides on the southern border did six hundred million "
        "dollars of damage.",
        "Nepal is the fourth most vulnerable nation to climate change. In two thousand "
        "eighteen, floods and landslides in the south cost it six hundred million US dollars "
        "in damages.",
        # The same in Romanian: "șase sute" was a 6 and an unread "sute", "patru" a 4 that the
        # claim's "fourth" never met (share 0.667).
        "Nepalul este pe locul patru în lume la vulnerabilitatea față de schimbările "
        "climatice. Inundațiile și alunecările de teren din august 2018 au produs pagube de "
        "șase sute de milioane de dolari.",
    ],
    ids=["english-words", "english-thousand", "romanian-words"],
)
def test_numbers_written_as_words_are_the_claims_numbers(voiceover):
    measured = measure_grounding(
        topic_title=NEPAL_TITLE,
        topic_angle=NEPAL_ANGLE,
        claims=_cited([FOURTH, FLOODS]),
        voiceover=voiceover,
    )
    assert measured["status"] == PASSED, measured["reasons"]
    assert measured["foreign"]["from_nowhere"] == []


def test_a_claim_quoted_with_other_punctuation_is_still_the_claim():
    voiceover = (
        "“Nepal is globally ranked fourth in terms of vulnerability to climate change”"
        " — and in Aug. 2018, flash floods & landslides across the southern border meant "
        "US $600M in damages."
    )
    measured = measure_grounding(
        topic_title=NEPAL_TITLE,
        topic_angle=NEPAL_ANGLE,
        claims=_cited([FOURTH, FLOODS]),
        voiceover=voiceover,
    )
    assert measured["status"] == PASSED, measured["reasons"]


def test_the_topics_title_stuffed_into_the_telescope_film_does_not_buy_it():
    # The cheapest way around the topic count: say the title, then tell the other film.
    voiceover = "Why is Nepal being handed a climate bill it cannot pay?\n\n" + JWST_VOICEOVER
    for ids in ([REHEARSAL_CLAIM], list(NEPAL_CLAIMS)):
        measured = measure_grounding(
            topic_title=NEPAL_TITLE,
            topic_angle=NEPAL_ANGLE,
            claims=_cited(ids),
            voiceover=voiceover,
        )
        assert measured["status"] == REFUSED
        assert any("nu o spune" in reason for reason in measured["reasons"])


def test_one_claim_said_and_three_cited_is_refused_for_the_two_unsaid():
    voiceover = (
        "Nepal is globally ranked fourth in vulnerability to climate change, and it is being "
        "handed a climate bill it cannot pay."
    )
    measured = measure_grounding(
        topic_title=NEPAL_TITLE,
        topic_angle=NEPAL_ANGLE,
        claims=_cited([FOURTH, FLOODS, PLEDGE]),
        voiceover=voiceover,
    )
    assert measured["status"] == REFUSED
    absent = {row["claim_id"] for row in measured["claims"] if not row["present"]}
    assert absent == {FLOODS, PLEDGE}


def test_the_claims_words_around_other_numbers_are_refused():
    # Same words, wrong world: a 40th place, a 1998 flood, six million.
    voiceover = (
        "Nepal ranks 40th for climate vulnerability. In 1998 floods on the southern border "
        "caused US$6 million in damages."
    )
    measured = measure_grounding(
        topic_title=NEPAL_TITLE,
        topic_angle=NEPAL_ANGLE,
        claims=_cited([FOURTH, FLOODS]),
        voiceover=voiceover,
    )
    assert measured["status"] == REFUSED


# --------------------------------------------------------- where it refuses, in the studio --


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    return engine


def _nepal_topic(engine) -> str:
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title=NEPAL_TITLE,
                topic="Nepal's climate finance gap",
                angle=NEPAL_ANGLE,
                target_audience="general",
                novelty_score=0.7,
                status="SELECTED",
                created_at=utc_now(),
            )
        )
        source_id = str(uuid4())
        session.add(
            SourceSnapshot(
                id=source_id,
                topic_id=topic_id,
                url="https://en.wikipedia.org/wiki/Climate_finance",
                title="Climate finance",
                publisher="Wikipedia",
                content_hash="0" * 64,
                raw_content="-",
                sanitized_content="-",
                credibility_score=0.8,
                fetched_at=utc_now(),
            )
        )
        for claim_id, text in NEPAL_CLAIMS.items():
            session.add(
                FactualClaim(
                    id=claim_id,
                    source_id=source_id,
                    topic_id=topic_id,
                    claim_text=text,
                    claim_type="GENERAL",
                    importance="KEY",
                    status="SUPPORTED",
                    confidence=0.9,
                    evidence_text=text,
                    created_at=utc_now(),
                )
            )
    return topic_id


PURPOSES = ["HOOK", "SETUP", "DEVELOPMENT", "REVEAL", "ENDING"]


def _script(engine, topic_id, lines, claim_ids, *, status="VERIFIED_PASS", story=None) -> str:
    scenes = [
        {
            "scene_number": index,
            "purpose": PURPOSES[min(index - 1, len(PURPOSES) - 1)]
            if index < len(lines)
            else "ENDING",
            "narration": line,
            "visual_description": "a river valley under monsoon cloud",
            "claim_ids": ids,
        }
        for index, (line, ids) in enumerate(zip(lines, claim_ids, strict=True), start=1)
    ]
    script_id = str(uuid4())
    cited = []
    for ids in claim_ids:
        cited.extend(cid for cid in ids if cid not in cited)
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title="Nepal's climate bill",
                target_duration_seconds=30,
                voiceover_full_text="\n\n".join(lines),
                scenes_json=scenes,
                status=status,
                claim_ids_json=cited,
                unverified_claim_ids_json=[],
                story_json=story
                if story is not None
                else {
                    "core_message": "Nepal pays for a climate it did not heat.",
                    "takeaway": "The promised money went elsewhere.",
                    "hook": lines[0],
                    "ending": lines[-1],
                    "cta": "Who should pay the climate bill Nepal is handed?",
                    "cta_kind": "DEBATE",
                },
                created_at=utc_now(),
            )
        )
    return script_id


def _jwst_script(engine, topic_id, **kwargs) -> str:
    lines = JWST_VOICEOVER.split("\n\n")
    return _script(engine, topic_id, lines, [[REHEARSAL_CLAIM]] * len(lines), **kwargs)


def test_the_story_review_refuses_the_rehearsals_script_before_the_storyboard(studio):
    from app.runbook.stages import _director_approves

    engine = studio
    script_id = _jwst_script(engine, _nepal_topic(engine))

    review = review_story(engine, None, script_id, target_seconds=30)

    assert review["verdict"] != "PASS"
    assert "narration_is_grounded" in review["failed"]
    check = review["checks"]["narration_is_grounded"]
    assert check["passed"] is False
    assert "0be61855" in check["reason"] and "nepal" in check["reason"]
    assert check["measured"]["status"] == REFUSED
    # The writer is told, in the review's notes, what is missing.
    assert any("0be61855" in note for note in review["notes"])
    # And nothing downstream moves: the Director cannot approve it, the gate before the
    # money holds it.
    assert _director_approves(engine, script_id, review) is None
    with Session(engine) as session:
        assert session.get(ScriptDraft, script_id).status == "VERIFIED_PASS"
        passed, why = story_gate(session, script_id)
    assert passed is False


def test_the_story_review_passes_a_faithful_script(studio):
    engine = studio
    script_id = _script(engine, _nepal_topic(engine), FAITHFUL, FAITHFUL_CLAIMS)

    review = review_story(engine, None, script_id, target_seconds=30)

    assert review["checks"]["narration_is_grounded"]["passed"] is True
    assert "narration_is_grounded" not in review["failed"]


def test_the_directors_facts_carry_the_measurement(studio):
    engine = studio
    script_id = _jwst_script(engine, _nepal_topic(engine))
    with Session(engine) as session:
        facts = _script_facts(session, session.get(ScriptDraft, script_id))
    assert facts["grounding"]["status"] == REFUSED
    assert facts["grounding"]["claims"][0]["claim_id"] == REHEARSAL_CLAIM
    assert facts["grounding"]["reasons"]


def test_an_old_pass_does_not_carry_an_ungrounded_script_past_the_gate(studio):
    """A script approved and passed before this check existed is measured at the gate before
    the money, so a PASS written without it cannot buy a shot for a film about the wrong
    thing."""
    engine = studio
    script_id = _jwst_script(engine, _nepal_topic(engine), status="APPROVED")
    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                verdict="PASS",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={},
                estimated_seconds=30.0,
                created_at=utc_now(),
            )
        )
    with Session(engine) as session:
        passed, why = story_gate(session, script_id)
    assert passed is False
    assert "0be61855" in why

    faithful = _script(engine, _nepal_topic_again(engine), FAITHFUL, FAITHFUL_CLAIMS)
    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=faithful,
                verdict="PASS",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={},
                estimated_seconds=30.0,
                created_at=utc_now(),
            )
        )
    with Session(engine) as session:
        assert story_gate(session, faithful) == (True, "")


def _nepal_topic_again(engine) -> str:
    """A second topic over the same claims: the fixture's claim ids are fixed, so the
    faithful film reuses the first topic's rows."""
    with Session(engine) as session:
        return session.get(FactualClaim, REHEARSAL_CLAIM).topic_id


def test_the_serial_is_not_measured_this_way(studio):
    """An episode of the office serial is a dramatisation: no claims about the world, no
    sources, and nothing here asks it for any."""
    engine = studio
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="The number before good morning",
                topic="office_serial",
                angle="Episodul serialului pentru ziua 2026-09-17",
                target_audience="general",
                novelty_score=0.5,
                status="SERIAL",
                created_at=utc_now(),
            )
        )
    line = (
        "Sarah opens the board and asks for the number before anyone says good morning. "
        "Aris answers with the evidence first and the opinion never."
    )
    script_id = _script(
        engine,
        topic_id,
        [line],
        [[]],
        status="APPROVED",
        story={"kind": "office_serial_episode", "episode_number": 1},
    )
    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                verdict="PASS",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={},
                estimated_seconds=30.0,
                created_at=utc_now(),
            )
        )
    with Session(engine) as session:
        script = session.get(ScriptDraft, script_id)
        assert script_grounding(session, script) is None
        assert story_gate(session, script_id) == (True, "")


# ------------------------------------------------------------ the rehearsal's own stage --


class _TelescopeWriter:
    """The rehearsal's stand-in: the telescope film for any topic, citing the first claim id
    it was given, and a Director whose own reading passes everything."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def health_check(self):
        from app.providers.base import HealthResult

        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        import json
        import re

        from app.providers.base import GenerateResult

        self.prompts.append(prompt)
        if "core_message" in prompt:
            ids = re.findall(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", prompt
            )
            lines = JWST_VOICEOVER.split("\n\n")
            answer = {
                "title": "The light your eyes were not built for",
                "core_message": "Infrared shows what visible light hides.",
                "takeaway": "The sky is not as empty as it looks.",
                "hook": lines[0],
                "ending": lines[-1],
                "cta": "Look up tonight and ask what else is hiding.",
                "cta_kind": "CURIOSITY",
                "scenes": [
                    {"narration": line, "visual": "a dark sky", "purpose": purpose,
                     "claim_ids": ids[:1]}
                    for line, purpose in zip(
                        lines, ["HOOK", "EVIDENCE", "PAYOFF", "ENDING"], strict=True
                    )
                ],
            }  # fmt: skip
            return GenerateResult(json.dumps(answer), 10, 40, None)
        if "hook_strength" in prompt:
            answer = {"verdict": "PASS", "hook_strength": 82, "clarity": 85, "payoff": 80,
                      "cta_fit": 78, "retention": {"at_3": 88}, "notes": []}  # fmt: skip
            return GenerateResult(json.dumps(answer), 10, 40, None)
        return GenerateResult("{}", 10, 40, None)


def test_the_rehearsals_day_no_longer_approves_or_storyboards_the_telescope_film(studio):
    """The rehearsal's script stage, replayed: the same stand-in, the same topic and claims.
    Then it wrote one draft, the Director passed it and it was storyboarded. Now every draft
    is sent back with the unsaid claim named, none is approved, nothing is storyboarded."""
    from app.agents.models import Agent, ModelRecord
    from app.media.models import Storyboard
    from app.models import OwnerPolicy
    from app.providers.registry import ProviderRegistry
    from app.runbook.stages import _script_and_storyboard
    from sqlalchemy import select

    engine = studio
    with Session(engine) as session, session.begin():
        # The rehearsal ran with the stop cleared, as the Owner's day does.
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent.provider_id))
    registry = ProviderRegistry()
    writer = _TelescopeWriter()
    registry.register(provider_id, writer)
    topic_id = _nepal_topic(engine)

    outcome = _script_and_storyboard(engine, registry, target_seconds=30)

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["storyboards"] == 0
    verdicts = [r["verdict"] for r in outcome["artefacts"]["story_reviews"]]
    assert verdicts and "PASS" not in verdicts, outcome
    assert all(
        "narration_is_grounded" in r["failed"] for r in outcome["artefacts"]["story_reviews"]
    )
    with Session(engine) as session:
        drafts = list(session.scalars(select(ScriptDraft).where(ScriptDraft.topic_id == topic_id)))
        assert drafts and all(d.status != "APPROVED" for d in drafts)
        assert session.scalars(select(Storyboard)).first() is None
        review = session.scalars(
            select(StoryReview).where(StoryReview.script_id == drafts[-1].id)
        ).first()
        # The writer is briefed with the reason: which claim went unsaid, and the topic.
        assert any("0be61855" in note for note in review.notes_json["notes"])
    # And the rewrite brief the writer received carries that note.
    assert any("0be61855" in prompt for prompt in writer.prompts if "core_message" in prompt)
