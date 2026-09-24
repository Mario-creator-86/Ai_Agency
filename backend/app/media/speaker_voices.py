"""One voice per speaker: the takes of a scene whose lines say who speaks them.

Measured before this module (2026-09-24): a serial scene was one voiceover read by one voice,
the first speaker's locked voice where a bible had one and the narrator's otherwise. On the
Owner's data no bible has a voice, so every line of every episode was the narrator's, and
two people talking sounded like one person reading. The storyboard already kept each
scene's lines with their speakers on the script (`app.story.lines`); this module turns them
into takes:

- **The takes.** A scene's lines become one take per run of one speaker, in the order they
  are said (`speaker_segments`). A narrator line (no speaker) is a take of its own.
- **The voice of a take**, in this order (`speaker_voice`):
  1. the character's locked voice (the bible's identity lock with its binding), resolved by
     the production policy exactly as a locked scene is;
  2. the voice the Owner bound to the character, locked or not: binding is his act;
  3. the voice `config/serial_voice_cast.json` proposes for the character, used only while
     the file says so and only if that voice is a discovered, available voice of the
     narrator's own connection: a proposal names his catalogue, never a guess;
  4. the narrator's, which is the scene's voice with no character in it: the channel's,
     the series', or the Organization default.
  A consistency-locked channel is not refused for a speaker with no voice of their own: the
  proposal and the narrator are both fixed from episode to episode, which is what the lock
  exists to keep, and the plan says which one spoke.
- **The guard.** The lines are read from the script, and the scene's narration is what the
  film says. When the two no longer say the same words, the lines are stale and the scene is
  read whole by one voice, as before.

Nothing here synthesises: choosing a voice id is configuration. The assembler speaks the
takes, joins them with `SPEAKER_GAP_SECONDS` of silence and times the captions to them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ROOT
from app.factual.models import ScriptDraft
from app.integrations.models import Integration
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.publishing.models import ChannelRecord

#: The Owner's proposal file: which catalogue voice each character speaks in by default.
VOICE_CAST_FILE = ROOT / "config" / "serial_voice_cast.json"

#: The breath between two speakers: long enough to hear a new person, short enough to be
#: one conversation. Between two scenes the picture decides the pause, not this.
SPEAKER_GAP_SECONDS = 0.3

#: The keys of a resolved voice the plan records for a take.
_VOICE_KEYS = (
    "integration_id",
    "model_id",
    "voice_id",
    "voice_settings",
    "valid",
    "source_level",
    "lock_applied",
    "character_id",
)


def load_voice_cast(path: Path | None = None) -> dict[str, Any]:
    """The proposal as the resolver reads it: {status, version, provider_kind, in_use, voices}.

    ``voices`` maps a bible's canonical name to a voice id, and is empty while the file says
    it is not in use; ``proposed`` keeps what it names either way, for the page. A missing
    or unreadable file proposes nothing.
    """
    source = path or VOICE_CAST_FILE
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        return {
            "status": "MISSING",
            "version": None,
            "provider_kind": None,
            "in_use": False,
            "voices": {},
            "proposed": {},
        }
    proposed: dict[str, str] = {}
    entries = data.get("voices")
    for name, entry in (entries if isinstance(entries, dict) else {}).items():
        voice_id = entry.get("voice_id") if isinstance(entry, dict) else entry
        if isinstance(voice_id, str) and voice_id.strip():
            proposed[str(name)] = voice_id.strip()
    in_use = bool(data.get("use_until_the_owner_binds", False))
    return {
        "status": str(data.get("status") or "PROPOSED"),
        "version": data.get("version"),
        "provider_kind": data.get("provider_kind"),
        "in_use": in_use,
        "voices": dict(proposed) if in_use else {},
        "proposed": proposed,
    }


def _words(text: Any) -> str:
    return " ".join(str(text or "").split())


def speaker_segments(
    lines: list[dict[str, Any]], speaker_bibles: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """The takes of one scene: consecutive lines of one speaker joined, in the order said.

    Each take is ``{speaker, character_id, text}``; the speaker is the roster name (None for
    the narrator) and ``character_id`` the bible that speaker has, if any. The text is the
    spoken words only: the lines were stored without names and directions.
    """
    bibles = speaker_bibles or {}
    takes: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        text = _words(line.get("text"))
        if not text:
            continue
        speaker = str(line["speaker"]) if line.get("speaker") else None
        if takes and takes[-1]["speaker"] == speaker:
            takes[-1]["text"] = f"{takes[-1]['text']} {text}"
            continue
        takes.append(
            {
                "speaker": speaker,
                "character_id": bibles.get(speaker) if speaker else None,
                "text": text,
            }
        )
    return takes


def _recorded(resolved: dict[str, Any], source: str, notes: list[str]) -> dict[str, Any]:
    voice = {key: resolved.get(key) for key in _VOICE_KEYS}
    voice["speaker_source"] = source
    voice["notes"] = list(resolved.get("notes") or []) + notes
    return voice


def speaker_voice(
    session: Session,
    narrator: dict[str, Any],
    character: CharacterBible | None,
    cast: dict[str, Any],
    *,
    channel: ChannelRecord | None = None,
    series_key: str | None = None,
    episode_overrides: dict | None = None,
    scene_overrides: dict | None = None,
) -> dict[str, Any]:
    """The voice one take is spoken in, with where it came from (see the module's order)."""
    from app.media.production_policy import _validate, resolve_purpose  # noqa: PLC0415

    if character is None:
        return _recorded(narrator, "narrator", [])
    notes: list[str] = []
    binding = character.voice_binding_json or {}
    if binding.get("voice_id"):
        if (character.identity_locks_json or {}).get("voice"):
            locked = resolve_purpose(
                session,
                "voice",
                channel=channel,
                series_key=series_key,
                episode_overrides=episode_overrides,
                scene_overrides=scene_overrides,
                characters=[character],
            )
            return _recorded(locked, "character_lock", notes)
        bound = {
            **narrator,
            "integration_id": binding.get("integration_id") or narrator.get("integration_id"),
            "voice_id": binding["voice_id"],
            "model_id": binding.get("model_id") or narrator.get("model_id"),
            "voice_settings": binding.get("voice_settings") or narrator.get("voice_settings"),
            "character_id": character.id,
            "notes": [],
        }
        valid, why = _validate(session, "voice", bound)
        if valid:
            return _recorded({**bound, "valid": True}, "character_binding", notes)
        notes.append(f"{character.canonical_name}'s bound voice cannot be used: {why}")

    proposed = (cast.get("voices") or {}).get(character.canonical_name)
    if proposed and narrator.get("integration_id"):
        integration = session.get(Integration, narrator["integration_id"])
        kind = cast.get("provider_kind")
        if integration is not None and (not kind or integration.kind == kind):
            chosen = {
                **narrator,
                "voice_id": proposed,
                "character_id": character.id,
                "notes": [],
            }
            valid, why = _validate(session, "voice", chosen)
            if valid:
                return _recorded({**chosen, "valid": True}, "voice_cast_proposal", notes)
            notes.append(
                f"The proposed voice {proposed} for {character.canonical_name} cannot be used: "
                f"{why}"
            )
        else:
            notes.append(
                f"The proposed voice for {character.canonical_name} belongs to another kind "
                "of connection than the narrator's"
            )
    notes.append(
        f"{character.canonical_name} has no voice of their own; the narrator's voice speaks "
        "their lines"
    )
    return _recorded(narrator, "narrator", notes)


def plan_speakers(session: Session, board: Storyboard, plan: dict[str, Any]) -> None:
    """Add each scene's takes and their voices to a resolved storyboard plan, in place.

    Only a scene whose script entry carries lines has takes, and only while those lines say
    what the scene's narration says; every other scene is read whole, exactly as before.
    """
    from app.media.production_policy import resolve_purpose  # noqa: PLC0415

    cast = load_voice_cast()
    plan["voice_cast"] = {
        "status": cast["status"],
        "version": cast["version"],
        "in_use": cast["in_use"],
        "file": "config/serial_voice_cast.json",
    }
    script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
    stored = [s for s in (script.scenes_json or []) if isinstance(s, dict)] if script else []
    if not any(isinstance(s.get("lines"), list) and s.get("lines") for s in stored):
        return
    by_index = {int(s.get("scene_index") or n): s for n, s in enumerate(stored, start=1)}
    rows = {
        row.scene_index: row
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board.id)
        )
    }
    channel = session.get(ChannelRecord, board.channel_id) if board.channel_id else None
    for scene_plan in plan.get("scenes", []):
        index = scene_plan.get("scene_index")
        entry = by_index.get(index) if isinstance(index, int) else None
        row = rows.get(index) if isinstance(index, int) else None
        lines = entry.get("lines") if entry else None
        if row is None or not isinstance(lines, list) or not lines:
            continue
        takes = speaker_segments(lines, entry.get("speaker_bibles") if entry else None)
        if not takes:
            continue
        if _words(" ".join(t["text"] for t in takes)) != _words(row.voiceover_segment):
            scene_plan["speakers_note"] = (
                "The scene's narration no longer matches its lines; it is read by one voice."
            )
            continue
        narrator = resolve_purpose(
            session,
            "voice",
            channel=channel,
            series_key=board.series_key,
            episode_overrides=board.production_overrides_json,
            scene_overrides=row.production_overrides_json,
        )
        ids = [t["character_id"] for t in takes if t["character_id"]]
        bibles = (
            {
                b.id: b
                for b in session.scalars(select(CharacterBible).where(CharacterBible.id.in_(ids)))
            }
            if ids
            else {}
        )
        scene_plan["speakers"] = [
            {
                **take,
                "voice": speaker_voice(
                    session,
                    narrator,
                    bibles.get(take["character_id"]) if take["character_id"] else None,
                    cast,
                    channel=channel,
                    series_key=board.series_key,
                    episode_overrides=board.production_overrides_json,
                    scene_overrides=row.production_overrides_json,
                ),
            }
            for take in takes
        ]
