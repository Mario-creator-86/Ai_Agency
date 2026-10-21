"""The suite's films timed by «pauza vocii» (the Owner, 2026-10-16), and the numbers their
tests re-derive from.

The pause rules (config/pause_rules.json) are the Owner's proposal and the voices are measured
from every kept take (`pauses.load_profiles`): neither may move a test's numbers, so the suite
is timed by PINNED_VOICE_PROFILES (conftest pins it the way STILL_CANDIDATES is pinned). A film a
test builds row by row is frozen as the storyboard builders freeze theirs (`freeze_film`:
`pause_plan.freeze_rows` over `pause_plan.factual_side`), and its expected lengths are written
with the pauses below, computed by the rules' own formulas from the pinned voice.

Nothing here calls a model, a vendor or the network.
"""

from __future__ import annotations

from typing import Any

#: The voices the suite is timed by, in the derived cache's own shape: both pools measured past
#: the rules' min_samples. The narrator's and the cast's full-stop, clause and dash pauses are
#: the 2026-10-16 measurement (the rules' fallback pools); the narrator's high rate is the 0.40 s
#: a spoken word the suite's films were written at (the design's own w_hi), his median the
#: design's 0.368.
PINNED_VOICE_PROFILES: dict[str, Any] = {
    "format": 1,
    "key": "suite-pinned",
    "takes": 55,
    "voices": {},
    "pools": {
        "narrator": {
            "takes": 25,
            "classes": {
                "SENTENCE": {"median": 0.49, "p25": 0.34, "n": 12},
                "CLAUSE": {"median": 0.2, "p25": 0.14, "n": 10},
                "DASH": {"median": 0.3, "p25": 0.18, "n": 10},
            },
            "rate": {
                "seconds_per_word": 0.368,
                "take_median_seconds_per_word": 0.368,
                "take_median_words_per_second": 2.72,
                "take_p25_words_per_second": 2.5,
            },
        },
        "character": {
            "takes": 30,
            "classes": {
                "SENTENCE": {"median": 0.28, "p25": 0.23, "n": 32},
                "CLAUSE": {"median": 0.24, "p25": 0.19, "n": 22},
                "DASH": {"median": 0.35, "p25": 0.18, "n": 10},
            },
            "rate": {
                "seconds_per_word": 0.34,
                "take_median_seconds_per_word": 0.34,
                "take_median_words_per_second": 2.94,
                "take_p25_words_per_second": 2.6667,
            },
        },
    },
}


def narrator() -> Any:
    """The pinned narrator, as the rules time him."""
    from app.media import pauses

    return pauses.voice_profile(None, rules=pauses.load_rules(), profiles=PINNED_VOICE_PROFILES)


def pause(cls: str, *, short: bool = False) -> float:
    """The pinned narrator's planned pause of class ``cls`` (``short``: the full stop between
    two short sentences), by the rules' own formula (`pauses.target`) and the factual knobs."""
    from app.media import pauses

    rules = pauses.load_rules()
    voice = narrator()
    return pauses.target(
        cls,
        out=voice,
        inn=voice,
        narrator=voice,
        knobs=pauses.channel_pauses("factual", rules),
        rules=rules,
        short=short,
    )


#: The narrator's high rate (a clip is bought for it) and his median (a film is aimed at it).
HIGH = 0.40
MEDIAN = 0.368
#: The margin an estimated narration is bought with (`assembler.NARRATION_ESTIMATE_MARGIN`).
MARGIN = 0.10


def freeze_film(engine: Any, storyboard_id: str) -> dict[str, Any] | None:
    """A factual film a test built row by row, its pauses frozen as `media.services` freezes a
    storyboard's (`pause_plan.freeze_rows`): each row one side, its writer's scene its montage
    tag's (else its own row), its purpose and kind its row's. Returns what was frozen."""
    from app.media import pauses
    from app.media.models import Storyboard, StoryboardScene
    from app.media.montage import beat_of
    from app.media.pause_plan import RowSpec, factual_side, freeze_rows
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    rules = pauses.load_rules()
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        specs = [
            RowSpec(
                row=row,
                sides=[
                    factual_side(
                        str(row.voiceover_segment or ""),
                        scene=int(beat_of(row.prompt_json).get("scene_number") or row.scene_index),
                        purpose=row.story_purpose,
                        kind=row.scene_kind,
                        planned_seconds=float(row.duration_seconds or 0.0),
                        rules=rules,
                    )
                ],
            )
            for row in rows
        ]
        return freeze_rows(session, board, specs, serial=False, rules=rules)
