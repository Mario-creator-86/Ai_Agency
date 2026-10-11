"""The sound department plans the music: which bed, how far under the words, where it may rise.

Owner, 2026-10-11: «Un agent, acum cel potrivit trebuie să monteze și muzica, cea care este
necesară în funcție de video. Acesta trebuie ca muzica să o pună la o diferență destul de mare de
voce, adică să fie doar pe fundal, să fie încet sau tare, acolo unde trebuie. Mare grijă totuși
să nu acopere vocea. Implementează acest lucru la agentul de la sunet.»

Until then the bed was chosen by counting mood words (`music_library.choose_bed`) and sat at one
level under the whole film. Now the Voice Artist — the studio's sound department, the one who
reviews the narration before it is voiced — is asked for a plan before the mix
(`sound_plan`, a structured task through `agents.structured.structured_run`): one bed from the
Owner's library, a level per scene, an ambience where a scene's audio intent calls for one, the
fades, and why, in Romanian, for the Owner. The schema is bound to the film (`plan_schema`): an
id the library does not have, a scene not planned or planned twice, is refused with the reason,
and she is asked once more with it. Without a model, or refused twice, the deterministic plan
(`deterministic_plan`: today's choice, every scene "under") takes over, so a film is never
without its mix, and the record says which it was.

What her plan may ask is bounded by the mix, never by her word (`toolchain.mix_bed`): "under"
keeps the bed 20 LU under the voice where the voice speaks, "soft" takes it 6 dB further down,
and "lift" raises it 8 dB only inside the voice's own silences, measured on the voice track;
quality control (`qc.audio_mix_verdict`) then refuses a mix whose bed sits under 18 LU below the
words. When it refuses, the Director's free audio redo asks her again with the refusal quoted
(`replan`): the measured numbers, the reasons, her previous plan; the new plan must change and
may add no lift. The deterministic plan is the last resort there too.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media import music_library
from app.media.music_library import Library, Track
from app.media.toolchain import (
    BED_FADE_BOUNDS,
    BED_FADE_IN_SECONDS,
    BED_FADE_OUT_SECONDS,
    LEVEL_GAIN_DB,
)
from app.services import utc_now
from app.wording import error_words

logger = logging.getLogger("studio.sound_design")

#: The role that plans the sound: the studio's sound department.
SOUND_ROLE = "VoiceArtist"
SOUND_DESIGN_TASK = "sound_design"
SOUND_DESIGN_TEMPLATE = "sound-design-v1"
#: Who made a film's plan, as production['audio']['plan']['source'] records it.
SOURCE_VOICE_ARTIST = "voice_artist"
SOURCE_DETERMINISTIC = "deterministic"
#: The plan a film was mixed with, and a plan asked again after quality control refused the mix
#: (on the storyboard: {source, by, run_id, bed, levels, ...}; the second with what changed).
PLAN_EVENT = "media.sound_plan_written"
REPLAN_EVENT = "media.sound_plan_replanned"
LEVELS: tuple[str, ...] = tuple(LEVEL_GAIN_DB)
#: How much of a brief one call may carry, in characters of JSON (`prompt_agent.trim_payload`).
MAX_PAYLOAD_CHARS = 14000
MAX_TOKENS = 3000

Level = Literal["under", "soft", "lift"]


class ScenePlan(BaseModel):
    """One scene of the plan: its level and, where the scene calls for it, an ambience."""

    model_config = ConfigDict(extra="ignore")
    scene_index: int = Field(ge=1, le=200)
    level: Level = "under"
    ambience: str | None = None
    why: str = Field(default="", max_length=300)

    @field_validator("level", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return str(value).strip().lower() if isinstance(value, str) else value

    @field_validator("ambience", mode="before")
    @classmethod
    def _no_ambience(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return None if text.lower() in ("", "none", "null", "-", "fără", "fara") else text


def _fade(value: Any, default: float) -> float:
    low, high = BED_FADE_BOUNDS
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        number = float(value)
    except ValueError:
        return default
    if number != number:  # NaN
        return default
    return min(max(number, low), high)


class SoundPlan(BaseModel):
    """The sound department's plan for one film: the bed, a level per scene, the fades."""

    model_config = ConfigDict(extra="ignore")
    bed: str | None = None
    why: str = Field(default="", max_length=400)
    scenes: list[ScenePlan] = Field(default_factory=list, max_length=200)
    fade_in_seconds: float = BED_FADE_IN_SECONDS
    fade_out_seconds: float = BED_FADE_OUT_SECONDS
    summary_ro: str = Field(default="", max_length=600)

    @field_validator("bed", mode="before")
    @classmethod
    def _no_bed(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return None if text.lower() in ("", "none", "null", "-", "fără", "fara") else text

    @field_validator("fade_in_seconds", mode="before")
    @classmethod
    def _fade_in(cls, value: Any) -> Any:
        return _fade(value, BED_FADE_IN_SECONDS)

    @field_validator("fade_out_seconds", mode="before")
    @classmethod
    def _fade_out(cls, value: Any) -> Any:
        return _fade(value, BED_FADE_OUT_SECONDS)

    def level_of(self, scene_index: int) -> str:
        return next((s.level for s in self.scenes if s.scene_index == scene_index), "under")

    def lifts(self) -> list[int]:
        return sorted(s.scene_index for s in self.scenes if s.level == "lift")

    def level_counts(self) -> dict[str, int]:
        counts = {level: 0 for level in LEVELS}
        for scene in self.scenes:
            counts[scene.level] += 1
        return counts


def _ids(library: Library, kind: str) -> set[str]:
    return {track.id for track in library.tracks if track.kind == kind}


def _previous_shape(previous: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The refused plan reduced to what a new plan is compared against."""
    if not previous:
        return None
    scenes = {
        int(item["scene_index"]): (
            str(item.get("level") or "under").lower(),
            item.get("ambience") or None,
        )
        for item in previous.get("scenes") or []
        if isinstance(item, Mapping) and item.get("scene_index") is not None
    }
    return {"bed": previous.get("bed") or None, "scenes": scenes}


def plan_schema(
    library: Library,
    scene_indexes: Iterable[int],
    *,
    previous: Mapping[str, Any] | None = None,
) -> type[SoundPlan]:
    """`SoundPlan` bound to this film: the bed a music track of the library (or null), every
    ambience an ambience track of it (or null), every scene named once and none the film does
    not have. With ``previous`` (a plan quality control refused), the new plan must differ from
    it and may not add a lift: the same plan would only be mixed again and refused again."""
    beds = _ids(library, "music")
    ambiences = _ids(library, "ambience")
    expected = {int(index) for index in scene_indexes}
    before = _previous_shape(previous)

    class BoundPlan(SoundPlan):
        @model_validator(mode="after")
        def _this_film(self) -> BoundPlan:
            if self.bed is not None and self.bed not in beds:
                raise ValueError(
                    f"bed {self.bed!r} is not a music track of the library; use one of "
                    f"{sorted(beds)} or null"
                )
            unknown = sorted(
                {s.ambience for s in self.scenes if s.ambience and s.ambience not in ambiences}
            )
            if unknown:
                raise ValueError(
                    f"ambience {unknown} is not an ambience track of the library; use one of "
                    f"{sorted(ambiences)} or null"
                )
            named = [s.scene_index for s in self.scenes]
            repeated = sorted({index for index in named if named.count(index) > 1})
            missing = sorted(expected - set(named))
            strange = sorted(set(named) - expected)
            if repeated or missing or strange:
                raise ValueError(
                    f"scenes not planned {missing}, unknown {strange}, repeated {repeated}: "
                    f"name each of {sorted(expected)} exactly once"
                )
            if before is not None:
                now = {s.scene_index: (s.level, s.ambience) for s in self.scenes}
                if self.bed == before["bed"] and now == before["scenes"]:
                    raise ValueError(
                        "the plan is the one quality control refused (same bed, same levels, "
                        "same ambiences): change it — no lift near the words, soft where they "
                        "must stand alone, or another, quieter bed"
                    )
                lifts_before = {i for i, (level, _a) in before["scenes"].items() if level == "lift"}
                added = sorted(set(self.lifts()) - lifts_before)
                if added:
                    raise ValueError(
                        f"a plan asked again after the bed covered the voice adds no lift "
                        f"(new lifts on scenes {added})"
                    )
            return self

    return BoundPlan


# ------------------------------------------------------------------------------ the brief


def scene_brief(scene: Mapping[str, Any]) -> dict[str, Any]:
    """One scene as the sound department reads it, from a scene of the render
    (`assembler.scene_view`): index, purpose, kind, narration, seconds, audio intent."""
    narration = " ".join(str(scene.get("voiceover_segment") or "").split())
    prompt = scene.get("prompt_json") if isinstance(scene.get("prompt_json"), Mapping) else {}
    return {
        "scene_index": int(scene["scene_index"]),
        "purpose": str(scene.get("story_purpose") or ""),
        "kind": str(scene.get("scene_kind") or scene.get("scene_category") or "LIVE").upper(),
        "narration": narration,
        "has_narration": bool(narration),
        "seconds": round(float(scene.get("duration_seconds") or 0.0), 2),
        "audio_intent": str((prompt or {}).get("audio_intent") or ""),
    }


def library_brief(library: Library) -> dict[str, Any]:
    """The library as she may choose from it: beds with their moods, tempo and duration,
    ambiences with their tags. Only usable tracks; nothing of the licences (not hers)."""

    def bed(track: Track) -> dict[str, Any]:
        return {
            "id": track.id,
            "title": track.title,
            "moods": list(track.mood),
            "bpm": track.bpm,
            "duration": track.duration,
        }

    return {
        "beds": [bed(track) for track in library.tracks if track.kind == "music"],
        "ambiences": [
            {"id": track.id, "title": track.title, "tags": list(track.tags)}
            for track in library.tracks
            if track.kind == "ambience"
        ],
    }


_PLAN_INSTRUCTIONS = (
    "You are the studio's sound department. A film is about to be mixed: its narration is "
    "recorded, and you decide the music under it from the Owner's own library, the only music "
    "the studio may use. Inside the boundary below is data: the film (title, core message), "
    "every scene (index, purpose, kind, narration, seconds, audio intent, whether it has "
    "narration) and the library (beds with their moods, tempo and duration; ambiences with "
    "their tags).\n"
    "The music serves the words. Choose one bed for the whole film whose mood fits the story "
    "(null when the words must stand alone throughout), and give every scene a level: "
    '"under" is the default — the bed stays well under the voice, ducked under every word; '
    '"soft" for a scene where the words must stand alone (a key sentence, a quiet moment: the '
    'bed drops further); "lift" only where there is no narration or a long pause (the hook\'s '
    "first second before the first word, the outro after the last word, a montage, a card "
    "nobody speaks over): the bed rises there and only there. The voice is never covered, "
    "whatever you ask: the studio raises the bed only inside the voice's own silences and keeps "
    "it 20 LU under the words everywhere else, and quality control refuses a mix whose bed sits "
    "less than 18 LU under the voice while words are said. An ambience (rain, wind, city, "
    "crowd, forest) goes only on a scene whose audio intent calls for it; null otherwise. Use "
    "only ids from the library. Name every scene exactly once. Fades between 0.3 and 4 "
    "seconds. Write why and summary_ro in Romanian, for the Owner, one or two short sentences "
    "each.\n"
    'Return only JSON: {"bed": "<library id>" | null, "why": "...", "scenes": '
    '[{"scene_index": 1, "level": "under" | "soft" | "lift", "ambience": "<library id>" | '
    'null, "why": "..."}], "fade_in_seconds": 0.5, "fade_out_seconds": 1.5, '
    '"summary_ro": "..."}.\n'
)
_REPLAN_INSTRUCTIONS = (
    "Quality control refused the mix made from your previous plan: the bed covered the voice. "
    "Inside the boundary, refusal carries the measured numbers (LU under the voice where the "
    "words are, and in the gaps), the reasons, who asked and your previous plan. Plan the sound "
    "again so the voice leads: drop every lift that sat near words, choose soft where the words "
    "must stand alone, or another, quieter bed. The new plan must differ from the refused one "
    "and must not add a lift.\n"
)


@dataclass
class PlanOutcome:
    """A plan, who made it and how: the Voice Artist's run or the deterministic fallback."""

    plan: SoundPlan
    source: str
    run_id: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    #: Why the deterministic plan stands (Romanian, for the Owner); "" for hers.
    reason: str = ""
    attempts: int = 0
    refusals: list[str] = field(default_factory=list)


def deterministic_plan(
    library: Library,
    *,
    mood_text: str,
    seed: str,
    scenes: Sequence[Mapping[str, Any]],
    bed_id: str | None = None,
) -> SoundPlan:
    """The plan the studio makes alone: the bed today's words call for (`choose_bed`; or
    ``bed_id`` when it is still a music track of the library), an ambience where a scene's
    audio intent names one (`choose_ambience`), every scene "under", the default fades."""
    bed = library.entry(bed_id) if bed_id else None
    if bed is not None and bed.kind != "music":
        bed = None
    if bed is None:
        bed = music_library.choose_bed(library, mood_text=mood_text, seed=seed)
    moods = music_library.moods_of(mood_text)
    if bed is None:
        why = "Biblioteca nu are nicio piesă de fundal folosibilă."
    elif moods:
        named = ", ".join(sorted(moods, key=lambda mood: -moods[mood])[:3])
        why = f"Aleasă de studio după cuvintele filmului ({named})."
    else:
        why = "Aleasă de studio: cuvintele filmului nu cer o stare anume."
    planned: list[ScenePlan] = []
    for scene in scenes:
        intent = str(scene.get("audio_intent") or "")
        ambience = music_library.choose_ambience(library, intent) if intent else None
        planned.append(
            ScenePlan(
                scene_index=int(scene["scene_index"]),
                level="under",
                ambience=ambience.id if ambience is not None else None,
                why="sub voce, ca peste tot (planul fix al studioului)",
            )
        )
    ambiences = sorted({s.ambience for s in planned if s.ambience})
    summary = (
        f"Plan fix: {'piesa „' + bed.id + '”' if bed is not None else 'fără muzică'}, toate "
        f"scenele sub voce, fără ridicări"
        + (f"; ambianță: {', '.join(ambiences)}" if ambiences else "")
        + "."
    )
    return SoundPlan(
        bed=bed.id if bed is not None else None, why=why, scenes=planned, summary_ro=summary
    )


def _payload(data: Mapping[str, Any]) -> str:
    from app.media.prompt_agent import trim_payload  # noqa: PLC0415 - it imports media

    fitted, _dropped = trim_payload(dict(data), MAX_PAYLOAD_CHARS)
    return json.dumps(fitted, ensure_ascii=False, default=str)


def sound_plan(
    engine: Engine,
    registry: Any,
    *,
    film: Mapping[str, Any],
    scenes: Sequence[Mapping[str, Any]],
    library: Library,
    correlation_id: str,
    mood_text: str,
    seed: str,
    previous: Mapping[str, Any] | None = None,
    refusal: Mapping[str, Any] | None = None,
) -> PlanOutcome:
    """The film's sound plan: the Voice Artist's when a registry and an active Voice Artist
    exist and her answer validates (asked once more with the refusal when it does not,
    `structured_run`), else the deterministic plan, with the reason recorded.

    ``film`` is {title, core_message}; ``scenes`` `scene_brief` rows. ``previous`` and
    ``refusal`` make it a re-plan after quality control refused the mix (`replan`): the schema
    then also demands a change and forbids a new lift. Never raises: a fault anywhere here
    leaves the film with the deterministic plan and the fault's words."""
    fallback_bed = str(previous.get("bed")) if previous and previous.get("bed") else None
    fallback = deterministic_plan(
        library, mood_text=mood_text, seed=seed, scenes=scenes, bed_id=fallback_bed
    )
    if previous is not None:
        fallback.summary_ro = (
            "Plan fix după refuzul controlului: toate scenele sub voce, fără ridicări"
            + (f", piesa „{fallback.bed}”" if fallback.bed else ", fără muzică")
            + "."
        )
    if registry is None:
        return PlanOutcome(fallback, SOURCE_DETERMINISTIC, reason="niciun model nu a fost întrebat")
    with Session(engine) as session:
        artist = agent_for_role(session, SOUND_ROLE)
        artist_id = artist.id if artist is not None else None
        artist_name = artist.display_name if artist is not None else None
    if artist_id is None:
        return PlanOutcome(fallback, SOURCE_DETERMINISTIC, reason="niciun VoiceArtist activ")
    data: dict[str, Any] = {
        "film": {"title": film.get("title"), "core_message": film.get("core_message")},
        "scenes": [dict(scene) for scene in scenes],
        "library": library_brief(library),
    }
    if previous is not None:
        data["refusal"] = {**dict(refusal or {}), "previous_plan": _plan_words(previous)}
    instructions = _PLAN_INSTRUCTIONS + (_REPLAN_INSTRUCTIONS if previous is not None else "")
    prompt = instructions + wrap_in_inert_boundary(_payload(data), "sound-design")
    schema = plan_schema(
        library, [int(scene["scene_index"]) for scene in scenes], previous=previous
    )
    title = str(film.get("title") or "")[:60]
    summary = (
        f"Refac planul de sunet al filmului «{title}» după refuzul controlului calității."
        if previous is not None
        else f"Aleg muzica și nivelurile ei pentru filmul «{title}» ({len(scenes)} scene)."
    )
    try:
        from app.agents.structured import structured_run  # noqa: PLC0415 - it imports agents

        parsed, first, second = structured_run(
            engine,
            registry,
            artist_id,
            SOUND_DESIGN_TASK,
            prompt,
            SOUND_DESIGN_TEMPLATE,
            correlation_id,
            schema,
            "",
            summary=summary,
            max_tokens=MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - a fault never costs the film its mix
        logger.warning("sound_plan_not_asked", extra={"error": type(exc).__name__})
        return PlanOutcome(
            fallback,
            SOURCE_DETERMINISTIC,
            agent_id=artist_id,
            agent_name=artist_name,
            reason=f"planul nu a putut fi cerut ({error_words(exc)[:200]})",
        )
    runs = [run for run in (first, second) if run is not None]
    refusals = [str(run["refusal"]) for run in runs if run.get("refusal")]
    last = runs[-1] if runs else None
    if parsed is None or last is None:
        detail = str((last or {}).get("error_detail") or (last or {}).get("status") or "")
        return PlanOutcome(
            fallback,
            SOURCE_DETERMINISTIC,
            run_id=str(last["id"]) if last else None,
            agent_id=artist_id,
            agent_name=artist_name,
            reason=(
                "răspunsul nu a respectat forma cerută nici a doua oară"
                + (f" ({detail[:240]})" if detail else "")
            ),
            attempts=len(runs),
            refusals=refusals,
        )
    with Session(engine) as session, session.begin():
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=(
                f"Sound plan of “{title}”: bed {parsed.bed or 'none'}, "
                f"{parsed.level_counts()} — {parsed.summary_ro}"
            )[:2000],
            source_type="run",
            source_id=str(last["id"]),
            agent_id=artist_id,
        )
    return PlanOutcome(
        parsed,
        SOURCE_VOICE_ARTIST,
        run_id=str(last["id"]),
        agent_id=artist_id,
        agent_name=artist_name,
        attempts=len(runs),
        refusals=refusals,
    )


# ------------------------------------------------------------------------------ the record


def plan_record(outcome: PlanOutcome, spans: Mapping[int, tuple[float, float]]) -> dict[str, Any]:
    """What production['audio']['plan'] keeps: the plan with each scene's place in the film
    (``spans``: scene_index -> (start, seconds)), who made it and how."""
    plan = outcome.plan
    return {
        "template": SOUND_DESIGN_TEMPLATE,
        "source": outcome.source,
        "by": outcome.agent_name,
        "agent_id": outcome.agent_id,
        "run_id": outcome.run_id,
        "attempts": outcome.attempts,
        "refusals": list(outcome.refusals),
        "reason": outcome.reason or None,
        "bed": plan.bed,
        "why": plan.why,
        "scenes": [
            {
                "scene_index": scene.scene_index,
                "start": round(spans.get(scene.scene_index, (0.0, 0.0))[0], 3),
                "seconds": round(spans.get(scene.scene_index, (0.0, 0.0))[1], 3),
                "level": scene.level,
                "ambience": scene.ambience,
                "why": scene.why,
            }
            for scene in plan.scenes
        ],
        "fade_in_seconds": plan.fade_in_seconds,
        "fade_out_seconds": plan.fade_out_seconds,
        "summary_ro": plan.summary_ro,
        "levels": plan.level_counts(),
        "written_at": utc_now(),
    }


def plan_from_record(record: Mapping[str, Any]) -> SoundPlan:
    """The plan a film was mixed with, read back from its record (the remix keeps it)."""
    scenes = []
    for item in record.get("scenes") or []:
        if not isinstance(item, Mapping) or item.get("scene_index") is None:
            continue
        level = str(item.get("level") or "under").lower()
        scenes.append(
            {
                "scene_index": int(item["scene_index"]),
                "level": level if level in LEVELS else "under",
                "ambience": item.get("ambience") or None,
                "why": str(item.get("why") or "")[:300],
            }
        )
    return SoundPlan.model_validate(
        {
            "bed": record.get("bed") or None,
            "why": str(record.get("why") or "")[:400],
            "scenes": scenes,
            "fade_in_seconds": record.get("fade_in_seconds", BED_FADE_IN_SECONDS),
            "fade_out_seconds": record.get("fade_out_seconds", BED_FADE_OUT_SECONDS),
            "summary_ro": str(record.get("summary_ro") or "")[:600],
        }
    )


def levels_for_mix(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The level plan `toolchain.mix_bed` takes, from a plan record's scenes."""
    return [
        {
            "scene_index": int(item["scene_index"]),
            "start": float(item.get("start") or 0.0),
            "seconds": float(item.get("seconds") or 0.0),
            "level": str(item.get("level") or "under").lower(),
        }
        for item in record.get("scenes") or []
        if isinstance(item, Mapping) and item.get("scene_index") is not None
    ]


def _plan_words(record: Mapping[str, Any]) -> dict[str, Any]:
    """A plan record as a refusal quotes it: bed, each scene's level and ambience, the fades."""
    return {
        "source": record.get("source"),
        "bed": record.get("bed"),
        "scenes": [
            {
                "scene_index": item.get("scene_index"),
                "level": item.get("level"),
                "ambience": item.get("ambience"),
            }
            for item in record.get("scenes") or []
            if isinstance(item, Mapping)
        ],
        "fade_in_seconds": record.get("fade_in_seconds"),
        "fade_out_seconds": record.get("fade_out_seconds"),
    }


def changes_between(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """What a new plan changed against the refused one, in the Owner's words."""
    changed: list[str] = []
    if (previous.get("bed") or None) != (current.get("bed") or None):
        changed.append(f"piesa: {previous.get('bed') or 'fără'} → {current.get('bed') or 'fără'}")
    before = {
        int(item["scene_index"]): item
        for item in previous.get("scenes") or []
        if isinstance(item, Mapping) and item.get("scene_index") is not None
    }
    for item in current.get("scenes") or []:
        if not isinstance(item, Mapping) or item.get("scene_index") is None:
            continue
        index = int(item["scene_index"])
        old = before.get(index, {})
        if str(old.get("level") or "under") != str(item.get("level") or "under"):
            changed.append(f"scena {index}: {old.get('level') or 'under'} → {item.get('level')}")
        if (old.get("ambience") or None) != (item.get("ambience") or None):
            changed.append(
                f"scena {index}: ambianță {old.get('ambience') or 'fără'} → "
                f"{item.get('ambience') or 'fără'}"
            )
    for key, word in (("fade_in_seconds", "fade-in"), ("fade_out_seconds", "fade-out")):
        if previous.get(key) is not None and previous.get(key) != current.get(key):
            changed.append(f"{word}: {previous.get(key)} → {current.get(key)} s")
    return changed


def plan_event_payload(record: Mapping[str, Any], storyboard_id: str) -> dict[str, Any]:
    """What `PLAN_EVENT` carries: who planned, what, and why it was the fallback if it was."""
    return {
        "storyboard_id": storyboard_id,
        "source": record.get("source"),
        "by": record.get("by"),
        "run_id": record.get("run_id"),
        "attempts": record.get("attempts"),
        "reason": record.get("reason"),
        "bed": record.get("bed"),
        "levels": record.get("levels"),
        "lifts": [
            item.get("scene_index")
            for item in record.get("scenes") or []
            if isinstance(item, Mapping) and item.get("level") == "lift"
        ],
        "ambiences": sorted(
            {
                str(item.get("ambience"))
                for item in record.get("scenes") or []
                if isinstance(item, Mapping) and item.get("ambience")
            }
        ),
        "fade_in_seconds": record.get("fade_in_seconds"),
        "fade_out_seconds": record.get("fade_out_seconds"),
        "summary_ro": record.get("summary_ro"),
    }


def mix_refusal(audio: Mapping[str, Any], mix_check: Mapping[str, Any] | None) -> dict[str, Any]:
    """What a re-plan is told: the measures of the refused mix and the check's reasons."""
    bed = audio.get("bed") if isinstance(audio.get("bed"), Mapping) else {}
    check = dict(mix_check or {})
    return {
        "reasons": [str(item) for item in check.get("reasons_ro") or []],
        "measured": {
            "lu_under_voice_in_speech": (bed or {}).get("measured_lu_under_voice_in_speech"),
            "lu_under_voice_in_gaps": (bed or {}).get("measured_lu_under_voice_in_gaps"),
            "lu_under_voice_film": (bed or {}).get("measured_lu_under_voice"),
            "target_lu_under_voice": (bed or {}).get("target_lu_under_voice"),
            "band_lu": [18, 22],
        },
        "report_id": check.get("report_id"),
    }


def replan_record(
    previous: Mapping[str, Any],
    outcome: PlanOutcome,
    current: Mapping[str, Any],
    *,
    asked_by: str,
    refusal: Mapping[str, Any],
) -> dict[str, Any]:
    """One entry of production['audio']['replans']: who asked, why, what changed, who answered.
    A loop that repeats is visible here and in `REPLAN_EVENT`."""
    return {
        "at": utc_now(),
        "asked_by": asked_by,
        "report_id": refusal.get("report_id"),
        "reasons": list(refusal.get("reasons") or []),
        "measured": dict(refusal.get("measured") or {}),
        "previous": _plan_words(previous),
        "plan": _plan_words(current),
        "changed": changes_between(previous, current),
        "source": outcome.source,
        "by": outcome.agent_name,
        "run_id": outcome.run_id,
        "attempts": outcome.attempts,
        "refusals": list(outcome.refusals),
        "reason": outcome.reason or None,
    }
