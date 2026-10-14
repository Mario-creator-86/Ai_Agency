"""The Director decides a film that failed quality control (2026-10-10).

Film babcf272 («The Particle That Shouldn't Exist (But Does)»), 2026-10-10: the studio
assembled it at 11:04 UTC from takes the Owner had approved (scenes 1-4, scene 2 his approved
test shot) and scene 5, a still that came out as three stacked panels, animated locally by his
LOCAL_MOVE choice. Its QC report d4ea68d2 failed on scene 5's panels (real), on every scene for
«text or a logo» (the film-level look read the studio's own burned-in subtitles: false) and on
scenes 2 and 3 for the bible's near-black void (takes he had approved: his choice). The Video
Editor's diagnosis was filed and ignored; the mechanical repair redid scenes 1 and 2 unasked,
retired his approved still, motion and test shot (REDO.OWNER, REDO.STILL_REPLACED), rewrote the
two scenes' prompts and opened RunPod sessions; nothing was delivered, and he stopped the studio.
His direction the same day: the agents check one another, the Director supervises, and she
decides alone («BA DA! POATE DECIDE SINGURĂ!»), with two things not hers: his paid-media rule
(OVER_USD 5: the Policy Kernel's may_act asks him above it) and facts about his accounts. And
nobody ever retires a still or clip he approved himself.

This module is her desk for one failed QC report; the walk itself (review, then what she
decided, then QC again) is `app.runbook.stages.director_decides_failed_film`:

- `film_qc_context` is what she reads, as data: every finding of the report, numbered, with its
  check, its scene and whether it is hers to judge at all (`not_yours`: rights, his music
  library's licences, factual claims, placeholder visuals, how the film was made, a file that
  does not match its record); the checks; per scene its kind,
  its words, which takes are in the film and who approved them (the Owner on the sheet, or the
  studio's gate), his own choices on the sheet and what a redo would retire of his; the visual
  bible; whether the studio burned its subtitles into the film; the Video Editor's diagnosis; her
  earlier reviews of the film; the paid redos his limits still allow.
- `protected_redos` and `repair_list`: a redo that would retire a take he approved is never
  carried out (skipped, and said), whoever lists it; a new still brings new motion with it, or,
  for a scene he chose to animate locally (LOCAL_MOVE), the film rejoined from its takes for
  free (`REJOIN`); a motion is never bought against that choice.
- `decision_state`: a REPAIR waiting on something outside her (`PENDING_OUTCOMES`: his answer,
  a take bought for it waiting for his look or the vendor, a film to rejoin with an approved
  take bought for it) stands, is carried on without asking her again once that came
  (``ready``), and is hers again once it lapsed (his no, an expired question, his look
  rejecting what was bought, nothing delivered, `BOUGHT_WAIT_DAYS` waited in vain). A take
  given back after a redo that delivered nothing is never read as the new one
  (`new_approved_take`).
- `look_entries`, `record_look`, `look_letter`: the candidates bought for her REPAIR that the
  stills gate or the clip QC refused wait for her own look, not for his (the Owner, 20:06 local
  the same day: «El ar trebui să hotărască dacă poza este bună sau nu»). She is shown them with
  the gate's reasons and chooses one (approved by her, `DIRECTOR_APPROVER`, never in his name)
  or rejects them all (the report is hers again at once); he gets a STATUS letter.
- `accept_film` writes the PASSED report her ACCEPT stands on: the original checks kept, a
  ``director_qc`` check listing every verdict, her overrules among them, so the publishing QC gate
  lets the film through (the rights and factual gates still run on their own). `close_film`
  closes it through the Director's own retirement path (`runbook.stages.close_film_books`) and
  withdraws the paid questions about it. `record_decision` writes `media.director_qc_decision`;
  `director_letter` the Owner's Romanian STATUS letter (never a question);
  `wait_for_director` the note in her inbox when she could not decide (no model, an answer that
  did not validate twice): nothing is redone then, and the watchdog asks her again later
  (`app.workflows.passes.director_qc_review`).

- 2026-10-12 (19.50 USD of RunPod that day, 11.05 on redos, and all three films still failing;
  the Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE
  ȘI LA VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!»): every REAL or ACCEPTED verdict
  names its severity (a minor defect is ACCEPTED and the film published), its cause and a
  lesson, and `learn_from_decision` stores each new lesson for the prompt writers once her
  decision is recorded. A scene that passed an earlier film's picture checks with the same
  takes is ``passed_before_unchanged`` in her context (`film_qc_context`): never REAL, never
  redone; the film QC itself no longer judges it again (`picture_qc.earlier_passes`).
- The review of that change, the same evening (the studio stopped until it was merged): what
  quality control measured as serious (`reviews.measured_serious`) is never ACCEPTED, and with
  only his cap in the way her REPAIR goes to his card; «Controlul «X» a picat» is REAL only with
  its scenes' findings (``check_level``); a scene is named by its own index or scene words,
  never a bare digit; what passed, or what she judged FALSE or accepted as minor, on the same
  picture is settled check by check (``passed_before``, ``accepted_before``, ``failing_now``);
  her lessons go to `prompt_agent.record_prompt_lesson` (source: her decision's run, scope: the
  film's kind, provisional) only where a picture or motion prompt can act on them
  (`teachable_lessons`), and are confirmed once a later QC passes their scenes
  (`confirm_lessons`); a REPAIR carried on after a wait is read again under these rules
  (`resume_repairs`).

Nothing here buys, calls a vendor or answers in the Owner's name: a REPAIR is bought by
`runbook.stages._apply_repairs`, through `assembler.redo_scene` (unasked, under his rule).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role
from app.agents.messages import is_for_owner, post_message, resolve_message
from app.agents.models import AgentMessage
from app.agents.reviews import (
    FILM_LEVEL_REDOS,
    PAID_REDOS,
    DirectorRedo,
    _names_scene,
    check_family,
    measured_by_detector,
    measured_serious,
    prompt_actionable,
    redo_refusal,
    scenes_named,
    settled_checks,
    vendor_fallback,
)
from app.db import lock_for_write
from app.factual.models import ScriptDraft
from app.media.models import (
    QualityControlReport,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.qc_report import CARD_KINDS, LIVE, PUBLISH_SCORE, RedoProposal
from app.models import DomainEvent
from app.services import append_event, utc_now
from app.wording import count, sentence

logger = logging.getLogger("studio.media.director_qc")

#: Her decision on one report, with every verdict and what came of it (aggregate: the report).
DECISION_EVENT = "media.director_qc_decision"
#: She was asked and could not decide (no model, an unusable answer): nothing was redone.
WAITING_EVENT = "media.director_qc_waiting"
#: The Owner's STATUS letter about her decision.
LETTER_KIND = "owner_director_qc"
#: The note in her inbox while a report waits for her.
INBOX_KIND = "director_qc_waiting"
#: Who decided, in the events and the PASSED report.
DIRECTOR = "Director"
#: `SceneTake.approved_by` and ``decided_by`` of his own look at a take (`assembler.TAKE_DECIDER`,
#: `shooting_sheet.OWNER`, `rehearsal.OWNER`).
OWNER = "owner"

#: A REPAIR whose carrying out waits on something outside her (2026-10-10 review): his answer
#: to the paid question (ASKED), or a take bought for her list that is not in a film yet
#: (BOUGHT_WAITING: a new still waiting for the vendor or the gate's verdict, candidates the gate
#: refused waiting for her own look, motion refused after its new still). Her decision stands
#: while it waits: the walk carries on what is left of her list once the wait is over
#: (`decision_state` ``ready``), and puts the report before her again once it lapsed (his no,
#: an expired question, his look or hers rejecting what was bought).
PENDING_OUTCOMES = frozenset({"ASKED", "BOUGHT_WAITING"})
#: How long a BOUGHT_WAITING decision waits for what cannot come by itself: refused candidates
#: nobody could look at (no model of the studio sees), or a film that could not be rejoined
#: from an approved take bought for her list. After it the report is hers again, so a film is
#: never left waiting for a look nobody gives (2026-10-10 review).
BOUGHT_WAIT_DAYS = 3
#: Her look at the candidates bought for her REPAIR that the stills gate or the clip QC refused
#: (aggregate: the report): what she was shown, what was not offered to her and why, the one
#: she chose or that she rejected them all, and her reason.
LOOK_EVENT = "media.director_take_look"
#: The Owner's STATUS letter about one look of hers.
LOOK_LETTER_KIND = "owner_director_look"
#: `SceneTake.approved_by` of a take she chose by looking. Never his "owner": «nobody retires a
#: take he approved» means his own approvals (`owner_approved_take_ids`,
#: `assembler.owner_approved_among`), and his later look at the take (`assembler.decide_take`)
#: replaces hers.
DIRECTOR_APPROVER = "director"
#: The most candidates one look shows her, newest first; older ones count as seen.
LOOK_MAX_CANDIDATES = 6
#: The words of the stills gate's degenerate check (`still_gate.local_checks`): no picture.
_NO_PICTURE_WORDS = "Imaginea nu e o imagine"
#: The outcomes that end her work on a report (the pending ones while they stand): the
#: watchdog does not ask her about it again. NOTHING_DONE (a repair of which nothing could be
#: carried out) is not one of them.
FINAL_OUTCOMES = frozenset({"ACCEPTED", "ACCEPT_REFUSED", "REPAIRED", "CLOSED"}) | PENDING_OUTCOMES

#: Checks that are not hers to accept away: the rights (facts about his accounts), the factual
#: claims (sources), placeholder visuals (no real footage), and how the film was made (his
#: production rule: template prompts in PRODUCTION, a film bought whole on the old render
#: path; «nu se publică» is his rule, not a measurement she may overrule).
NOT_YOURS_CHECKS = frozenset({"rights_qc", "factual_qc", "content_source_qc", "production_path_qc"})
#: The technical failures that say the file is not the one recorded, or was never measured.
_FILE_FAULTS = (
    "Rendered video file missing",
    "Provenance digest",
    "File is not a decodable video",
    "ffprobe is not installed",
)
#: Findings of a check that is otherwise hers which state a licence fact about his account:
#: `qc.audio_mix_verdict`'s «Piesa „…” din film nu este în biblioteca de muzică a
#: Proprietarului …» and «… nu este fișierul licențiat (sha256 diferit)». The publishing gate
#: never reads the music library again (its rights gate reads only the film's licence status),
#: so a PASSED report of hers would publish an unlicensed track (2026-10-10 review). The same
#: check's loudness findings («Muzica stă la …», «Nivelul muzicii …») stay hers.
_LICENCE_PREFIXES = ("Piesa „",)
#: What a finding's words say about its check, for the reasons `evaluate_media_qc` writes.
_PREFIX_CHECKS: tuple[tuple[str, str], ...] = (
    ("Captions", "captions_qc"),
    ("Motion QC", "motion_qc"),
    ("Montaj", "editorial_qc"),
    ("Measured loudness", "audio_qc"),
    ("Measured true peak", "audio_qc"),
    ("Loudness could not", "audio_qc"),
    ("The film has no audio stream", "audio_qc"),
    ("ffmpeg with loudnorm", "audio_qc"),
    ("Invalid license", "rights_qc"),
    ("Claim", "factual_qc"),
    ("Visuals are locally generated placeholder", "content_source_qc"),
    ("Measured aspect ratio", "technical_qc"),
    ("Declared resolution", "technical_qc"),
    ("Durata măsurată", "technical_qc"),
    *((fault, "technical_qc") for fault in _FILE_FAULTS),
    *((prefix, "audio_mix_qc") for prefix in _LICENCE_PREFIXES),
    ("Muzica stă la", "audio_mix_qc"),
    ("Nivelul muzicii", "audio_mix_qc"),
    ("Filmul a fost cumpărat întreg pe calea veche", "production_path_qc"),
)
#: Words inside a finding that name its check when no prefix does: the production path's
#: «Scena 3 a fost filmată din prompturi-șablon …» names a scene but is not a picture finding.
_CONTAINED_CHECKS: tuple[tuple[str, str], ...] = (
    ("prompturi-șablon", "production_path_qc"),
    ("calea veche de randare", "production_path_qc"),
    # The one-frame look's and the character check's own words (`picture_qc.evaluate_pictures`
    # writes them to the report, not to its check's record). 2026-10-12: read by their scene
    # they were filed under the span look, or under no check, and «Controlul «picture_qc» a
    # picat» was added beside them with no scene, which she marked REAL every time.
    ("the frame is not a picture", "picture_qc"),
    ("the frame is not one picture", "picture_qc"),
    ("the picture is not what the scene asked for", "picture_qc"),
    ("the look gave no verdict for this scene", "picture_qc"),
    ("is not the character the bible describes", "character_drift_qc"),
)


def is_not_yours(text: str, check: str | None) -> bool:
    """Whether a finding is not hers to accept away: its check is his or the sources' to
    settle (`NOT_YOURS_CHECKS`), it states a licence fact about his music library, or it says
    the file is not the one recorded."""
    stripped = text.strip()
    if check in NOT_YOURS_CHECKS:
        return True
    if any(stripped.startswith(fault) for fault in _FILE_FAULTS):
        return True
    return any(stripped.startswith(prefix) for prefix in _LICENCE_PREFIXES)


#: Checks with per-scene entries, in the order a "Scena N: ..." finding is matched against.
_SCENE_CHECKS = (
    "picture_spans_qc",
    "picture_qc",
    "character_drift_qc",
    "content_integrity_qc",
    "motion_qc",
)
_SCENE_PREFIX = re.compile(r"^\s*scen[ae]\s+(\d+)\s*:", re.IGNORECASE)
_SCENE_ANYWHERE = re.compile(r"\bscen[ae]\s+(\d+)\b", re.IGNORECASE)

#: Her verdicts and decisions, in the Owner's words.
VERDICT_RO = {
    "REAL": "real, de refăcut",
    "FALSE": "fals, controlul a citit greșit filmul",
    "OWNER_CHOICE": "alegerea ta, rămâne cum ai aprobat-o",
    "ACCEPTED": "real, dar acceptat așa cum este",
}
#: How bad she judged a REAL or ACCEPTED defect (2026-10-12), in the Owner's words.
SEVERITY_RO = {"minor": "defect mic", "serious": "defect serios"}
#: Her lessons are stored as provisional prompt lessons by the run of her decision, scoped to
#: the kind of film (`prompt_agent.record_prompt_lesson`: it refuses a lesson naming a scene
#: or a title, and a newer lesson that says the same supersedes the older); they are
#: confirmed once a later film QC of the storyboard passes the scenes they were about
#: (`confirm_lessons`). The review of 2026-10-12 dropped a private word-overlap of their own.
LESSON_SCOPES = ("serial", "factual")
DECISION_RO = {
    "ACCEPT": "filmul se publică așa cum este",
    "REPAIR": "se refac doar scenele pe care le-a numit",
    "CLOSE": "filmul se închide",
}
REDO_RO = {
    "still": "imaginea",
    "motion": "mișcarea",
    "card": "cardul",
    "audio": "sunetul",
    "encode": "codarea",
    "rejoin": "filmul reasamblat din preluări",
}
CAPTIONS_BURNED_NOTE = (
    "The studio burns its own subtitles of the narration into the finished film: words on screen "
    "that are the narration are the studio's captions, not text or a logo in the picture."
)
CAPTIONS_NOT_BURNED_NOTE = (
    "This film's captions were not burned into the picture: text on screen is not the studio's "
    "subtitles."
)
MONEY_NOTE = (
    "Paid redos (still, motion) are bought only under the Owner's paid-media rule, inside his "
    "caps and limits; above his rule he is asked. Card, audio and encode cost nothing and are "
    "done once per film."
)


# ------------------------------------------------------------------------------- reading


def _payload(event: DomainEvent) -> dict[str, Any]:
    return dict(event.payload) if isinstance(event.payload, dict) else {}


def _short(text: Any, limit: int = 300) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _scene_of(entry: Mapping[str, Any]) -> int | None:
    for key in ("scene_index", "scene"):
        value = entry.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _failed_entries(check: Any) -> list[Mapping[str, Any]]:
    if not isinstance(check, Mapping):
        return []
    entries: list[Mapping[str, Any]] = []
    for key in ("scenes", "clips"):
        value = check.get(key)
        if isinstance(value, list):
            entries += [
                item
                for item in value
                if isinstance(item, Mapping)
                and (item.get("passed") is False or item.get("status") == "FAILED")
            ]
    return entries


def _listed(check: Mapping[str, Any]) -> list[str]:
    return [
        str(item)
        for key in ("failures", "reasons_ro", "problems")
        if isinstance(check.get(key), list)
        for item in check.get(key) or []
    ]


def _check_of(text: str, scene: int | None, checks: Mapping[str, Any]) -> str | None:
    """Which check wrote a finding: a check that lists these very words first, then its words
    (the reasons `evaluate_media_qc` writes), then a check whose failing entry for that scene
    says it, then the lists a check keeps. The exact listing comes before the scene: the
    production path's «Scena 3 a fost filmată din prompturi-șablon» names a scene, and read by
    its scene it was taken for a picture finding of hers (2026-10-10 review)."""
    stripped = text.strip()
    for name, check in checks.items():
        if isinstance(check, Mapping) and stripped in (item.strip() for item in _listed(check)):
            return str(name)
    for prefix, name in _PREFIX_CHECKS:
        if stripped.startswith(prefix):
            return name
    for words, name in _CONTAINED_CHECKS:
        if words in stripped:
            return name
    if scene is not None:
        rest = _SCENE_PREFIX.sub("", stripped).strip().lower()
        candidates = [name for name in _SCENE_CHECKS if name in checks]
        for name in candidates:
            for entry in _failed_entries(checks.get(name)):
                if _scene_of(entry) != scene:
                    continue
                said = " ".join(
                    str(value)
                    for value in (entry.get("reason"), entry.get("detail_ro"), entry.get("detail"))
                    if value
                ).lower()
                if rest and rest[:40] in said:
                    return name
        for name in candidates:
            if any(_scene_of(entry) == scene for entry in _failed_entries(checks.get(name))):
                return name
    for name, check in checks.items():
        if not isinstance(check, Mapping):
            continue
        if any(item and (item in stripped or stripped in item) for item in _listed(check)):
            return str(name)
    return None


def _failing_scenes(check: Any, name: str) -> list[int]:
    """The scenes a check's own record says it failed: its failing entries, the one-frame look's
    scenes with a «no» among its answers, the character check's people who did not match."""
    scenes = {_scene_of(entry) for entry in _failed_entries(check)}
    if isinstance(check, Mapping) and name == "picture_qc":
        scenes |= {
            _scene_of(entry)
            for entry in check.get("scenes") or []
            if isinstance(entry, Mapping)
            and any(
                entry.get(key) is False
                for key in ("is_a_picture", "one_picture", "shows_the_scene")
            )
        }
    if isinstance(check, Mapping) and name == "character_drift_qc":
        scenes |= {
            _scene_of(person)
            for person in check.get("characters") or []
            if isinstance(person, Mapping)
            and person.get("status") == "MEASURED"
            and person.get("matches") is False
        }
    return sorted(scene for scene in scenes if scene is not None)


def report_findings(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every finding of a failed report, numbered from 1 in the report's own order: its words,
    its check, its scene, the scenes its words name (``scenes``: its own and those named with an
    explicit scene word, `reviews.scenes_named`), the serious class quality control measured in
    it (``measured_serious``, `reviews.measured_serious`), and whether it is hers to judge
    (``not_yours``). A check that failed with no words of its own becomes «Controlul «X» a
    picat», marked ``check_level`` with the scenes its record failed (``scenes_of_check``): it
    says nothing a scene's finding does not (2026-10-12 review)."""
    checks = report.get("checks_json") or {}
    checks = dict(checks) if isinstance(checks, Mapping) else {}
    reasons = [str(item) for item in report.get("failure_reasons_json") or [] if str(item).strip()]
    findings: list[dict[str, Any]] = []
    for text in reasons:
        match = _SCENE_PREFIX.match(text) or _SCENE_ANYWHERE.search(text)
        scene = int(match.group(1)) if match else None
        check = _check_of(text, scene, checks)
        words = " ".join(text.split())
        findings.append(
            {
                "id": len(findings) + 1,
                "text": words,
                "check": check,
                "scene_index": scene,
                "scenes": sorted(scenes_named(words, own=scene)),
                "measured_serious": measured_serious(words),
                # YuNet or the flat band: read again on every film, never settled (round 3).
                "detector": measured_by_detector(words),
                "not_yours": is_not_yours(text, check),
            }
        )
    named = {item["check"] for item in findings}
    for name, check in sorted(checks.items()):
        # A check that failed and wrote no reason of its own still needs her verdict.
        if isinstance(check, Mapping) and check.get("passed") is False and name not in named:
            detail = check.get("detail") or check.get("reason_ro") or check.get("warning")
            findings.append(
                {
                    "id": len(findings) + 1,
                    "text": " ".join(
                        (f"Controlul «{name}» a picat" + (f": {detail}" if detail else "")).split()
                    ),
                    "check": name,
                    "scene_index": None,
                    "scenes": [],
                    "measured_serious": None,
                    "not_yours": name in NOT_YOURS_CHECKS,
                    "check_level": True,
                    "scenes_of_check": _failing_scenes(check, str(name)),
                }
            )
    if not findings:
        findings.append(
            {
                "id": 1,
                "text": "Raportul a picat fără un motiv scris.",
                "check": None,
                "scene_index": None,
                "not_yours": False,
            }
        )
    return findings


def sound_reading(production: Mapping[str, Any]) -> dict[str, Any] | None:
    """The film's sound as she reads it before deciding an audio redo (2026-10-11): the plan
    (who made it, the bed, each scene's level and ambience, the fades), the measured level of
    the bed under the voice where the words are, in the gaps and over the film, and every time
    the plan was asked again after a refusal. None for a film mixed before plans existed."""
    audio = production.get("audio") if isinstance(production.get("audio"), Mapping) else None
    if not audio:
        return None
    plan = audio.get("plan") if isinstance(audio.get("plan"), Mapping) else None
    bed = audio.get("bed") if isinstance(audio.get("bed"), Mapping) else {}
    if plan is None and not bed:
        return None
    reading: dict[str, Any] = {
        "plan": (
            {
                "source": plan.get("source"),
                "by": plan.get("by"),
                "reason": _short(plan.get("reason"), 200) or None,
                "bed": plan.get("bed"),
                "why": _short(plan.get("why"), 300),
                "scenes": [
                    {
                        "scene_index": item.get("scene_index"),
                        "level": item.get("level"),
                        "ambience": item.get("ambience"),
                        "why": _short(item.get("why"), 160),
                    }
                    for item in plan.get("scenes") or []
                    if isinstance(item, Mapping)
                ][:60],
                "fade_in_seconds": plan.get("fade_in_seconds"),
                "fade_out_seconds": plan.get("fade_out_seconds"),
                "summary_ro": _short(plan.get("summary_ro"), 400),
            }
            if plan is not None
            else None
        ),
        "measured": {
            "bed": bed.get("track_id"),
            "lu_under_voice_in_speech": bed.get("measured_lu_under_voice_in_speech"),
            "lu_under_voice_in_gaps": bed.get("measured_lu_under_voice_in_gaps"),
            "lu_under_voice_film": bed.get("measured_lu_under_voice"),
            "target_lu_under_voice": bed.get("target_lu_under_voice"),
            "accepted_band_lu": [18, 22],
            "lifted_seconds": bed.get("lifted_seconds"),
            "lift_spans": bed.get("lift_spans"),
            "speech_seconds": bed.get("speech_seconds"),
            "gap_seconds": bed.get("gap_seconds"),
        }
        if bed
        else None,
        "replans": [
            {
                "at": item.get("at"),
                "asked_by": _short(item.get("asked_by"), 160),
                "reasons": [_short(reason, 200) for reason in item.get("reasons") or []][:4],
                "changed": [_short(change, 120) for change in item.get("changed") or []][:12],
                "source": item.get("source"),
                "reason": _short(item.get("reason"), 200) or None,
            }
            for item in (audio.get("replans") or [])[-4:]
            if isinstance(item, Mapping)
        ],
        "advisory": _short(audio.get("advisory"), 300) or None,
        "warning": _short(audio.get("warning"), 300) or None,
    }
    return reading


def _compact_checks(checks: Mapping[str, Any]) -> dict[str, Any]:
    """Each check as she needs it: passed or not, what it says, and its failing scenes."""
    out: dict[str, Any] = {}
    for name, check in checks.items():
        if not isinstance(check, Mapping):
            continue
        entry: dict[str, Any] = {"passed": check.get("passed")}
        for key in ("status", "detail", "reason_ro", "warning", "burned_in", "environment"):
            if check.get(key) not in (None, "", [], {}):
                entry[key] = _short(check.get(key), 300)
        failing = [
            {
                "scene_index": _scene_of(item),
                "reason": _short(item.get("reason") or item.get("detail_ro"), 300),
            }
            for item in _failed_entries(check)
        ]
        if failing:
            entry["failing_scenes"] = failing[:12]
        out[str(name)] = entry
    return out


def owner_approved_take_ids(
    session: Session, storyboard_id: str, *, final_only: bool = False
) -> set[str]:
    """The film's takes the Owner approved himself: ``approved_by`` "owner" (kept on a take a
    redo retired since), or his newest look at the take (`media.scene_take_decided`) APPROVED.

    ``final_only``: only the takes his newest look approved as final (`decide_take`
    ``final``; 2026-10-11, his card): what no repair of the Director's retires. An approval
    with no look of his on record (an adopted take) is not a final one."""
    from app.media.assembler import TAKE_DECIDED_EVENT  # noqa: PLC0415 - a large module

    approved: set[str] = set()
    if not final_only:
        approved = set(
            session.scalars(
                select(SceneTake.id).where(
                    SceneTake.storyboard_id == storyboard_id, SceneTake.approved_by == OWNER
                )
            )
        )
    looks: dict[str, tuple[str, bool]] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == TAKE_DECIDED_EVENT)
        .order_by(DomainEvent.sequence)
    ):
        payload = _payload(event)
        if str(payload.get("storyboard_id") or "") != storyboard_id:
            continue
        if str(payload.get("decided_by") or "").lower() != OWNER:
            continue
        looks[str(event.aggregate_id)] = (
            str(payload.get("decision") or ""),
            bool(payload.get("final")),
        )
    approved |= {
        take
        for take, (decision, final) in looks.items()
        if decision == "APPROVED" and (final or not final_only)
    }
    approved -= {take for take, (decision, _final) in looks.items() if decision == "REJECTED"}
    return approved


def film_takes(production: Mapping[str, Any]) -> dict[int, dict[str, str | None]]:
    """Per scene, the still and the shot the film was cut from (its render record)."""
    takes: dict[int, dict[str, str | None]] = {}
    for scene in production.get("scenes") or []:
        if not isinstance(scene, Mapping) or _scene_of(scene) is None:
            continue
        still = scene.get("still_take") if isinstance(scene.get("still_take"), Mapping) else {}
        motion = scene.get("motion") if isinstance(scene.get("motion"), Mapping) else {}
        takes[int(_scene_of(scene) or 0)] = {
            "still": str(still.get("take_id")) if still and still.get("take_id") else None,
            "motion": str(motion.get("take_id")) if motion and motion.get("take_id") else None,
        }
    return takes


def _take_notes(
    session: Session, in_film: Mapping[int, Mapping[str, str | None]]
) -> dict[int, dict[str, Any]]:
    """Per scene, what was accepted on the takes the film was cut from before they were filmed
    (`fix_check.take_note`: the small traces a look saw and let through, and the Director's look
    that approved a take). The review of 2026-10-12, round 3: the film QC context did not read
    them, and the same small trace accepted on the still came back as a finding after the
    money. Read only; a scene with no note is left out."""
    try:
        from app.media.fix_check import take_note  # noqa: PLC0415 - a large module
    except ImportError:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for scene, takes in in_film.items():
        found: dict[str, Any] = {}
        for layer, take_id in takes.items():
            note = take_note(session, str(take_id)) if take_id else None
            if not note:
                continue
            minor = [
                {
                    "finding": _short(item.get("finding"), 200),
                    "seen": _short(item.get("seen"), 200),
                }
                for item in note.get("minor") or []
                if isinstance(item, Mapping)
            ][:6]
            said = note.get("director_look")
            look = said if isinstance(said, Mapping) else None
            if not minor and not look:
                continue
            found[layer] = {
                "approved_by": note.get("approved_by"),
                **({"minor_traces_accepted": minor} if minor else {}),
                **(
                    {
                        "director_look": {
                            "verdict": look.get("verdict"),
                            "severity": look.get("severity"),
                            "reason": _short(look.get("reason_ro"), 300),
                        }
                    }
                    if look
                    else {}
                ),
            }
        if found:
            out[int(scene)] = found
    return out


def protected_redos(
    session: Session,
    storyboard_id: str,
    production: Mapping[str, Any],
    *,
    final_only: bool = True,
) -> dict[int, dict[str, list[str]]]:
    """Per scene and redo kind, the takes the Owner approved (``final_only``, the default: as
    final, which no repair of the Director's retires, 2026-10-11) that the redo would take from
    the film or retire: a still redo retires the scene's stills and every shot filmed from
    them, a motion redo its shots. The film's own takes count whatever their status now
    (babcf272's were retired by the mechanical repair), and so do the scene's current ones."""
    from app.media.assembler import (  # noqa: PLC0415 - a large module
        REUSABLE_TAKE_STATUSES,
        SHOT_TAKE_KINDS,
    )

    his = owner_approved_take_ids(session, storyboard_id, final_only=final_only)
    in_film = film_takes(production)
    stills: dict[int, set[str]] = {}
    shots: dict[int, set[str]] = {}
    for scene, takes in in_film.items():
        if takes["still"]:
            stills.setdefault(scene, set()).add(takes["still"])
        if takes["motion"]:
            shots.setdefault(scene, set()).add(takes["motion"])
    for take in session.scalars(
        select(SceneTake).where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.status.in_(REUSABLE_TAKE_STATUSES),
        )
    ):
        into = shots if take.kind in SHOT_TAKE_KINDS else stills if take.kind == "still" else None
        if into is not None:
            into.setdefault(int(take.scene_number), set()).add(str(take.id))
    out: dict[int, dict[str, list[str]]] = {}
    for scene in sorted(set(stills) | set(shots)):
        own_shots = shots.get(scene, set()) & his
        out[scene] = {
            "still": sorted((stills.get(scene, set()) & his) | own_shots),
            "motion": sorted(own_shots),
        }
    return out


def owner_scene_choices(session: Session, storyboard_id: str) -> dict[int, str]:
    """His own choice of a model for a scene on the sheet (the newest per scene), and the
    scenes he chose to show as a locally animated still."""
    from app.media.production_policy import LOCAL_MOVE  # noqa: PLC0415
    from app.media.qc import owner_local_moves  # noqa: PLC0415 - a large module
    from app.media.shooting_sheet import SCENE_MODEL_EVENT  # noqa: PLC0415 - it imports runbook

    chosen: dict[int, str] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == SCENE_MODEL_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        payload = _payload(event)
        scene = payload.get("scene_index")
        if isinstance(scene, int) and str(payload.get("decided_by") or "").lower() == OWNER:
            chosen[scene] = str(payload.get("model_id") or "auto")
    for scene in owner_local_moves(session, storyboard_id):
        chosen[int(scene)] = LOCAL_MOVE
    return chosen


def _take_view(
    row: SceneTake | None, his: set[str], take_id: str | None, final: set[str] | None = None
) -> dict[str, Any] | None:
    if take_id is None:
        return None
    marks = {"approved_by_owner": take_id in his, "owner_approval_final": take_id in (final or ())}
    if row is None:
        return {"take_id": take_id, "status": "UNKNOWN", **marks}
    return {
        "take_id": row.id,
        "kind": row.kind,
        "status": row.status,
        "approved_by": row.approved_by,
        **marks,
        "failure_code": row.failure_code,
    }


def _not_final(
    approved: Mapping[str, list[str]], final: Mapping[str, list[str]]
) -> dict[str, list[str]]:
    """Per redo kind, the takes he approved without marking them final: what her confirmed
    repair may replace (he is told). Empty kinds are left out."""
    out: dict[str, list[str]] = {}
    for redo, ids_ in approved.items():
        kept = [take for take in ids_ if take not in (final.get(redo) or [])]
        if kept:
            out[redo] = kept
    return out


def decisions_of_film(session: Session, storyboard_id: str) -> list[dict[str, Any]]:
    """Her decisions on the film's reports, oldest first (their payloads, with ``at``)."""
    out: list[dict[str, Any]] = []
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == DECISION_EVENT)
        .order_by(DomainEvent.sequence)
    ):
        payload = _payload(event)
        if str(payload.get("storyboard_id") or "") == storyboard_id:
            out.append({**payload, "at": event.timestamp, "event_id": event.event_id})
    return out


def _done_of(item: Mapping[str, Any]) -> Mapping[str, Any]:
    done = item.get("done")
    return done if isinstance(done, Mapping) else {}


def _asked_ids(item: Mapping[str, Any]) -> list[str]:
    return [
        str(entry["approval_id"])
        for entry in _done_of(item).get("asked") or []
        if isinstance(entry, Mapping) and entry.get("approval_id")
    ]


def _earlier(session: Session, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Her last decisions on the film, as she needs them to decide again: what she found and
    listed, and what came of it — skipped, refused, stopped by his limits (``limited``: a REPAIR
    of only those scenes can do nothing now, 2026-10-10 review), bought, and his answer to each
    paid question it raised (``owner_answers``: a no puts the report before her again)."""
    from app.services import approval_answers  # noqa: PLC0415 - his answers, read only

    out: list[dict[str, Any]] = []
    for item in decisions[-4:]:
        done = _done_of(item)
        asked = _asked_ids(item)
        found = approval_answers(session, asked)
        answers = [
            {
                "approval_id": approval_id,
                "result": found[approval_id]["result"],
                "expired": found[approval_id]["result"] == "PENDING"
                and str(found[approval_id]["expires_at"]) <= utc_now(),
                "note": _short(found[approval_id]["note"], 200) or None,
            }
            for approval_id in asked
            if approval_id in found
        ]
        out.append(
            {
                "report_id": item.get("report_id"),
                "at": item.get("at"),
                "decision": item.get("decision"),
                "outcome": item.get("outcome"),
                "summary": _short(item.get("summary"), 300),
                "verdicts": [
                    {
                        "text": _short(verdict.get("text"), 140),
                        "verdict": verdict.get("verdict"),
                        "reason": _short(verdict.get("reason"), 160),
                        **(
                            {"severity": verdict.get("severity")} if verdict.get("severity") else {}
                        ),
                    }
                    for verdict in (item.get("verdicts") or [])[:20]
                    if isinstance(verdict, Mapping)
                ],
                "repairs": item.get("repairs") or [],
                "bought": [
                    {"redo": entry.get("redo"), "scene_index": entry.get("scene_index")}
                    for entry in done.get("bought") or []
                    if isinstance(entry, Mapping)
                ],
                "skipped": [
                    _short(entry.get("reason"), 200)
                    for entry in done.get("skipped") or []
                    if isinstance(entry, Mapping)
                ],
                "refused": [
                    _short(entry.get("reason"), 200)
                    for entry in done.get("refused") or []
                    if isinstance(entry, Mapping)
                ],
                "limited": [
                    {
                        "scene_index": entry.get("scene_index"),
                        "per_scene": entry.get("per_scene"),
                        "per_film": entry.get("per_film"),
                    }
                    for entry in done.get("limited") or []
                    if isinstance(entry, Mapping)
                ],
                # Her second looks that overturned a refusal before a purchase: nothing was
                # bought for those scenes (the review of 2026-10-12, round 3: they were not
                # shown to her, and she marked the same findings REAL every hour).
                "overturned": [
                    {
                        "scene_index": entry.get("scene_index"),
                        "checks": list(entry.get("checks") or []),
                        "severity": entry.get("severity"),
                        "reason": _short(entry.get("reason"), 200),
                    }
                    for entry in done.get("overturned") or []
                    if isinstance(entry, Mapping)
                ],
                "owner_answers": answers,
            }
        )
    return out


def _diagnosis_of(session: Session, report_id: str) -> dict[str, Any] | None:
    """The Video Editor's newest diagnosis of this report (`review_failed_render`'s letter)."""
    editor = agent_for_role(session, "VideoEditor")
    if editor is None:
        return None
    for message in session.scalars(
        select(AgentMessage)
        .where(AgentMessage.from_agent_id == editor.id, AgentMessage.intent == "ESCALATE")
        .order_by(AgentMessage.created_at.desc())
        .limit(40)
    ):
        body = message.body_json if isinstance(message.body_json, dict) else {}
        if str(body.get("report_id") or "") == report_id:
            return {
                "by": editor.display_name,
                "diagnosis": _short(body.get("diagnosis"), 600),
                "correction": _short(body.get("correction"), 600),
                "model_correction": _short(body.get("model_correction"), 400),
            }
    return None


def _failing_now(findings: Iterable[Mapping[str, Any]], index: int) -> list[str]:
    """The checks failing scene ``index`` in this report, by family (`reviews.check_family`):
    every finding about the scene (its own, or named with a scene word) but a whole check's «a
    picat». A finding no check claimed is «unattributed», which nothing ever settled."""
    failing: set[str] = set()
    for finding in findings:
        if finding.get("check_level") or not _names_scene(finding, index):
            continue
        failing.add(check_family(finding.get("check")) or "unattributed")
    return sorted(failing)


def film_qc_context(
    engine: Engine,
    reading: Mapping[str, Any],
    *,
    diagnosis: Mapping[str, Any] | None = None,
    limits: Mapping[str, Any] | None = None,
    free_used: bool = False,
) -> dict[str, Any]:
    """Everything the Director reads before she decides one failed report, as data.

    ``reading`` is `app.agents.reviews.failed_render_reading`'s; ``limits`` the paid redos his
    limits allow ({per_scene, per_film, spent: {scene: n}, open_motion: [scene]}: a scene whose
    new still was bought and whose motion was not yet may still have it, in the same round);
    ``free_used`` whether a free fix was already applied to this film's line (it is done
    once). A scene with an approved take bought for her earlier REPAIR and in no film yet
    (`bought_not_in_film`) says so (``approved_new_take_not_in_film``).

    What is settled about each scene's picture is said check by check (2026-10-12; the review
    of that day): ``passed_before`` names the picture checks that passed it in a report made
    before this one with exactly its carry key (the same takes, the check's version, the bible
    and look, the span and speed: `picture_qc.carry_keys`), ``accepted_before`` the checks whose
    findings on it she judged FALSE or accepted as minor, or her second look overturned, on
    exactly these takes (`picture_qc.earlier_acceptances`), ``failing_now`` the checks failing it
    in this report, and ``passed_before_unchanged`` that every one of them was settled before.
    aa170155's scene 1 passed three film QCs and failed the fourth with nothing changed, and her
    REPAIR bought a new still and clip for it: a finding of a settled check is never REAL, and a
    scene whose every failing check is settled is never redone (`reviews.passed_scene_refusal`).
    ``film.kind`` is «serial» for an episode of the office serial, else «factual»: the scope of
    the lessons she writes."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.media.picture_qc import (  # noqa: PLC0415 - shared render evidence
        CARRIED_CHECKS,
        earlier_acceptances,
        earlier_passes,
        film_scene_prompts,
        settle_family,
        storyboard_carry_keys,
    )

    report = reading.get("report") or {}
    report_id = str(reading.get("report_id") or "")
    storyboard_id = str(reading.get("storyboard_id") or "")
    production: Mapping[str, Any] = reading.get("production") or {}
    checks = report.get("checks_json") or {}
    findings = report_findings(report)
    # Every family a scene's finding belongs to now, beside the picture checks: her second
    # look settles any of them (the review of 2026-10-12, round 3: an overturned Motion QC or
    # unattributed finding was neither settled nor shown, and the film looped every hour).
    families = sorted(
        set(CARRIED_CHECKS)
        | {
            settle_family(finding.get("check"))
            for finding in findings
            if not finding.get("check_level")
            and (finding.get("scene_index") is not None or finding.get("scenes"))
        }
    )
    limits = dict(limits or {})
    per_scene = int(limits.get("per_scene") or 0)
    per_film = int(limits.get("per_film") or 0)
    spent = {int(k): int(v) for k, v in (limits.get("spent") or {}).items()}
    open_motion = {int(scene) for scene in limits.get("open_motion") or []}
    film_left = max(0, per_film - sum(spent.values()))
    from app.media.production_policy import LOCAL_MOVE  # noqa: PLC0415

    kinds = scene_kinds(reading.get("sheet"))
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id) if storyboard_id else None
        title = str(board.title if board is not None else storyboard_id[:8])
        bible = board.visual_bible_json if board is not None else None
        his = owner_approved_take_ids(session, storyboard_id) if storyboard_id else set()
        final_ids = (
            owner_approved_take_ids(session, storyboard_id, final_only=True)
            if storyboard_id
            else set()
        )
        choices = owner_scene_choices(session, storyboard_id) if storyboard_id else {}
        protected = protected_redos(session, storyboard_id, production) if storyboard_id else {}
        # His approvals he did not mark final: her confirmed repair may replace them, and he
        # is told (2026-10-11, his card).
        replaceable = (
            protected_redos(session, storyboard_id, production, final_only=False)
            if storyboard_id
            else {}
        )
        not_in_film = bought_not_in_film(session, storyboard_id) if storyboard_id else []
        script = session.get(ScriptDraft, board.script_draft_id) if board is not None else None
        film_kind = "serial" if is_serial_film(board, script) else "factual"
        # Approved stays approved (2026-10-12), check by check: what an earlier report passed
        # with exactly this picture, and what she settled on exactly these takes.
        this_report = session.get(QualityControlReport, report_id) if report_id else None
        passed_before: dict[str, dict[int, Any]] = {}
        accepted_before: dict[str, dict[int, Any]] = {}
        #: Per family, each scene's carry key now: her verdicts and second looks are recorded
        #: with it, and only exactly this picture is settled by them later (round 3).
        settle_keys: dict[str, dict[int, dict[str, Any]]] = {}
        if storyboard_id:
            for name in families:
                settle_keys[name] = storyboard_carry_keys(session, storyboard_id, production, name)
                accepted_before[name] = earlier_acceptances(
                    session, storyboard_id, production, name, settle_keys[name]
                )
            for name in CARRIED_CHECKS:
                passed_before[name] = earlier_passes(
                    session,
                    storyboard_id,
                    settle_keys[name],
                    name,
                    before=str(this_report.verified_at) if this_report is not None else None,
                    exclude_report_ids=[report_id],
                )
        in_film = film_takes(production)
        notes = _take_notes(session, in_film)
        ids = [take for takes in in_film.values() for take in takes.values() if take]
        rows = {
            row.id: row for row in session.scalars(select(SceneTake).where(SceneTake.id.in_(ids)))
        }
        scenes: list[dict[str, Any]] = []
        for scene in session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ):
            index = int(scene.scene_index)
            prompts = film_scene_prompts(session, production, scene)
            takes = in_film.get(index, {"still": None, "motion": None})
            kind = kinds.get(index) or str(scene.scene_kind or LIVE).upper()
            passed = {
                name: {
                    "report_id": found[index].report_id,
                    "verified_at": found[index].verified_at,
                    "note": found[index].note_ro,
                }
                for name, found in passed_before.items()
                if index in found
            }
            accepted = {
                name: {
                    "report_id": found[index].report_id,
                    "decided_at": found[index].decided_at,
                    "verdicts": list(found[index].verdicts),
                    "note": found[index].note_ro,
                }
                for name, found in accepted_before.items()
                if index in found
            }
            failing = _failing_now(findings, index)
            settled = settled_checks({"passed_before": passed, "accepted_before": accepted})
            # A face YuNet counted or a band the flat-band reading found on this scene now is
            # measured, never settled (round 3 of the 2026-10-12 review).
            detected = any(
                finding.get("detector")
                and not finding.get("check_level")
                and _names_scene(finding, index)
                for finding in findings
            )
            scenes.append(
                {
                    "scene_index": index,
                    "kind": kind,
                    "narration": _short(scene.voiceover_segment, 300),
                    "asked": prompts["still_prompt"],
                    "motion_requested": prompts["motion_prompt"],
                    "ending_frame": prompts["ending_frame"],
                    "prompt_sources": prompts["prompt_sources"],
                    "in_film": {
                        "still": _take_view(
                            rows.get(takes["still"] or ""), his, takes["still"], final_ids
                        ),
                        "motion": _take_view(
                            rows.get(takes["motion"] or ""), his, takes["motion"], final_ids
                        ),
                    },
                    "owner_choice_on_sheet": choices.get(index),
                    "owner_approved_would_be_retired_by": {
                        redo: list(ids_)
                        for redo, ids_ in (protected.get(index) or {}).items()
                        if ids_
                    },
                    "owner_approved_would_be_replaced_by": _not_final(
                        replaceable.get(index) or {}, protected.get(index) or {}
                    ),
                    "paid_redos_left": (
                        0
                        if kind in CARD_KINDS
                        else max(0, min(per_scene - spent.get(index, 0), film_left))
                    ),
                    # Its new still was bought and its motion not yet: the motion is the same
                    # round, possible whatever is left.
                    "motion_after_new_still": index in open_motion
                    and choices.get(index) != LOCAL_MOVE,
                    # Bought for her earlier REPAIR, approved, in no film yet: her REPAIR of
                    # this scene joins it into the film, nothing is bought again.
                    "approved_new_take_not_in_film": [
                        item["take_id"] for item in not_in_film if item["scene_index"] == index
                    ]
                    or None,
                    # Settled check by check with exactly this picture: a finding of such a
                    # check is never REAL, and a scene whose every failing check is settled is
                    # never redone (2026-10-12, the Owner: «picarea QC dacă deja a fost
                    # aprobată» is not allowed).
                    **({"passed_before": passed} if passed else {}),
                    **({"accepted_before": accepted} if accepted else {}),
                    # The small traces accepted on its takes before they were filmed, and her
                    # look that approved one (`fix_check.TAKE_NOTE_EVENT`, round 3).
                    **({"accepted_on_takes": notes[index]} if notes.get(index) else {}),
                    "failing_now": failing,
                    "passed_before_unchanged": bool(settled)
                    and set(failing) <= settled
                    and not detected,
                    "accepted_before_unchanged": bool(accepted),
                }
            )
        earlier = (
            _earlier(session, decisions_of_film(session, storyboard_id)) if storyboard_id else []
        )
        looks = looks_of_film(session, storyboard_id) if storyboard_id else []
        found = dict(diagnosis) if diagnosis else _diagnosis_of(session, report_id)
    captions = production.get("captions") if isinstance(production.get("captions"), dict) else {}
    burned = (captions or {}).get("burned_in")
    if found:
        found = {
            key: _short(value, 600)
            for key, value in found.items()
            if key in ("by", "diagnosis", "correction", "model_correction") and value
        }
    return {
        "film": {
            "title": title,
            "storyboard_id": storyboard_id,
            "asset_id": reading.get("media_asset_id"),
            "report_id": report_id,
            "status": report.get("status"),
            "score": report.get("score"),
            # The scope of the lessons she writes (`learn_from_decision`).
            "kind": film_kind,
        },
        "findings": findings,
        "scenes": scenes,
        "captions": {
            "burned_in": burned,
            "note": CAPTIONS_BURNED_NOTE if burned else CAPTIONS_NOT_BURNED_NOTE,
        },
        "visual_bible": bible or None,
        "paid_redo_limits": {
            "per_scene": per_scene,
            "per_film": per_film,
            "spent_by_scene": {str(k): v for k, v in sorted(spent.items())},
            "left_for_film": film_left,
        },
        "free_fix_already_used": bool(free_used),
        "money": MONEY_NOTE,
        "video_editor_diagnosis": found or None,
        # The film's sound: the plan it was mixed with, who made it, the bed measured under
        # the words and in the gaps, and every re-plan a refusal caused — so an audio redo of
        # hers is decided on the numbers, and a loop that repeats is in front of her.
        "sound": sound_reading(production),
        "earlier_reviews": earlier,
        # Her own looks at the pictures a gate refused: after she rejected them all, the
        # report is hers again with her reasons in front of her.
        "your_looks": looks,
        "checks": _compact_checks(checks if isinstance(checks, Mapping) else {}),
        "redo_proposals": [
            proposal.as_dict() if isinstance(proposal, RedoProposal) else dict(proposal)
            for proposal in reading.get("proposals") or []
        ],
        # The code's own bookkeeping, never shown to her (`reviews._director_payload`): each
        # scene's carry key per family, recorded on her verdicts (`annotate_verdicts`).
        "_settle_keys": settle_keys,
    }


def annotate_verdicts(
    verdicts: Iterable[Mapping[str, Any]], context: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Her verdicts with the finding each judges, and whether an OWNER_CHOICE rests on his
    approval of a take in the film or his choice on the sheet (``owner_choice_confirmed``); a
    REAL or ACCEPTED one keeps its severity, cause and lesson (2026-10-12). Each also keeps what
    the next reading needs (the review of 2026-10-12): whether the finding is a whole check's
    (``check_level``), the scenes it names, and whether a prompt can act on it
    (``teaches``: only then is its lesson stored, `learn_from_decision`)."""
    from app.media.picture_qc import settle_family  # noqa: PLC0415 - shared render evidence

    findings = {int(item["id"]): item for item in context.get("findings") or []}
    raw_keys = context.get("_settle_keys")
    keys = raw_keys if isinstance(raw_keys, Mapping) else {}
    owner_scenes: set[int] = set()
    for scene in context.get("scenes") or []:
        in_film = scene.get("in_film") or {}
        if scene.get("owner_choice_on_sheet") or any(
            isinstance(take, Mapping) and take.get("approved_by_owner") for take in in_film.values()
        ):
            owner_scenes.add(int(scene["scene_index"]))
    out: list[dict[str, Any]] = []
    for verdict in verdicts:
        finding = findings.get(int(verdict["finding"]), {})
        entry = {
            "finding": int(verdict["finding"]),
            "text": finding.get("text"),
            "check": finding.get("check"),
            "scene_index": finding.get("scene_index"),
            "scenes": list(finding.get("scenes") or []),
            "not_yours": bool(finding.get("not_yours")),
            "verdict": str(verdict["verdict"]),
            "reason": _short(verdict.get("reason"), 400),
        }
        if finding.get("check_level"):
            entry["check_level"] = True
            entry["scenes_of_check"] = list(finding.get("scenes_of_check") or [])
        if finding.get("measured_serious"):
            entry["measured_serious"] = finding.get("measured_serious")
        if finding.get("detector"):
            entry["detector"] = True
        scene = finding.get("scene_index")
        if isinstance(scene, int) and not finding.get("check_level"):
            # Exactly the picture she judged (round 3 of the 2026-10-12 review): only a later
            # film with this very carry key is settled by this verdict.
            key = (keys.get(settle_family(finding.get("check"))) or {}).get(scene)
            if key:
                entry["carry_key"] = dict(key)
        if entry["verdict"] in ("REAL", "ACCEPTED"):
            # How bad, why it appeared, and the rule a future prompt follows (2026-10-12).
            entry["severity"] = verdict.get("severity")
            entry["cause"] = _short(verdict.get("cause"), 400)
            entry["lesson"] = _short(verdict.get("lesson"), 240)
            entry["teaches"] = bool(finding) and prompt_actionable(finding, context)
        if entry["verdict"] == "OWNER_CHOICE":
            entry["owner_choice_confirmed"] = finding.get("scene_index") in owner_scenes
        out.append(entry)
    return sorted(out, key=lambda item: item["finding"])


# ------------------------------------------------------------------------------- deciding


def _picture_kinds(kind: str) -> tuple[str, ...]:
    """The take kinds a waiting entry reads: a still, a shot (motion, test shot), or either for
    the film rejoined from its takes (`REJOIN`)."""
    from app.media.assembler import SHOT_TAKE_KINDS  # noqa: PLC0415 - a large module

    if kind == "still":
        return ("still",)
    if kind == REJOIN:
        return ("still", *SHOT_TAKE_KINDS)
    return tuple(SHOT_TAKE_KINDS)


def _marks_since(
    session: Session, take_ids: Sequence[str], since: str, until: str | None = None
) -> dict[str, set[str]]:
    """What happened to these takes at or after ``since`` (and before ``until``, when given),
    from their history: a purchase wrote a candidate into the row (``recorded``), a redo that
    delivered nothing gave the take back as it was (``restored``), the Owner's look approved it
    (``approved``)."""
    from app.media.assembler import (  # noqa: PLC0415 - a large module
        TAKE_DECIDED_EVENT,
        TAKE_RECORDED_EVENT,
        TAKE_RESTORED_EVENT,
    )

    marks: dict[str, set[str]] = {"recorded": set(), "restored": set(), "approved": set()}
    if not take_ids:
        return marks
    before = (DomainEvent.timestamp < until,) if until else ()
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.aggregate_id.in_(list(dict.fromkeys(take_ids))),
            DomainEvent.event_type.in_(
                (TAKE_RECORDED_EVENT, TAKE_RESTORED_EVENT, TAKE_DECIDED_EVENT)
            ),
            DomainEvent.timestamp >= since,
            *before,
        )
    ):
        take_id = str(event.aggregate_id)
        if event.event_type == TAKE_RECORDED_EVENT:
            marks["recorded"].add(take_id)
        elif event.event_type == TAKE_RESTORED_EVENT:
            marks["restored"].add(take_id)
        else:
            payload = _payload(event)
            if (
                str(payload.get("decided_by") or "").lower() == OWNER
                and payload.get("decision") == "APPROVED"
            ):
                marks["approved"].add(take_id)
    return marks


def bought_since(
    session: Session,
    storyboard_id: str,
    scene: int,
    kind: str,
    since: str,
    until: str | None = None,
) -> list[SceneTake]:
    """The takes of the scene (`_picture_kinds` of ``kind``) a purchase wrote since ``since``,
    newest first: a row created since, or the row a candidate was written into since (the same
    file of the same words is one row, `assembler.record_take`: the staircase film's still redo
    wrote its candidates into the rows of the stills they replaced). A take given back since
    (`assembler.give_back_retired_takes`: the redo delivered nothing) is not one of them: it is
    the old picture, whatever its ``updated_at`` says (2026-10-10 review). ``until`` closes the
    window: what a later purchase wrote is not this one's (`runbook.stages._round_delivered`)."""
    rows = list(
        session.scalars(
            select(SceneTake)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene,
                SceneTake.kind.in_(_picture_kinds(kind)),
                SceneTake.updated_at >= since,
            )
            .order_by(SceneTake.updated_at.desc())
        )
    )
    marks = _marks_since(session, [row.id for row in rows], since, until)
    return [row for row in rows if _new_since(row, marks, since, approved=False, until=until)]


def _new_since(
    row: SceneTake,
    marks: Mapping[str, set[str]],
    since: str,
    *,
    approved: bool,
    until: str | None = None,
) -> bool:
    """Whether a take is new since ``since`` (and before ``until``, when given): created in the
    window; else (an older row) written into by a purchase in it, or (``approved``) approved by
    his look in it, and not given back since (a row that existed before and was given back is
    the old picture)."""
    if str(row.created_at) >= since:
        return until is None or str(row.created_at) < until
    if row.id in marks["restored"]:
        return False
    return row.id in marks["recorded"] or (approved and row.id in marks["approved"])


def new_approved_take(
    session: Session, storyboard_id: str, scene: int, kind: str, since: str
) -> str | None:
    """An APPROVED take of the scene (``kind`` "still", "motion" for a shot, or `REJOIN` for
    either) that is new since ``since`` (the moment her REPAIR began to be carried out): bought
    since (`bought_since`: the gate, a late delivery or his look approved it), or approved by
    his own look since. Read from the take's history, not by id: a still redo may write its
    candidate into the row of the still it replaces.

    A take that existed before and was given back since is never new (2026-10-10 review):
    `give_back_retired_takes` sets ``updated_at`` to the moment it gave babcf272's three-panel
    still back, after a redo whose every candidate was REFUSED (the GPU forced off), and the
    walk read it as the new still, rejoined the same film and told the Owner it was repaired
    «cu imaginea nouă»."""
    rows = list(
        session.scalars(
            select(SceneTake)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene,
                SceneTake.kind.in_(_picture_kinds(kind)),
                SceneTake.status == "APPROVED",
                SceneTake.updated_at >= since,
            )
            .order_by(SceneTake.updated_at.desc())
        )
    )
    marks = _marks_since(session, [row.id for row in rows], since)
    return next((str(row.id) for row in rows if _new_since(row, marks, since, approved=True)), None)


def _older_than(moment: Any, days: float) -> bool:
    """Whether ``moment`` (an ISO timestamp) lies more than ``days`` before now."""
    try:
        then = datetime.fromisoformat(str(moment))
        now = datetime.fromisoformat(utc_now())
    except ValueError:
        return False
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - then > timedelta(days=days)


def bought_not_in_film(session: Session, storyboard_id: str) -> list[dict[str, Any]]:
    """The approved takes bought for her earlier REPAIRs of this film that none of its films
    holds yet, one per (scene, kind), with the moment that REPAIR began ({scene_index, kind,
    take_id, since}). Her REPAIR of such a scene carries it on (the film rejoined from its
    takes, or its motion) and never buys it again: it is something she can still do when
    nothing else can be bought (2026-10-10 review: babcf272's new scene-5 still, approved, in no
    film because its rejoin was refused, left her prompt saying REPAIR was not possible, and
    she was steered to accept the three panels it replaced)."""
    in_films: set[str] = set()
    for production in session.scalars(
        select(VideoRenderJob.production_json).where(
            VideoRenderJob.storyboard_id == storyboard_id,
            VideoRenderJob.output_asset_id.is_not(None),
        )
    ):
        if isinstance(production, Mapping):
            for takes in film_takes(production).values():
                in_films.update(take for take in takes.values() if take)
    found: dict[tuple[int, str], dict[str, Any]] = {}
    for decided in decisions_of_film(session, storyboard_id):
        since = str(decided.get("started_at") or "")
        if not since:
            continue
        for pair in decided.get("bought_so_far") or []:
            if not isinstance(pair, list | tuple) or len(pair) != 2:
                continue
            kind, scene = str(pair[0]), pair[1]
            if kind not in ("still", "motion") or not isinstance(scene, int):
                continue
            if (scene, kind) in found:
                continue
            take = new_approved_take(session, storyboard_id, scene, kind, since)
            if take is not None and take not in in_films:
                found[(scene, kind)] = {
                    "scene_index": scene,
                    "kind": kind,
                    "take_id": take,
                    "since": since,
                }
    return [found[key] for key in sorted(found)]


def _asked_state(session: Session, decision: Mapping[str, Any]) -> str:
    """ASKED: ``ready`` (his yes waits to be spent), ``waiting`` (a question still open) or
    ``lapsed`` (every question refused, expired or spent with nothing after it)."""
    from app.services import approval_answers  # noqa: PLC0415 - his answers, read only

    ids = _asked_ids(decision)
    if not ids:
        # Nothing to read (a question without an id): carried on as before, and may_act
        # finds his answer or asks again.
        return "ready"
    present = list(approval_answers(session, ids).values())
    now = utc_now()
    if any(row["result"] == "APPROVED" and not row["consumed_at"] for row in present):
        return "ready"
    if any(row["result"] == "PENDING" and str(row["expires_at"]) > now for row in present):
        return "waiting"
    return "lapsed"


def _waiting_entries(decision: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """What a BOUGHT_WAITING decision waits for, one entry per (scene, kind)."""
    listed = decision.get("waiting_so_far")
    if not isinstance(listed, list):
        listed = _done_of(decision).get("waiting") or []
    return [
        entry
        for entry in listed
        if isinstance(entry, Mapping) and isinstance(entry.get("scene_index"), int)
    ]


def _looked_by_owner(session: Session, take_ids: Iterable[str]) -> set[str]:
    """The takes among these that his own look on the sheet decided (`decide_take`)."""
    from app.media.assembler import TAKE_DECIDED_EVENT  # noqa: PLC0415 - a large module

    ids = sorted(set(take_ids))
    if not ids:
        return set()
    return {
        str(event.aggregate_id)
        for event in session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == TAKE_DECIDED_EVENT, DomainEvent.aggregate_id.in_(ids)
            )
        )
        if str(_payload(event).get("decided_by") or "").lower() == OWNER
    }


def _her_looks(session: Session, report_id: str) -> list[dict[str, Any]]:
    """Her looks at the pictures bought for her REPAIRs of this report, oldest first."""
    return [
        {**_payload(event), "at": event.timestamp, "event_id": event.event_id}
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == LOOK_EVENT, DomainEvent.aggregate_id == report_id)
            .order_by(DomainEvent.sequence)
        )
    ]


def _owed_her_look(
    session: Session, candidates: Iterable[SceneTake], seen: set[str]
) -> list[SceneTake]:
    """The candidates that wait for her look: refused (by the stills gate or the clip QC),
    with their file on disk, and looked at by neither her nor him (his look decides them: it
    wins over hers)."""
    refused = [
        row
        for row in candidates
        if row.status == "REJECTED"
        and row.sha256
        and row.path
        and Path(str(row.path)).is_file()
        and row.id not in seen
    ]
    his = _looked_by_owner(session, (row.id for row in refused))
    return [row for row in refused if row.id not in his]


def _bought_state(session: Session, decision: Mapping[str, Any]) -> str:
    """BOUGHT_WAITING: ``ready`` (a take bought for her list is approved now, so what follows
    it can be carried out: its motion, or the film rejoined from its takes), ``look``
    (candidates the stills gate or the clip QC refused, on disk, wait for her own look:
    `look_entries`), ``waiting`` (something bought for it can still come: a candidate at the
    vendor or waiting for the gate's verdict) or ``lapsed`` (nothing waits: his look or hers
    rejected what was bought, every candidate came back refused or lost and the takes it
    replaced were given back, or what could not come by itself waited `BOUGHT_WAIT_DAYS`:
    refused candidates nobody could look at, a film that could not be rejoined).

    Refused candidates used to wait for his look («Decide Proprietarul»). The Owner, 2026-10-10:
    the Director decides whether the picture is good; his look on the sheet still wins.

    Only what was bought since the entry's moment is read (`bought_since`): the scene's older
    takes (a runner-up the stills step left PAID, the still a redo gave back) wait for nothing
    (2026-10-10 review: a REPAIR whose candidates were all REFUSED with the GPU forced off
    stood «waiting» for ever)."""
    storyboard_id = str(decision.get("storyboard_id") or "")
    entries = _waiting_entries(decision)
    if not storyboard_id or not entries:
        return "lapsed"
    seen = {
        str(take)
        for look in _her_looks(session, str(decision.get("report_id") or ""))
        for take in look.get("seen") or []
    }
    rank = {"lapsed": 0, "waiting": 1, "look": 2}
    state = "lapsed"
    for entry in entries:
        scene = int(entry["scene_index"])
        kind = str(entry.get("kind") or "still")
        since = str(entry.get("since") or decision.get("started_at") or "")
        if kind == REJOIN:
            # An approved take bought for her list that the film could not be rejoined with
            # yet: tried again with the watchdog's back-off, for `BOUGHT_WAIT_DAYS`.
            if not _older_than(
                entry.get("waiting_since") or since, BOUGHT_WAIT_DAYS
            ) and new_approved_take(session, storyboard_id, scene, REJOIN, since):
                return "ready"
            continue
        if new_approved_take(session, storyboard_id, scene, kind, since):
            return "ready"
        candidates = bought_since(session, storyboard_id, scene, kind, since)
        if any(row.status in ("SUBMITTED", "PAID") for row in candidates):
            found = "waiting"
        elif not _older_than(since, BOUGHT_WAIT_DAYS) and _owed_her_look(session, candidates, seen):
            found = "look"
        else:
            continue
        state = max(state, found, key=rank.__getitem__)
    return state


def decision_state(engine: Engine, report_id: str) -> dict[str, Any]:
    """Where her work on one report stands: ``final`` (an outcome that ends it, or a pending
    one that still stands), ``pending`` (her REPAIR waits on something outside her),
    ``ready`` (what it waited for came: the walk carries on what is left of her list without
    asking her again), ``look`` (candidates bought for it that a gate refused wait for her own
    look: the walk shows them to her, `look_entries`), ``lapsed`` (a pending REPAIR whose wait
    ended without it — his no, an expired question, his look or hers rejecting what was bought:
    the report is hers again, 2026-10-10 review: an ASKED she never heard back about stood
    «final» forever), the newest
    ``outcome`` and ``decision`` (its payload), ``tries`` (times nothing final came of asking
    her: every such round writes one `WAITING_EVENT`) and ``last_at``."""
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.event_type.in_((DECISION_EVENT, WAITING_EVENT)),
                    DomainEvent.aggregate_id == report_id,
                )
                .order_by(DomainEvent.sequence)
            )
        )
        newest = next((e for e in reversed(events) if e.event_type == DECISION_EVENT), None)
        decision = _payload(newest) if newest is not None else None
        outcome = decision.get("outcome") if decision else None
        stands = bool(decision and decision.get("final") and outcome in FINAL_OUTCOMES)
        wait = "none"
        if stands and decision is not None and newest is not None and outcome == "ASKED":
            wait = _asked_state(session, decision)
        elif stands and decision is not None and newest is not None and outcome == "BOUGHT_WAITING":
            wait = _bought_state(session, decision)
    tries = sum(1 for event in events if event.event_type == WAITING_EVENT)
    lapsed = wait == "lapsed"
    return {
        "final": stands and not lapsed,
        "pending": stands and outcome in PENDING_OUTCOMES and not lapsed,
        "ready": wait == "ready",
        "look": wait == "look",
        "lapsed": lapsed,
        "outcome": outcome,
        "decision": decision,
        "tries": tries,
        "last_at": events[-1].timestamp if events else None,
    }


def scene_kinds(sheet: Mapping[str, Any] | None) -> dict[int, str]:
    return {
        int(row["scene_index"]): str(row.get("kind") or LIVE).upper()
        for row in (sheet or {}).get("scenes") or []
        if isinstance(row, Mapping) and row.get("scene_index") is not None
    }


#: Not a redo she lists: the film rejoined from its takes once a take bought for her list is
#: approved (a new still of a scene he chose to animate locally, a shot that waited for his
#: look). 0 credits: nothing is bought, the narration already voiced is reused.
REJOIN = "rejoin"


def repair_list(
    repairs: Iterable[Mapping[str, Any]],
    *,
    kinds: Mapping[int, str],
    protected: Mapping[int, Mapping[str, list[str]]],
    proposals: Iterable[Any],
    free_used: bool,
    choices: Mapping[int, str] | None = None,
    already: Iterable[Sequence[Any]] = (),
) -> tuple[list[RedoProposal], list[dict[str, Any]]]:
    """Her list as the redo path takes it, and what of it is not carried out, with why.

    Only what she listed: a redo that would retire a take the Owner approved as final is
    skipped (``OWNER_APPROVED``; ``protected``, `protected_redos`: since 2026-10-11 an approval
    he did not mark final is replaced by her confirmed repair, and he is told); a free fix
    (card, audio, encode) on a film whose line already had
    one is skipped (``FREE_FIX_USED``: done once, never in a loop); a card redo of a filmed
    scene is skipped (``NOT_A_CARD``) and a still or motion redo of a card becomes its card.
    A new still brings new motion for its scene (the shot filmed from the old still is retired
    with it). Paid redos carry the studio's price when it has one; their purchase is still
    asked of the Policy Kernel by `redo_scene`.

    His choice on the sheet (``choices``, `owner_scene_choices`) stands: a scene he chose to
    show as a locally animated still (LOCAL_MOVE) gets no paid motion. A motion she lists there
    is skipped (``OWNER_CHOICE``), and its new still is followed by the film rejoined from its
    takes (`REJOIN`, 0 credits) instead of a paid motion (2026-10-10 review: babcf272's scene 5,
    his LOCAL_MOVE, would have had a 340-credit motion bought unasked on a model he never chose).

    ``already``: the (redo, scene) bought for this very decision before (her REPAIR carried on
    after his answer or his look, `decision_state` ``ready``): never bought again; what follows
    them (the motion after a new still, the film rejoined) is what is left of her list."""
    from app.media.production_policy import LOCAL_MOVE  # noqa: PLC0415

    choices = dict(choices or {})
    bought = {
        (str(pair[0]), int(pair[1]) if pair[1] is not None else None)
        for pair in already
        if len(pair) == 2
    }
    priced = {
        (proposal.redo, proposal.scene_index): proposal
        for proposal in proposals
        if isinstance(proposal, RedoProposal)
    }
    wanted: list[dict[str, Any]] = []
    for item in repairs:
        redo = str(item.get("redo") or "")
        scene = item.get("scene_index")
        scene = int(scene) if isinstance(scene, int) and redo not in FILM_LEVEL_REDOS else None
        if redo in ("still", "motion") and scene is not None and kinds.get(scene) in CARD_KINDS:
            redo = "card"
        wanted.append({"redo": redo, "scene_index": scene, "reason": _short(item.get("reason"))})
    run: list[RedoProposal] = []
    skipped: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    stills_run: set[int] = set()
    #: What follows a new still of hers, per scene: its motion, or the film rejoined.
    follow: dict[int, str] = {}

    def skip(entry: Mapping[str, Any], status: str, reason: str) -> None:
        skipped.append({**entry, "status": status, "reason": reason})

    def local(scene: int) -> bool:
        return choices.get(scene) == LOCAL_MOVE

    def paid(redo: str, scene: int, reason: str) -> RedoProposal:
        known = priced.get((redo, scene))
        credits = known.credits if known is not None and known.credits else None
        return RedoProposal(
            redo=redo,
            scene_index=scene,
            reason=reason,
            credits=credits,
            usd_micros=known.usd_micros if known is not None and credits else None,
            price_source=known.price_source if known is not None else None,
            model_id=known.model_id if known is not None else None,
            resolution=known.resolution if known is not None else None,
        )

    order = ("still", "motion", "card", "audio", "encode")
    for entry in sorted(wanted, key=lambda e: order.index(e["redo"]) if e["redo"] in order else 9):
        redo, scene = entry["redo"], entry["scene_index"]
        if (redo, scene) in seen:
            continue
        seen.add((redo, scene))
        what = f"scena {scene}: {REDO_RO.get(redo, redo)}" if scene else REDO_RO.get(redo, redo)
        if redo in ("card", *FILM_LEVEL_REDOS):
            if redo == "card" and kinds.get(int(scene or 0)) not in CARD_KINDS:
                skip(entry, "NOT_A_CARD", f"{what.capitalize()}: scena este filmată, nu un card")
                continue
            if free_used:
                skip(
                    entry,
                    "FREE_FIX_USED",
                    f"{what.capitalize()}: reparația gratuită s-a făcut deja o dată pentru acest "
                    "film și nu se repetă singură",
                )
                continue
            run.append(
                RedoProposal(redo=redo, scene_index=scene, reason=entry["reason"], credits=0)
            )
            continue
        if redo not in ("still", "motion") or scene is None:
            skip(entry, "UNKNOWN", f"{what.capitalize()}: nu se știe ce să se refacă")
            continue
        if (redo, scene) in bought:
            # Bought for this decision already: what follows it is what is left of her list.
            if redo == "still":
                stills_run.add(scene)
                follow.setdefault(scene, REJOIN if local(scene) else "motion")
            else:
                follow[scene] = REJOIN
            continue
        if redo == "motion" and local(scene):
            skip(
                entry,
                "OWNER_CHOICE",
                f"Scena {scene}: ai ales-o pe foaia de filmare animată local (LOCAL_MOVE); nu "
                "i se cumpără mișcare, alegerea ta rămâne",
            )
            continue
        his = list((protected.get(scene) or {}).get(redo) or [])
        if his:
            skip(
                entry,
                "OWNER_APPROVED",
                f"Scena {scene}: preluarea din film a fost aprobată de tine ca finală; nimeni "
                "nu o retrage în locul tău, deci scena nu se reface",
            )
            continue
        if redo == "motion" and ("still", scene) in seen and scene not in stills_run:
            # Her still for this scene was not carried out: a motion redo alone would film the
            # same picture again, which she did not ask for.
            skip(entry, "STILL_SKIPPED", f"Scena {scene}: mișcarea nouă cerea o imagine nouă")
            continue
        run.append(paid(redo, scene, entry["reason"]))
        if redo == "still":
            stills_run.add(scene)
            follow.setdefault(scene, REJOIN if local(scene) else "motion")
        elif scene in follow:
            follow[scene] = "listed"
    for scene, next_step in sorted(follow.items()):
        if next_step == "motion" and ("motion", scene) in bought:
            next_step = REJOIN
        if next_step == "motion" and not any(
            item.redo == "motion" and item.scene_index == scene for item in run
        ):
            if (protected.get(scene) or {}).get("motion"):
                skip(
                    {"redo": "motion", "scene_index": scene, "reason": ""},
                    "OWNER_APPROVED",
                    f"Scena {scene}: cadrul din film a fost aprobat de tine ca final; mișcarea "
                    "nu se reface în locul tău",
                )
                continue
            run.append(paid("motion", scene, f"Scena {scene}: mișcarea filmată din imaginea nouă."))
        elif next_step == REJOIN:
            run.append(
                RedoProposal(
                    redo=REJOIN,
                    scene_index=scene,
                    reason=(
                        f"Scena {scene}: filmul se reasamblează din preluări cu imaginea nouă"
                        + (", animată local, cum ai ales" if local(scene) else "")
                        + "; fără credite."
                    ),
                    credits=0,
                )
            )
    return run, skipped


#: A redo of a resumed REPAIR that today's rules no longer allow (`resume_repairs`).
DROPPED_ON_RESUME = "DROPPED_ON_RESUME"


def resume_repairs(
    decided: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Her REPAIR's list as its resumption may still carry it out under today's rules, and what
    is dropped, with why in the Owner's words (2026-10-12 review: a REPAIR decided before that
    day's rules waited for his answer or for a take, and was then carried out as it was — a
    scene that had passed before, or that no REAL serious finding named, redone all the same).

    ``context`` is her reading of the same report rebuilt now (`film_qc_context`). Kept: what
    was bought for this decision already (``bought_so_far``: what follows it is never cut), and
    every other redo `reviews.redo_refusal` allows, or stops only at his limits (his card asks
    him), on a scene that is not settled (``passed_before_unchanged``) and that a REAL finding
    of a serious defect names (one with no severity, from before 2026-10-12, counts as
    serious), unless that finding's check is settled for the scene (`reviews.settled_checks`).
    The free fixes (card, audio, encode) need only `redo_refusal`."""
    from app.agents.reviews import LIMITS  # noqa: PLC0415 - one code for his cap
    from app.media.picture_qc import settle_family  # noqa: PLC0415 - shared render evidence

    bought = {
        (str(pair[0]), pair[1] if isinstance(pair[1], int) else None)
        for pair in decided.get("bought_so_far") or []
        if isinstance(pair, list | tuple) and len(pair) == 2
    }
    scenes = {
        int(scene["scene_index"]): scene
        for scene in context.get("scenes") or []
        if isinstance(scene, Mapping) and isinstance(scene.get("scene_index"), int)
    }
    real = [
        verdict
        for verdict in decided.get("verdicts") or []
        if isinstance(verdict, Mapping)
        and verdict.get("verdict") == "REAL"
        and verdict.get("severity") != "minor"
        and not verdict.get("check_level")
        and not (
            isinstance(verdict.get("scene_index"), int)
            # What YuNet or the flat band measured is never settled (round 3).
            and not (verdict.get("detector") or measured_by_detector(verdict.get("text")))
            and settle_family(verdict.get("check"))
            in settled_checks(scenes.get(int(verdict["scene_index"])) or {})
        )
    ]
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    def drop(item: Mapping[str, Any], reason: str) -> None:
        dropped.append({**item, "status": DROPPED_ON_RESUME, "reason": _short(reason)})

    for item in decided.get("repairs") or []:
        if not isinstance(item, Mapping):
            continue
        scene = item.get("scene_index")
        if (str(item.get("redo") or ""), scene if isinstance(scene, int) else None) in bought:
            kept.append(dict(item))
            continue
        try:
            redo = DirectorRedo.model_validate(item)
        except ValueError:
            drop(item, "Refacerea nu mai spune ce să se refacă")
            continue
        if redo.redo in PAID_REDOS and redo.scene_index is not None:
            index = int(redo.scene_index)
            if (scenes.get(index) or {}).get("passed_before_unchanged"):
                drop(
                    item,
                    f"Scena {index}: ce o pică acum a trecut un control anterior (sau a fost "
                    "acceptat de Directoare) cu aceleași preluări; nu se reface",
                )
                continue
            if not any(_names_scene(verdict, index) for verdict in real):
                drop(
                    item,
                    f"Scena {index}: nicio constatare reală a unui defect serios nu o numește; "
                    "o imagine sau o mișcare se reface doar pentru un defect serios",
                )
                continue
        refused = redo_refusal(redo, context)
        if refused is not None and refused[0] != LIMITS:
            drop(item, f"Nu se mai poate face acum ({refused[1]})")
            continue
        kept.append(dict(item))
    return kept, dropped


def _teaching(payload: Mapping[str, Any]) -> list[tuple[str, list[tuple[int, str, str]]]]:
    """Each lesson of her decision a prompt writer can follow, in the order her verdicts give
    them, with every (scene, family, verdict) that taught it: a REAL or ACCEPTED verdict whose
    finding a picture or motion prompt can act on (``teaches``, `reviews.prompt_actionable`:
    not the sound, the encode, a whole check's «a picat», Motion QC's fallback, nor a picture
    already settled for its check). A verdict recorded before ``teaches`` existed counts when it
    is one scene's finding of a picture or motion check other than a vendor's fallback."""
    from app.agents.reviews import PROMPT_CHECKS  # noqa: PLC0415 - one list for both
    from app.media.picture_qc import settle_family  # noqa: PLC0415 - shared render evidence

    taught: dict[str, list[tuple[int, str, str]]] = {}
    for verdict in payload.get("verdicts") or []:
        if not isinstance(verdict, Mapping) or verdict.get("verdict") not in ("REAL", "ACCEPTED"):
            continue
        teaches = verdict.get("teaches")
        if teaches is None:
            check = verdict.get("check")
            teaches = (
                not verdict.get("check_level")
                and isinstance(verdict.get("scene_index"), int)
                and (check is None or str(check) in PROMPT_CHECKS)
                and not vendor_fallback(verdict)
            )
        lesson = " ".join(str(verdict.get("lesson") or "").split())
        if not teaches or not lesson:
            continue
        pairs = taught.setdefault(lesson, [])
        scene = verdict.get("scene_index")
        if isinstance(scene, int):
            pairs.append((int(scene), settle_family(verdict.get("check")), str(verdict["verdict"])))
    return list(taught.items())


def teachable_lessons(payload: Mapping[str, Any]) -> list[tuple[str, int | None]]:
    """The lessons of her decision a prompt writer can follow (`_teaching`), each said once,
    with the first scene it was about."""
    return [(lesson, pairs[0][0] if pairs else None) for lesson, pairs in _teaching(payload)]


def lesson_source(run_id: Any, number: int) -> str:
    """The source a lesson of her decision is stored under: an id made from her decision's run
    and the lesson's place among its lessons (`_teaching`), the length of a run id (the memory
    row's ``source_id`` holds 36 characters). One source per lesson (the review of 2026-10-12,
    round 3): a lesson is confirmed by its own scenes and withdrawn when her second look
    overturned the very findings that taught it, never with the rest of her decision's."""
    return str(uuid5(NAMESPACE_URL, f"director-qc-lesson:{run_id}#{int(number)}"))


def lesson_sources(payload: Mapping[str, Any]) -> dict[str, str]:
    """{lesson: source} for every lesson of her decision a prompt can follow."""
    run_id = payload.get("run_id")
    if not run_id:
        return {}
    return {
        lesson: lesson_source(run_id, number)
        for number, (lesson, _pairs) in enumerate(_teaching(payload), start=1)
    }


def lesson_groups(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The lessons her decision recorded, each with the source it was stored under and the
    (scene, family, verdict) that taught it. A decision recorded before one source per lesson
    (no ``lesson_sources``) stored them all under its run: one group, every pair."""
    recorded = {str(item) for item in payload.get("lessons_recorded") or []}
    run_id = payload.get("run_id")
    if not recorded or not run_id:
        return []
    teaching = [(lesson, pairs) for lesson, pairs in _teaching(payload) if lesson in recorded]
    sources = payload.get("lesson_sources")
    if isinstance(sources, Mapping):
        return [
            {"lesson": lesson, "source_id": str(sources[lesson]), "pairs": pairs}
            for lesson, pairs in teaching
            if sources.get(lesson)
        ]
    pairs = [pair for _lesson, found in teaching for pair in found]
    return [{"lesson": None, "source_id": str(run_id), "pairs": pairs}] if pairs else []


def _film_scope(session: Session, payload: Mapping[str, Any]) -> str:
    """The scope her lessons are stored under: «serial» for an episode of the office serial,
    «factual» for any other film (`prompt_agent.record_prompt_lesson`)."""
    kind = str(payload.get("film_kind") or "")
    if kind in LESSON_SCOPES:
        return kind
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media

    board = session.get(Storyboard, str(payload.get("storyboard_id") or ""))
    script = session.get(ScriptDraft, board.script_draft_id) if board is not None else None
    return "serial" if is_serial_film(board, script) else "factual"


def learn_from_decision(session: Session, payload: Mapping[str, Any]) -> list[str]:
    """Store the lesson of every REAL or ACCEPTED verdict of her fresh decision that a prompt
    can act on (`teachable_lessons`) as a prompt lesson; returns the lessons stored.

    2026-10-12, the Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE
    APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!» Until then a lesson
    was written only by the editorial review, and the same mistakes were bought again film after
    film. Each is stored through `prompt_agent.record_prompt_lesson` (the studio's one rule for
    what a lesson may say and how a newer one supersedes an older one), with the run of her
    decision and the lesson's place as its source (`lesson_source`), scoped to the kind of film
    (`_film_scope`) and provisional until a later QC passes the scenes it was about with new
    takes (`confirm_lessons`), or withdrawn when her second look overturned the findings that
    taught it (`withdraw_overturned_lessons`); what it refuses is not counted.
    Only her own fresh decision teaches: a decision carried on (``resumed``) repeats one already
    learned, and the Owner's card that publishes a film (``decided_by`` owner) is not her
    reading."""
    from app.media.prompt_agent import record_prompt_lesson  # noqa: PLC0415 - a large module

    if str(payload.get("decided_by") or "") != DIRECTOR or payload.get("resumed"):
        return []
    lessons = teachable_lessons(payload)
    if not lessons:
        return []
    sources = lesson_sources(payload)
    scope = _film_scope(session, payload)
    stored: list[str] = []
    for lesson, _scene in lessons:
        if record_prompt_lesson(
            session,
            lesson,
            source_id=sources.get(lesson),
            scope=scope,
            provisional=True,
        ):
            stored.append(lesson)
    return stored


def record_lessons(engine: Engine, payload: Mapping[str, Any]) -> list[str]:
    """`learn_from_decision` in its own short transaction: called as soon as her fresh decision
    is read (`runbook.stages._director_reads`), so the rewrite of the very scenes her REPAIR
    redoes (`scene_rewrite.rewrite_scene` reads `prompt_lessons`) already follows them.

    A failure while storing them is logged and costs nothing else (2026-10-12 review: it used to
    discard her validated decision, and the film waited for an answer she had already given)."""
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            return learn_from_decision(session, payload)
    except Exception as exc:  # noqa: BLE001 - her decision stands without its lessons
        logger.warning(
            "director_lessons_not_recorded",
            extra={"report_id": payload.get("report_id"), "error": type(exc).__name__},
        )
        return []


def _learned(session: Session, payload: Mapping[str, Any]) -> list[str]:
    """The lessons her decision taught: those already recorded when it was read
    (``lessons_recorded``, `record_lessons`), else learned now in a savepoint of this
    transaction, so a failure there leaves her decision to be written all the same."""
    if "lessons_recorded" in payload:
        return [str(item) for item in payload.get("lessons_recorded") or []]
    try:
        with session.begin_nested():
            return learn_from_decision(session, payload)
    except Exception as exc:  # noqa: BLE001 - her decision is written without its lessons
        logger.warning(
            "director_lessons_not_recorded",
            extra={"report_id": payload.get("report_id"), "error": type(exc).__name__},
        )
        return []


def _decision_event(session: Session, payload: Mapping[str, Any], correlation: str) -> DomainEvent:
    """Her decision on the report, with the lessons it taught named in the event
    (``lessons_recorded``): recorded when her decision was read, never a second time
    (`_learned`)."""
    learned = _learned(session, payload)
    data = {key: value for key, value in payload.items() if key != "lessons_recorded"}
    if learned:
        data["lessons_recorded"] = learned
        if "lesson_sources" not in data and not payload.get("resumed"):
            # Her fresh decision's lessons were stored each under its own source
            # (`lesson_source`, round 3); a decision recorded before that and carried on now
            # stored them under its run, and says so by having none (`lesson_groups`).
            data["lesson_sources"] = {
                lesson: source
                for lesson, source in lesson_sources(payload).items()
                if lesson in learned
            }
    return append_event(
        session,
        DECISION_EVENT,
        "quality_control_report",
        str(payload["report_id"]),
        1,
        data,
        correlation,
    )


def _check_passes(
    checks: Mapping[str, Any], findings: list[dict[str, Any]], family: str, scene: int
) -> bool:
    """Whether a report's check of ``family`` passes one scene: no finding of that family is
    about the scene (its own, named with a scene word, or a whole check's «a picat» over it),
    and the check measured it — a picture check's own verdict on the scene passed
    (`picture_qc.scene_state`), any other check ran. A finding no check claimed passes a scene
    no finding at all is about."""
    from app.media.picture_qc import (  # noqa: PLC0415
        CARRIED_CHECKS,
        UNATTRIBUTED,
        scene_state,
        settle_family,
    )

    for finding in findings:
        if family != UNATTRIBUTED and settle_family(finding.get("check")) != family:
            continue
        if finding.get("check_level"):
            if scene in (finding.get("scenes_of_check") or []):
                return False
            continue
        if _names_scene(finding, scene):
            return False
    if family in CARRIED_CHECKS:
        return scene_state(checks, family, scene) is True
    if family == UNATTRIBUTED:
        return True
    record = checks.get(family)
    return isinstance(record, Mapping) and record.get("passed") is not None


def _film_takes_of_report(session: Session, report_id: str) -> dict[int, tuple[str, str | None]]:
    """The (still, clip) each scene of the report's film was cut from."""
    from app.media.picture_qc import scene_takes  # noqa: PLC0415

    report = session.get(QualityControlReport, report_id) if report_id else None
    job = (
        session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == report.media_asset_id)
        )
        if report is not None
        else None
    )
    production = job.production_json if job is not None else None
    return scene_takes(production if isinstance(production, Mapping) else {})


def confirm_lessons(engine: Engine, report_id: str) -> int:
    """Confirm her provisional lessons once a later film QC of the storyboard shows they worked
    (`prompt_agent.confirm_prompt_lessons`, by each lesson's source, `lesson_source`): for a
    lesson, every scene it was about that the later film shows with other takes than the film
    she judged is passed by the same check, and at least one such scene exists.

    2026-10-12 review: her lessons stayed «unverified» for ever; round 3 of it: they were
    confirmed by scenes nothing had changed in (a scene her second look kept as it was passed
    again with the very picture, which proves nothing about the words). Returns how many were
    confirmed. Read and written in one short transaction; nothing is bought."""
    from app.media.prompt_agent import confirm_prompt_lessons  # noqa: PLC0415 - a large module

    with Session(engine) as session:
        report = session.get(QualityControlReport, report_id)
        if report is None:
            return 0
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == report.media_asset_id)
        )
        storyboard_id = str(job.storyboard_id) if job is not None else ""
        if not storyboard_id:
            return 0
        checks = report.checks_json if isinstance(report.checks_json, Mapping) else {}
        findings = report_findings(
            {"checks_json": checks, "failure_reasons_json": report.failure_reasons_json or []}
        )
        takes_now = _film_takes_of_report(session, report_id)
        verified_at = str(report.verified_at)
        sources: list[str] = []
        judged: dict[str, dict[int, tuple[str, str | None]]] = {}
        for decision in decisions_of_film(session, storyboard_id):
            if str(decision.get("report_id") or "") == report_id:
                continue
            # When her decision began to be carried out (a REPAIR's ``started_at``), else when
            # it was recorded: a QC from before cannot show her lesson worked.
            if str(decision.get("started_at") or decision.get("at") or "") >= verified_at:
                continue
            groups = lesson_groups(decision)
            if not groups:
                continue
            then_id = str(decision.get("report_id") or "")
            if then_id not in judged:
                judged[then_id] = _film_takes_of_report(session, then_id)
            takes_then = judged[then_id]
            for group in groups:
                changed = [
                    (scene, family)
                    for scene, family, _verdict in group["pairs"]
                    if scene in takes_now and takes_now.get(scene) != takes_then.get(scene)
                ]
                if changed and all(
                    _check_passes(checks, findings, family, scene) for scene, family in changed
                ):
                    sources.append(str(group["source_id"]))
    if not sources:
        return 0
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        return int(confirm_prompt_lessons(session, sorted(set(sources))) or 0)


#: Why her lessons are withdrawn when her second look overturned the findings that taught them.
OVERTURNED_LESSON_RO = (
    "Directoarea s-a uitat din nou la scenă: refuzul controlului nu s-a confirmat, deci lecția "
    "nu avea ce corecta"
)


def withdraw_overturned_lessons(
    engine: Engine, payload: Mapping[str, Any], overturned: Iterable[int]
) -> int:
    """Withdraw the provisional lessons of her decision that only REAL findings of scenes her
    second look overturned taught (`prompt_agent.withdraw_prompt_lessons`, by each lesson's
    source): the defect was not there, so the cause she wrote for it teaches nothing (the review
    of 2026-10-12, round 3: those lessons were stored before her look and stayed). A lesson
    another verdict also taught stays. Returns how many; never raises."""
    scenes = {int(scene) for scene in overturned}
    sources = [
        str(group["source_id"])
        for group in lesson_groups(payload)
        if group["pairs"]
        and all(verdict == "REAL" and scene in scenes for scene, _f, verdict in group["pairs"])
    ]
    if not sources:
        return 0
    try:
        from app.media.prompt_agent import withdraw_prompt_lessons  # noqa: PLC0415

        with Session(engine) as session, session.begin():
            lock_for_write(session)
            return int(withdraw_prompt_lessons(session, sources, OVERTURNED_LESSON_RO) or 0)
    except Exception as exc:  # noqa: BLE001 - the lessons stay provisional; the film goes on
        logger.warning(
            "director_lessons_not_withdrawn",
            extra={"report_id": payload.get("report_id"), "error": type(exc).__name__},
        )
        return 0


#: Her ACCEPT that her second looks made of her REPAIR: what the summary adds.
ACCEPTED_BY_LOOKS_RO = (
    "Înainte de orice cumpărare s-a uitat din nou la fiecare scenă pe care o refăcea, și "
    "refuzul controlului nu s-a confirmat la niciuna ({scenes}): nu se cumpără nimic, iar filmul "
    "trece controlul prin decizia ei și merge la publicare."
)


def accepted_by_looks(
    decided: Mapping[str, Any], overturned: Iterable[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Her REPAIR made her ACCEPT when her second looks before the purchases overturned every
    REAL finding of the report; None when one REAL finding stands.

    The Owner, 2026-10-12 19:00: «și după ce se uită Directoarea, trebuie să aibă și puterea de
    a trece de QC și merge mai departe cu publicarea». Until then a REPAIR whose every purchase
    her look dropped did nothing, and the film waited an hour for her next reading. Every REAL
    finding must name scenes her looks overturned (``overturned``: `runbook.stages`'s entries,
    with ``scene_index`` and ``severity``) — for a defect quality control measured as serious
    only with no defect at all (severity none: the contract of her second look and, again, the
    code's); a whole check's «a picat» only over such scenes; none about no scene (the sound,
    the encode); and no finding is one that is not hers (rights, claims, the file: her ACCEPT
    does not reach them). Her verdicts are kept as her looks left them: no defect makes the
    finding FALSE, a minor one ACCEPTED as minor (``before_look`` keeps REAL), and the looks are
    the evidence the PASSED report stands on (``second_looks``, ``done.overturned``)."""
    looks: dict[int, Mapping[str, Any]] = {
        int(entry["scene_index"]): entry
        for entry in overturned
        if isinstance(entry, Mapping) and isinstance(entry.get("scene_index"), int)
    }
    verdicts = [item for item in decided.get("verdicts") or [] if isinstance(item, Mapping)]
    if str(decided.get("decision") or "") != "REPAIR" or not looks or not verdicts:
        return None
    if any(item.get("not_yours") for item in verdicts):
        return None
    after: list[dict[str, Any]] = []
    cleared: set[int] = set()
    for verdict in verdicts:
        item = dict(verdict)
        if item.get("verdict") != "REAL":
            after.append(item)
            continue
        if item.get("check_level"):
            named = {int(s) for s in item.get("scenes_of_check") or [] if isinstance(s, int)}
        else:
            own = item.get("scene_index")
            named = set(scenes_named(item.get("text"), own=own if isinstance(own, int) else None))
            named |= {int(s) for s in item.get("scenes") or [] if isinstance(s, int)}
        if not named or not named <= set(looks):
            return None
        severities = {str(looks[scene].get("severity") or "") for scene in named}
        serious = bool(item.get("measured_serious") or measured_serious(item.get("text")))
        if not severities <= {"none", "minor"} or (serious and severities != {"none"}):
            return None
        reasons = "; ".join(
            dict.fromkeys(_short(looks[scene].get("reason"), 200) for scene in sorted(named))
        )
        item["before_look"] = "REAL"
        item["reason"] = _short(f"A doua privire a Directoarei: {reasons}", 400)
        if severities == {"none"}:
            item["verdict"] = "FALSE"
        else:
            item["verdict"] = "ACCEPTED"
            item["severity"] = "minor"
        cleared |= named
        after.append(item)
    if not cleared:
        return None
    scenes = ", ".join(f"scena {scene}" for scene in sorted(cleared))
    said = str(decided.get("summary") or "").strip()
    summary = " ".join(part for part in (said, ACCEPTED_BY_LOOKS_RO.format(scenes=scenes)) if part)
    entries = [dict(looks[scene]) for scene in sorted(looks)]
    return {
        **decided,
        "decision": "ACCEPT",
        "verdicts": after,
        "repairs": [],
        "repairs_before_look": list(decided.get("repairs") or []),
        "accepted_by_second_look": True,
        "second_looks": entries,
        "done": {"overturned": entries},
        "summary": _short(summary, 800),
    }


def record_decision(engine: Engine, payload: Mapping[str, Any], correlation: str) -> str:
    """Write `DECISION_EVENT` (``payload`` names the report); returns the event id."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        return str(_decision_event(session, payload, correlation).event_id)


def accept_film(
    engine: Engine,
    reading: Mapping[str, Any],
    payload: Mapping[str, Any],
    correlation: str,
    *,
    decided_by: str = DIRECTOR,
) -> dict[str, Any]:
    """Her ACCEPT, carried out: a new PASSED report for the film with the original checks
    kept, a ``director_qc`` check listing every verdict (her overrules among them) and the
    original failures, written in one transaction with her decision. The score is the
    publishing gate's minimum unless the measured one was higher: the film passes by her
    decision, not by a measurement that never said so. ``decided_by`` is the Owner's when his
    card «Publică filmul așa cum e» carries it out (`decisions.producers.redo_cap`)."""
    from app.publishing.services import QC_MINIMUM_SCORE  # noqa: PLC0415 - it imports media

    report = reading.get("report") or {}
    report_id = str(reading["report_id"])
    asset_id = str(reading["media_asset_id"])
    passed_id = str(uuid4())
    verdicts = list(payload.get("verdicts") or [])
    checks = dict(report.get("checks_json") or {})
    checks["director_qc"] = {
        "passed": True,
        "status": "DECIDED",
        "decision": "ACCEPT",
        "decided_by": decided_by,
        "agent_name": payload.get("agent_name"),
        "run_id": payload.get("run_id"),
        "of_report": report_id,
        "original_status": report.get("status"),
        "original_score": report.get("score"),
        "original_failures": list(report.get("failure_reasons_json") or []),
        "overrules": [item for item in verdicts if item.get("verdict") != "REAL"],
        "summary": payload.get("summary"),
        # Her second looks that overturned every REAL finding before anything was bought: the
        # evidence her ACCEPT stands on (the Owner, 2026-10-12 19:00: «și după ce se uită
        # Directoarea, trebuie să aibă și puterea de a trece de QC»).
        **(
            {"second_looks": list(payload.get("second_looks") or [])}
            if payload.get("second_looks")
            else {}
        ),
    }
    score = max(float(QC_MINIMUM_SCORE), float(PUBLISH_SCORE), float(report.get("score") or 0.0))
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        event = _decision_event(
            session,
            {**payload, "outcome": "ACCEPTED", "final": True, "passed_report_id": passed_id},
            correlation,
        )
        session.add(
            QualityControlReport(
                id=passed_id,
                media_asset_id=asset_id,
                status="PASSED",
                score=round(min(score, 1.0), 2),
                checks_json=checks,
                failure_reasons_json=[],
                verified_at=utc_now(),
                event_id=event.event_id,
            )
        )
        event_id = str(event.event_id)
    return {"passed_report_id": passed_id, "event_id": event_id}


def close_film(
    engine: Engine, reading: Mapping[str, Any], payload: Mapping[str, Any], correlation: str
) -> dict[str, Any]:
    """Her CLOSE, carried out through the Director's own retirement path: the film REJECTED
    with its books closed (`runbook.stages.close_film_books`, ``retired_by`` Director), the
    paid questions about it withdrawn (nothing more is bought for it), and her decision, in one
    transaction, under the film's purchase lease as the Owner's «Închide filmul» takes it: a
    purchase in flight refuses the close (`shooting_sheet.FilmBusy`, raised; the report then
    waits for her). Nothing is bought. (`media.film_close.close_film` is his command, and
    refuses a rendered film; this is hers.)"""
    from app.media.shooting_sheet import (  # noqa: PLC0415 - it imports runbook
        CLOSE_LEASE_STEP,
        film_purchase_lease,
    )

    storyboard_id = str(reading.get("storyboard_id") or "")
    if not storyboard_id:
        return _closing(engine, reading, payload, correlation)
    with film_purchase_lease(
        engine, storyboard_id, holder=correlation, step=CLOSE_LEASE_STEP, ttl_seconds=600
    ):
        return _closing(engine, reading, payload, correlation)


def _closing(
    engine: Engine, reading: Mapping[str, Any], payload: Mapping[str, Any], correlation: str
) -> dict[str, Any]:
    from app.runbook.stages import (  # noqa: PLC0415 - runbook imports media
        close_film_books,
        film_spent_micros,
    )
    from app.services import withdraw_subject_approvals  # noqa: PLC0415

    storyboard_id = str(reading.get("storyboard_id") or "")
    # Read under the lease: every purchase that finished before it is in this figure.
    spent = film_spent_micros(engine, storyboard_id) if storyboard_id else 0
    closing: dict[str, Any] = {}
    withdrawn: list[str] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        board = session.get(Storyboard, storyboard_id) if storyboard_id else None
        if board is not None and board.status != "REJECTED":
            title = str(board.title or storyboard_id[:8])
            closing = close_film_books(
                session,
                board,
                spent=spent,
                retired_by=DIRECTOR,
                correlation=correlation,
                details={
                    "previous_status": board.status,
                    "reason": _short(
                        f"Închis de Directoare după controlul calității: {payload.get('summary')}",
                        300,
                    ),
                    "report_id": payload.get("report_id"),
                    "media_asset_id": payload.get("media_asset_id"),
                },
            )
            withdrawn = withdraw_subject_approvals(
                session,
                subject=storyboard_id,
                reason=(
                    f"Retrasă: Directoarea a închis filmul «{title}» după controlul calității; "
                    "pentru el nu se mai cumpără nimic."
                ),
                correlation_id=correlation,
            )
        event = _decision_event(
            session,
            {
                **payload,
                "outcome": "CLOSED",
                "final": True,
                "bought_takes": closing.get("bought_takes") or {},
                "spent_usd_micros": closing.get("spent_usd_micros", spent),
                "withdrawn_approvals": withdrawn,
            },
            correlation,
        )
        return {
            "event_id": str(event.event_id),
            "closed": bool(closing),
            "bought_takes": closing.get("bought_takes") or {},
            "items": closing.get("items") or [],
            "spent_usd_micros": int(closing.get("spent_usd_micros", spent) or 0),
            "withdrawn": withdrawn,
        }


# ------------------------------------------------- her look at the pictures a gate refused
#
# 2026-10-10, 20:06 local, the Owner: «Directorul ce face? El ar trebui să hotărască dacă poza
# este bună sau nu.» babcf272's scene 5: her REPAIR bought a new still, the stills gate refused
# every candidate on a local reading (a black night sky at the top read as a flat band between
# panels) before anything looked at them, and her decision waited for his look on the sheet.
# Now she looks at them herself (`runbook.stages._director_looks`); his look still wins.


def looks_of_film(session: Session, storyboard_id: str) -> list[dict[str, Any]]:
    """Her newest looks at the pictures bought for this film, as she reads them again."""
    out: list[dict[str, Any]] = []
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == LOOK_EVENT)
        .order_by(DomainEvent.sequence)
    ):
        payload = _payload(event)
        if str(payload.get("storyboard_id") or "") != storyboard_id:
            continue
        out.append(
            {
                "report_id": payload.get("report_id"),
                "at": event.timestamp,
                "scene_index": payload.get("scene_index"),
                "kind": payload.get("kind"),
                "decision": payload.get("decision"),
                "shown": len(payload.get("shown") or []),
                "chosen_candidate": payload.get("candidate"),
                "approved": payload.get("approved"),
                "reason": _short(payload.get("reason"), 400),
            }
        )
    return out[-6:]


def no_picture(row: SceneTake, ffmpeg: str | None) -> str | None:
    """Why a candidate is no picture at all (the degenerate check: stripes, bands, a blank
    field), or None: the gate's own words, else measured again (`qc.still_is_degenerate`).

    Never hers to choose: there is nothing in it to judge, and choosing it would put an empty
    frame in the film. Every other refusal (panels, sharpness, motion blur, palette, the vision
    checklist's verdict, faces) is a reading of a picture, and a reading can be wrong
    (babcf272's night sky read as a band between panels): those she judges by looking."""
    from app.media.assembler import DEGENERATE_FAILURE_CODE  # noqa: PLC0415 - a large module
    from app.media.qc import still_is_degenerate  # noqa: PLC0415 - a large module

    detail = str(row.failure_detail or "")
    if row.failure_code == DEGENERATE_FAILURE_CODE or _NO_PICTURE_WORDS in detail:
        return _short(detail, 200) or "nu este o imagine"
    if row.kind == "still" and row.path:
        return still_is_degenerate(ffmpeg, Path(str(row.path)))
    return None


def look_pictures(row: SceneTake, ffmpeg_path: str | None, work_dir: Path) -> list[str]:
    """What she is shown of one candidate, as quality control shows it (`picture_qc`): a still
    at 1080 px, or a shot's first, middle and last frames. Empty when it cannot be prepared."""
    from app.media.picture_qc import still_image  # noqa: PLC0415 - a large module
    from app.media.qc import clip_frames  # noqa: PLC0415 - a large module
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    ffmpeg = find_ffmpeg(ffmpeg_path)
    if row.kind == "still":
        image = still_image(ffmpeg, str(row.path))
        return [image] if image else []
    frames = clip_frames(ffmpeg, str(row.path), work_dir)
    images = [still_image(ffmpeg, path) for _at, _time, path in frames]
    return [image for image in images if image] if frames and all(images) else []


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def look_entries(
    engine: Engine, decision: Mapping[str, Any], *, ffmpeg_path: str | None, work_dir: Path
) -> list[dict[str, Any]]:
    """What she is shown, per scene of her BOUGHT_WAITING decision whose refused candidates
    wait for her look (`_owed_her_look`): ``shown`` (the scene's intent, its picture prompt,
    the film's look, the bible's rules, and per candidate the gate's own reasons for refusing
    it), ``images`` (each candidate's pictures in order, `look_pictures`) and ``offered`` (their
    take ids, newest first). ``not_offered`` lists the others with why: no picture at all
    (`no_picture`), a file that is not the one bought, a shot he could not choose either
    (`assembler.clip_choice`: filmed from another still or for another motion prompt), pictures
    that cannot be prepared, or more than `LOOK_MAX_CANDIDATES`. ``seen``: every candidate
    considered, so no look is owed for them again. Reads only."""
    from app.media.assembler import (  # noqa: PLC0415 - a large module
        SHOT_TAKE_KINDS,
        clip_choice,
        scene_clip_context,
    )
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.media.stills_stage import _bible_rules  # noqa: PLC0415 - the gate's own rules
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    storyboard_id = str(decision.get("storyboard_id") or "")
    planned: list[tuple[int, str, str, list[SceneTake], dict[str, Any]]] = []
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id) if storyboard_id else None
        if board is None:
            return []
        title = _title(session, storyboard_id)
        bible = dict(board.visual_bible_json) if isinstance(board.visual_bible_json, dict) else {}
        seen = {
            str(take)
            for look in _her_looks(session, str(decision.get("report_id") or ""))
            for take in look.get("seen") or []
        }
        for entry in _waiting_entries(decision):
            kind = str(entry.get("kind") or "still")
            scene = int(entry["scene_index"])
            since = str(entry.get("since") or decision.get("started_at") or "")
            if kind == REJOIN or new_approved_take(session, storyboard_id, scene, kind, since):
                continue
            candidates = bought_since(session, storyboard_id, scene, kind, since)
            if any(row.status in ("SUBMITTED", "PAID") for row in candidates):
                continue  # the gate's verdict may still come
            owed = _owed_her_look(session, candidates, seen)
            if not owed:
                continue
            row = session.scalars(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == storyboard_id,
                    StoryboardScene.scene_index == scene,
                )
            ).first()
            package = (
                row.prompt_json if row is not None and isinstance(row.prompt_json, dict) else {}
            )
            visual = row.visual_prompt if row is not None else ""
            view: dict[str, Any] = {
                "scene_index": scene,
                "narration": _short(row.voiceover_segment if row is not None else "", 300),
                "intent": _short(visual, 400),
                "picture_prompt": _short(package.get("still_prompt") or visual, 800),
                "look": _short(package.get("look_block"), 400) or None,
                "camera_move": package.get("camera_move"),
                # The picture prompt can omit these under its character cap. A look that
                # sees only that truncated text invents the wardrobe from the candidate
                # itself, then later QC refuses it against the actual character bible.
                "character_bible": package.get("characters") or [],
                "in_frame": package.get("in_frame") or [],
                "shot_plan": {
                    key: package.get(key)
                    for key in ("subject", "action", "camera", "shot_size", "ending_frame")
                },
            }
            if kind != "still":
                view["motion_prompt"] = _short(package.get("motion_prompt"), 400) or None
            for take in owed:
                session.expunge(take)
            planned.append((scene, kind, since, owed, view))
    ffmpeg = find_ffmpeg(ffmpeg_path)
    rules = list(_bible_rules(bible))[:12]
    faces = bible_face_rule(bible) is not None
    out: list[dict[str, Any]] = []
    for scene, kind, since, owed, view in planned:
        shot = kind != "still"
        clip_scene, still_sha, other_stills = (
            scene_clip_context(engine, storyboard_id, scene) if shot else (None, None, [])
        )
        offered: list[str] = []
        not_offered: list[dict[str, str]] = []
        shown: list[dict[str, Any]] = []
        images: list[str] = []
        for take in owed:  # newest first
            why: str | None = None
            if len(offered) >= LOOK_MAX_CANDIDATES:
                why = f"i se arată o dată doar cele mai noi {LOOK_MAX_CANDIDATES} variante"
            elif _file_sha256(Path(str(take.path))) != take.sha256:
                why = "fișierul de pe disc nu mai este cel cumpărat"
            elif (broken := no_picture(take, ffmpeg)) is not None:
                why = f"nu este o imagine ({broken})"
            elif take.kind in SHOT_TAKE_KINDS:
                verdict = clip_choice(
                    take, scene=clip_scene, still_sha256=still_sha, other_stills=other_stills
                )
                if not verdict["eligible"]:
                    why = str(verdict["why_not_ro"])
            pictures = [] if why else look_pictures(take, ffmpeg_path, work_dir)
            if why is None and not pictures:
                why = "imaginea nu a putut fi pregătită pentru privire (lipsește codorul)"
            if why is not None:
                not_offered.append({"take_id": take.id, "why": _short(why, 300)})
                continue
            offered.append(take.id)
            images += pictures
            shown.append(
                {
                    "candidate": len(offered),
                    "failure_code": take.failure_code,
                    "gate_reasons": [
                        part.strip()
                        for part in str(take.failure_detail or "").split("; ")
                        if part.strip()
                    ][:8],
                }
            )
        out.append(
            {
                "scene_index": scene,
                "kind": kind,
                "since": since,
                "offered": offered,
                "not_offered": not_offered,
                "seen": [take.id for take in owed],
                "images": images,
                "shown": {
                    "film": title,
                    "kind": "shot" if shot else "still",
                    "refused_by": "the clip QC" if shot else "the stills gate",
                    "scene": view,
                    "faces_forbidden": faces,
                    "bible_rules": rules,
                    "candidates": shown,
                },
            }
        )
    return out


def _choice_refused(
    session: Session, row: SceneTake | None, storyboard_id: str, sha_now: str | None
) -> str | None:
    """Why the candidate she chose cannot be approved now, or None: it changed since she was
    shown it (his look came first, it is no longer refused), the film was closed, or its file
    is no longer the one bought."""
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports runbook

    if row is None:
        return "preluarea nu mai există"
    if _looked_by_owner(session, [row.id]):
        return "Proprietarul s-a uitat deja la ea; privirea lui rămâne"
    if row.status != "REJECTED":
        return f"preluarea nu mai este refuzată (acum {row.status})"
    if film_is_closed(session, storyboard_id):
        return "filmul este închis"
    if not row.sha256 or sha_now != row.sha256:
        return "fișierul de pe disc nu mai este cel cumpărat"
    return None


def record_look(
    engine: Engine,
    decision: Mapping[str, Any],
    entry: Mapping[str, Any],
    answer: Mapping[str, Any] | None,
    correlation: str,
) -> dict[str, Any]:
    """Her look, written in one transaction: `LOOK_EVENT` (what she was shown, what was not
    offered to her and why, her decision and reason) and, when she chose, the chosen candidate
    approved by her. ``answer`` None: nothing could be shown to her (NOTHING_TO_SEE).

    Her choice is written as the gate writes its own approval (`stills_stage._set_verdicts`):
    APPROVED with no failure left on the take (the gate's refusal stays on her event), so the
    walk carries on exactly as with a still the gate approved: the film rejoined for a scene he
    chose to animate locally, else the motion step under every money gate. A failure left on
    it would hold the scene for his look (`assembler.owner_chose_flagged_still`), the very wait
    her look replaces. It is not his approval: ``approved_by`` is `DIRECTOR_APPROVER`, no
    `TAKE_DECIDED_EVENT` is written, and his later look on the sheet replaces hers. Not applied
    (``approved`` False, ``not_applied`` why) when the take changed since she was shown it.
    Nothing is bought."""
    from app.providers.runpod.wiring import sync_take_quality  # noqa: PLC0415

    report_id = str(decision.get("report_id") or "")
    storyboard_id = str(decision.get("storyboard_id") or "")
    offered = [str(take) for take in entry.get("offered") or []]
    verb = str((answer or {}).get("decision") or "NOTHING_TO_SEE")
    number = (answer or {}).get("candidate")
    chosen = (
        offered[number - 1]
        if verb == "CHOOSE" and isinstance(number, int) and 0 < number <= len(offered)
        else None
    )
    if answer is not None:
        reason = _short(answer.get("reason"), 600)
    else:
        reason = _short("; ".join(item["why"] for item in entry.get("not_offered") or []), 600)
    with Session(engine) as session:
        path = (
            session.scalar(select(SceneTake.path).where(SceneTake.id == chosen)) if chosen else None
        )
    # Hashed before the write lock is taken: a clip is megabytes.
    sha_now = _file_sha256(Path(str(path))) if path else None
    shown = (entry.get("shown") or {}).get("candidates") or []
    payload: dict[str, Any] = {
        "report_id": report_id,
        "storyboard_id": storyboard_id,
        "media_asset_id": decision.get("media_asset_id"),
        "scene_index": entry.get("scene_index"),
        "kind": entry.get("kind"),
        "since": entry.get("since"),
        "decided_by": DIRECTOR,
        "decision": verb,
        "candidate": number if chosen else None,
        "chosen_take_id": chosen,
        "approved": False,
        "not_applied": None,
        "reason": reason,
        "shown": offered,
        "gate": [
            {"take_id": take, **dict(view)} for take, view in zip(offered, shown, strict=False)
        ],
        "not_offered": list(entry.get("not_offered") or []),
        "seen": [str(take) for take in entry.get("seen") or []],
        **{key: (answer or {}).get(key) for key in ("agent_id", "agent_name", "run_id", "model")},
    }
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        if chosen:
            row = session.get(SceneTake, chosen)
            why = _choice_refused(session, row, storyboard_id, sha_now)
            if why is None and row is not None:
                payload.update(
                    previous_status=row.status,
                    previous_failure_code=row.failure_code,
                    previous_failure_detail=row.failure_detail,
                )
                row.status = "APPROVED"
                row.approved_by = DIRECTOR_APPROVER
                row.failure_code = None
                row.failure_detail = None
                sync_take_quality(session, row, accepted=True, reason=reason)
                row.updated_at = utc_now()
                payload["approved"] = True
            payload["not_applied"] = why
        event = append_event(
            session, LOOK_EVENT, "quality_control_report", report_id, 1, payload, correlation
        )
        payload["event_id"] = str(event.event_id)
    logger.info(
        "director_take_look",
        extra={"report_id": report_id, "decision": verb, "approved": payload["approved"]},
    )
    return payload


# --------------------------------------------------------------------- telling the others


def _title(session: Session, storyboard_id: str) -> str:
    board = session.get(Storyboard, storyboard_id) if storyboard_id else None
    words = str(board.title if board is not None else storyboard_id[:8] or "filmul")
    return words.removeprefix("Storyboard: ").strip() or storyboard_id[:8]


def _open_inbox_notes(session: Session, report_id: str) -> list[AgentMessage]:
    return [
        message
        for message in session.scalars(
            select(AgentMessage).where(
                AgentMessage.status == "OPEN", AgentMessage.to_agent_id.is_(None)
            )
        )
        if not is_for_owner(message)
        and isinstance(message.body_json, dict)
        and message.body_json.get("kind") == INBOX_KIND
        and str(message.body_json.get("report_id") or "") == report_id
    ]


def wait_for_director(
    engine: Engine,
    reading: Mapping[str, Any],
    reason: str,
    correlation: str,
    *,
    words: str | None = None,
) -> dict[str, Any]:
    """She could not decide: nothing is redone and no take is retired. A `WAITING_EVENT`, and
    one open note in her inbox per report (kept, not repeated), so the watchdog asks her again
    later (`app.workflows.passes.director_qc_review`). ``words``: the note's text when it is
    not a report she has not decided (her look at the pictures bought for her REPAIR)."""
    report_id = str(reading.get("report_id") or "")
    storyboard_id = str(reading.get("storyboard_id") or "")
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        title = _title(session, storyboard_id)
        event = append_event(
            session,
            WAITING_EVENT,
            "quality_control_report",
            report_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "media_asset_id": reading.get("media_asset_id"),
                "reason": _short(reason, 500),
            },
            correlation,
        )
        event_id = str(event.event_id)
        standing = _open_inbox_notes(session, report_id)
        if standing:
            note_id = str(standing[0].id)
        else:
            note = post_message(
                session,
                intent="STATUS",
                subject=f"Filmul «{title}» așteaptă decizia Directoarei după controlul calității"[
                    :200
                ],
                body={
                    "kind": INBOX_KIND,
                    "report_id": report_id,
                    "storyboard_id": storyboard_id,
                    "media_asset_id": reading.get("media_asset_id"),
                    "reason": _short(reason, 500),
                },
                body_text=words
                or (
                    f"Filmul «{title}» nu a trecut controlul calității. Nimic nu s-a refăcut și "
                    "nicio preluare nu s-a retras: decizia este a Directoarei. Acum nu a putut "
                    f"decide ({_short(reason, 300)}); studioul o întreabă din nou la trecerea "
                    "următoare."
                ),
                to_agent_id=None,
                correlation_id=correlation,
            )
            note_id = str(note.id)
    logger.info("director_qc_waiting", extra={"report_id": report_id, "reason": reason[:200]})
    return {
        "outcome": "WAITING",
        "reason": reason,
        "event_id": event_id,
        "note_id": note_id,
        "report_id": report_id,
    }


def _verdict_lines(verdicts: Iterable[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in verdicts:
        words = VERDICT_RO.get(str(item.get("verdict")), str(item.get("verdict")))
        if item.get("severity") in SEVERITY_RO:
            words += f", {SEVERITY_RO[str(item.get('severity'))]}"
        if item.get("verdict") == "OWNER_CHOICE" and item.get("owner_choice_confirmed") is False:
            words += " (dar la această scenă nu ai aprobat nimic: rămâne acceptată de ea)"
        if item.get("not_yours"):
            words += "; nu este al ei de trecut cu vederea"
        lines.append(
            f"- «{_short(item.get('text'), 160)}»: {words} ({_short(item.get('reason'), 200)})."
        )
    return lines


def _outcome_line(outcome: str, step: Mapping[str, Any]) -> str:
    repair = step.get("repair") or {}
    if outcome == "ACCEPTED":
        return (
            "Un raport nou al controlului calității (TRECUT, prin decizia ei, cu verdictele de mai "
            "sus) stă acum lângă cel măsurat; filmul merge la publicare după politica canalului, "
            "iar porțile drepturilor și ale afirmațiilor se aplică separat."
        )
    if outcome == "ACCEPT_REFUSED":
        return (
            "Filmul nu se publică: ce a picat la drepturi, la afirmații, la sursa imaginii sau la "
            "fișier nu este al Directoarei de trecut cu vederea; se lămurește la tine sau prin "
            "surse."
        )
    if outcome == "CLOSED":
        closing = step.get("closing") or {}
        items = closing.get("items") or []
        return (
            "Filmul este închis: pentru el nu se mai cumpără nimic"
            + (f"; ce s-a cumpărat ({', '.join(items)}) rămâne în registre" if items else "")
            + "."
        )
    if outcome == "ASKED":
        return (
            "Refacerea plătită hotărâtă de ea așteaptă răspunsul tău pe foaia de filmare, după "
            "regula ta pentru pașii plătiți; fără el nu se cumpără nimic."
        )
    if outcome == "BOUGHT_WAITING":
        return (
            "Ce s-a cumpărat pentru refacerea ei nu este încă într-un film: așteaptă judecata "
            "studioului, iar ce refuză poarta privește Directoarea însăși și alege sau respinge "
            "(privirea ta pe foaia de filmare rămâne mai presus de a ei). Când este aprobat, "
            "studioul duce refacerea mai departe singur, fără să cumpere din nou ce a cumpărat; "
            "filmul care a picat nu se publică."
        )
    if outcome == "REPAIRED":
        if repair.get("requalified") == "PASSED":
            return (
                "Filmul refăcut a trecut controlul calității și merge la publicare, după "
                "politica canalului."
            )
        return "Filmul refăcut nu a trecut controlul calității; Directoarea îl citește din nou."
    return "Nimic din ce a cerut nu se putea reface acum; filmul care a picat nu se publică."


def director_letter(
    engine: Engine,
    reading: Mapping[str, Any],
    step: Mapping[str, Any],
    correlation: str,
    *,
    done_lines: list[str] | None = None,
) -> str | None:
    """The Owner's letter about her decision: a STATUS note in Romanian, never a question.
    One per report, outcome, new film and number of purchases made for her decision (a repair
    his yes or his look continued later is news, and so is every purchase; the same outcome
    twice is not). Returns the letter's id, or None when it was written before."""
    from app.media.shooting_sheet import sheet_url  # noqa: PLC0415 - it imports runbook

    decision = dict(step.get("decision") or {})
    outcome = str(step.get("outcome") or "")
    report_id = str(reading.get("report_id") or "")
    storyboard_id = str(reading.get("storyboard_id") or "")
    new_asset = (step.get("repair") or {}).get("new_asset")
    bought_count = len(step.get("bought_so_far") or [])
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for message in session.scalars(
            select(AgentMessage).where(
                AgentMessage.to_agent_id.is_(None), AgentMessage.intent == "STATUS"
            )
        ):
            body = message.body_json if isinstance(message.body_json, dict) else {}
            if (
                is_for_owner(message)
                and body.get("kind") == LETTER_KIND
                and str(body.get("report_id") or "") == report_id
                and body.get("outcome") == outcome
                and body.get("new_asset") == new_asset
                and int(body.get("bought_count") or 0) == bought_count
            ):
                return None
        title = _title(session, storyboard_id)
        name = str(decision.get("agent_name") or "Directoarea")
        verb = str(decision.get("decision") or "")
        lines = [
            f"Către Owner. {name}, Directoarea, a citit controlul calității filmului «{title}», "
            f"care a picat, și a decis singură: {DECISION_RO.get(verb, verb)}.",
        ]
        if decision.get("resumed"):
            lines[0] = (
                f"Către Owner. Filmul «{title}» a continuat: refacerea hotărâtă de Directoare s-a "
                "reluat de unde rămăsese (după răspunsul tău sau după ce preluarea cumpărată a "
                "fost aprobată), fără să se cumpere din nou ce s-a cumpărat deja."
            )
        if decision.get("summary"):
            lines.append(sentence(_short(decision["summary"], 600)))
        verdicts = list(decision.get("verdicts") or [])
        if verdicts and not decision.get("resumed"):
            lines += ["", "Ce a găsit, constatare cu constatare:", *_verdict_lines(verdicts)]
        if done_lines:
            lines += ["", "Ce s-a făcut:", *done_lines]
        lines += ["", _outcome_line(outcome, step)]
        summary_ro = str(reading.get("summary_ro") or "").strip()
        if summary_ro and not decision.get("resumed"):
            lines += ["", "Raportul măsurat:", summary_ro]
        if storyboard_id:
            lines.append(f"Foaia de filmare: {sheet_url(storyboard_id)}")
        director = agent_for_role(session, "Director")
        subject = {
            "ACCEPTED": f"Directoarea a acceptat filmul «{title}» după controlul calității",
            "ACCEPT_REFUSED": f"Filmul «{title}» nu se publică: ce a picat nu este al Directoarei",
            "CLOSED": f"Directoarea a închis filmul «{title}» după controlul calității",
            "ASKED": f"Filmul «{title}»: refacerea hotărâtă de Directoare așteaptă răspunsul tău",
            "BOUGHT_WAITING": (
                f"Filmul «{title}»: s-a cumpărat pentru refacerea hotărâtă de Directoare; "
                "așteaptă aprobarea preluării noi"
            ),
            "REPAIRED": (
                f"Filmul «{title}» refăcut la decizia Directoarei a trecut controlul calității"
                if (step.get("repair") or {}).get("requalified") == "PASSED"
                else f"Filmul «{title}» refăcut la decizia Directoarei, din nou la control"
            ),
        }.get(outcome, f"Directoarea a decis filmul «{title}» după controlul calității")
        message = post_message(
            session,
            intent="STATUS",
            subject=subject[:200],
            body={
                "kind": LETTER_KIND,
                "report_id": report_id,
                "storyboard_id": storyboard_id,
                "media_asset_id": reading.get("media_asset_id"),
                "decision": verb,
                "outcome": outcome,
                "new_asset": new_asset,
                "bought_count": bought_count,
                "passed_report_id": step.get("passed_report_id"),
                "verdicts": [
                    {"finding": v.get("finding"), "verdict": v.get("verdict")} for v in verdicts
                ],
            },
            body_text="\n".join(lines),
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=correlation,
        )
        return str(message.id)


def look_letter(
    engine: Engine, decision: Mapping[str, Any], look: Mapping[str, Any], correlation: str
) -> str | None:
    """The Owner's letter about one look of hers (`record_look`): a short STATUS note in
    Romanian, never a question: what she was shown, the one she chose or that she rejected
    them all, and why. Once per look; returns the letter's id, or None when it was written."""
    from app.media.shooting_sheet import sheet_url  # noqa: PLC0415 - it imports runbook

    storyboard_id = str(decision.get("storyboard_id") or "")
    event_id = str(look.get("event_id") or "")
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for message in session.scalars(
            select(AgentMessage).where(
                AgentMessage.to_agent_id.is_(None), AgentMessage.intent == "STATUS"
            )
        ):
            body = message.body_json if isinstance(message.body_json, dict) else {}
            if (
                is_for_owner(message)
                and body.get("kind") == LOOK_LETTER_KIND
                and body.get("look_event_id") == event_id
            ):
                return None
        title = _title(session, storyboard_id)
        name = str(look.get("agent_name") or decision.get("agent_name") or "Directoarea")
        scene = look.get("scene_index")
        shot = look.get("kind") != "still"
        shown = len(look.get("shown") or [])
        gate = "controlul clipului" if shot else "poarta imaginilor"
        verb = str(look.get("decision") or "")
        # What she looked at and what she said of it, as Romanian agrees it.
        what, refused, none = {
            (False, True): ("imaginea cumpărată", "o refuzase", "nu o alege, nu intră în film"),
            (True, True): ("clipul cumpărat", "îl refuzase", "nu îl alege, nu intră în film"),
            (False, False): (
                f"cele {count(shown, 'imagine', 'imagini')} cumpărate",
                "le refuzase",
                "nu alege niciuna, niciuna nu intră în film",
            ),
            (True, False): (
                f"cele {count(shown, 'clip', 'clipuri')} cumpărate",
                "le refuzase",
                "nu alege niciunul, niciunul nu intră în film",
            ),
        }[(shot, shown == 1)]
        lines = [
            f"Către Owner. {name}, Directoarea, a privit {what} pentru refacerea scenei {scene} "
            f"a filmului «{title}», pe care {gate} {refused}, și a decis singură: "
            + (f"a ales varianta {look.get('candidate')}." if verb == "CHOOSE" else f"{none}."),
        ]
        if verb == "NOTHING_TO_SEE":
            lines = [
                f"Către Owner. Variantele cumpărate pentru refacerea scenei {scene} a filmului "
                f"«{title}», refuzate de {gate}, nu i-au putut fi arătate Directoarei."
            ]
        if look.get("reason"):
            lines.append(sentence(_short(look["reason"], 600)))
        if verb == "CHOOSE" and look.get("previous_failure_detail"):
            lines.append(f"Ce spusese {gate}: «{_short(look['previous_failure_detail'], 300)}».")
        if verb == "CHOOSE" and look.get("approved"):
            lines.append(
                "Varianta aleasă intră în film fără să se cumpere nimic din nou; dacă te uiți tu "
                "la ea pe foaia de filmare, privirea ta rămâne mai presus de a ei."
            )
        else:
            if verb == "CHOOSE":
                lines.append(f"Alegerea ei nu s-a aplicat: {_short(look.get('not_applied'), 200)}.")
            lines.append(
                "Raportul filmului este din nou al ei: poate reface scena, accepta filmul sau "
                "închide filmul, în limitele tale."
            )
        if storyboard_id:
            lines.append(f"Foaia de filmare: {sheet_url(storyboard_id)}")
        subject = {
            "CHOOSE": f"Directoarea a ales {'clipul' if shot else 'imaginea'} scenei {scene} "
            f"din filmul «{title}»",
            "REJECT": f"Directoarea a respins {'clipurile' if shot else 'imaginile'} noi ale "
            f"scenei {scene} din filmul «{title}»",
        }.get(verb, f"Filmul «{title}»: nimic de privit pentru scena {scene}")
        director = agent_for_role(session, "Director")
        message = post_message(
            session,
            intent="STATUS",
            subject=subject[:200],
            body={
                "kind": LOOK_LETTER_KIND,
                "report_id": decision.get("report_id"),
                "storyboard_id": storyboard_id,
                "look_event_id": event_id,
                "decision": verb,
                "scene_index": scene,
                "chosen_take_id": look.get("chosen_take_id"),
                "approved": bool(look.get("approved")),
            },
            body_text="\n".join(lines),
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=correlation,
        )
        return str(message.id)


def settle_inbox(engine: Engine, report_id: str, outcome: str, correlation: str) -> list[str]:
    """Her decision answers the note that waited for it in her inbox."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        settled: list[str] = []
        for note in _open_inbox_notes(session, report_id):
            resolve_message(
                session,
                note.id,
                resolution=f"Directoarea a decis: {outcome}.",
                resolved_by=DIRECTOR,
                correlation_id=correlation,
            )
            settled.append(str(note.id))
        return settled


def outcome_words(title: str, outcome: Mapping[str, Any]) -> str:
    """One film's walk through her decision, in a sentence for the stage's reason."""
    final = str(outcome.get("outcome") or "")
    repairs = list(outcome.get("repairs") or [])
    bought = sum(len(item.get("bought") or []) for item in repairs)
    words = {
        "ACCEPTED": "Directoarea l-a acceptat după controlul calității",
        "ACCEPT_REFUSED": "Directoarea l-ar publica, dar ce a picat nu este al ei de trecut",
        "CLOSED": "închis de Directoare după controlul calității",
        "ASKED": "refacerea hotărâtă de Directoare așteaptă răspunsul tău",
        "BOUGHT_WAITING": (
            "pentru refacerea hotărâtă de Directoare s-a cumpărat"
            + (f" ({count(bought, 'refacere cumpărată', 'refaceri cumpărate')})" if bought else "")
            + "; preluarea nouă așteaptă aprobarea, apoi refacerea continuă"
        ),
        "REPAIRED": (
            "refăcut la decizia Directoarei ("
            + count(bought, "refacere cumpărată", "refaceri cumpărate")
            + "); controlul calității după refacere: "
            + ("trecut" if outcome.get("passed_asset") else "picat")
        ),
        "NOTHING_DONE": "nimic din ce a cerut Directoarea nu se putea reface acum",
        "WAITING": "așteaptă decizia Directoarei, nimic nu s-a refăcut",
    }.get(final, "Directoarea nu a decis încă")
    return f"Filmul «{title}»: {words}."


__all__ = [
    "BOUGHT_WAIT_DAYS",
    "DECISION_EVENT",
    "DIRECTOR_APPROVER",
    "DROPPED_ON_RESUME",
    "FINAL_OUTCOMES",
    "INBOX_KIND",
    "LETTER_KIND",
    "LOOK_EVENT",
    "LOOK_LETTER_KIND",
    "PENDING_OUTCOMES",
    "REJOIN",
    "WAITING_EVENT",
    "accept_film",
    "annotate_verdicts",
    "bought_not_in_film",
    "bought_since",
    "close_film",
    "confirm_lessons",
    "decision_state",
    "director_letter",
    "film_qc_context",
    "film_takes",
    "is_not_yours",
    "learn_from_decision",
    "lesson_groups",
    "lesson_source",
    "lesson_sources",
    "look_entries",
    "look_letter",
    "look_pictures",
    "looks_of_film",
    "new_approved_take",
    "no_picture",
    "outcome_words",
    "owner_approved_take_ids",
    "owner_scene_choices",
    "protected_redos",
    "record_decision",
    "record_lessons",
    "record_look",
    "repair_list",
    "report_findings",
    "resume_repairs",
    "scene_kinds",
    "settle_inbox",
    "teachable_lessons",
    "wait_for_director",
    "withdraw_overturned_lessons",
]
