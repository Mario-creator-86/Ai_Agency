"""The studio's own approved cadres, kept as a training set for a LoRA of its own (2026-10-11).

The Owner, after reading the LTX-2 trainer with the session: «Strângem setul de date de acum,
antrenăm după ~100 de clipuri». An image-to-video LoRA on the studio's own approved stills and
clips is the lever beyond prompts and reference portraits for the serial's faces and look, and
the trainer wants captioned clips — which the studio has better than any auto caption: the
exact prompt each take was bought on. So every take the gates let through (a still the
stills gate or the Owner approved, a shot the clip QC or the Owner approved) is written, once,
to a manifest beside the studio's media (`manifest.jsonl` under the media root's `training`
folder): the take, its film and scene, its file and hash, the scene's prompt as it stands at
that moment and whether the take was bought on exactly those words, the camera move, the
seconds, the resolution, the model, the series look's version and who approved it.

Nothing is trained here and nothing is bought: the training itself is his card, when the
serial has about `MILESTONE_CLIPS` approved clips (one STATUS letter then, once). A take
whose file is gone is left out; a take written once is never written twice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: Where the manifest lives, under the media root.
MANIFEST_RELATIVE = Path("training") / "manifest.jsonl"
#: The kinds that train a video model: the first frame and the clip.
TRAINING_KINDS: tuple[str, ...] = ("still", "test_shot", "motion")
#: How many approved serial clips make the training worth his card.
MILESTONE_CLIPS = 100
#: The events the pass leaves.
SAMPLE_EVENT = "training.samples_added"
MILESTONE_EVENT = "training.milestone_reached"
LETTER_KIND = "training_set_milestone"


def manifest_path(settings: Any) -> Path:
    from app.media.disk import media_root  # noqa: PLC0415

    return media_root(settings) / MANIFEST_RELATIVE


def read_manifest(path: Path) -> list[dict[str, Any]]:
    """The manifest's rows, oldest first; a line that is not JSON is skipped, never raised."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _prompt_of(package: dict[str, Any], kind: str) -> str:
    key = "still_prompt" if kind == "still" else "motion_prompt"
    return " ".join(str(package.get(key) or "").split())


@watchdog_pass("training_set", order=170, on_error={"added": 0, "clips": 0})
def collect_training_samples(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.agents.memory import agent_for_role  # noqa: PLC0415
    from app.agents.messages import post_message  # noqa: PLC0415
    from app.db import lock_for_write  # noqa: PLC0415
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.media.assembler import still_fields, take_hash  # noqa: PLC0415 - a large module
    from app.media.models import SceneTake, Storyboard, StoryboardScene  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415

    path = manifest_path(context.settings)
    known = {str(row.get("take_id")) for row in read_manifest(path)}
    added: list[dict[str, Any]] = []
    with Session(context.engine) as session:
        takes = session.scalars(
            select(SceneTake)
            .where(SceneTake.status == "APPROVED", SceneTake.kind.in_(TRAINING_KINDS))
            .order_by(SceneTake.created_at)
        ).all()
        boards: dict[str, dict[str, Any]] = {}
        for take in takes:
            if str(take.id) in known or not take.path or not Path(str(take.path)).is_file():
                continue
            board_id = str(take.storyboard_id)
            if board_id not in boards:
                board = session.get(Storyboard, board_id)
                script = (
                    session.get(ScriptDraft, board.script_draft_id)
                    if board is not None and board.script_draft_id
                    else None
                )
                boards[board_id] = {
                    "title": str(board.title) if board is not None else "",
                    "serial": is_serial_film(board, script),
                }
            scene = session.scalar(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == board_id,
                    StoryboardScene.scene_index == int(take.scene_number),
                )
            )
            package = dict(scene.prompt_json or {}) if scene is not None else {}
            prompt = _prompt_of(package, str(take.kind))
            matches = None
            if take.kind == "still" and prompt:
                # Bought on exactly these words (no reference picture drawn from): the hash
                # the stills step wrote. A still drawn from a character's reference carries
                # the picture in its hash and reads as not matching; its words are still kept.
                matches = take_hash(still_fields(prompt, None), take.model_id) == take.prompt_hash
            added.append(
                {
                    "take_id": str(take.id),
                    "kind": str(take.kind),
                    "storyboard_id": board_id,
                    "film_title": boards[board_id]["title"],
                    "serial": bool(boards[board_id]["serial"]),
                    "scene_index": int(take.scene_number),
                    "path": str(take.path),
                    "sha256": take.sha256,
                    "prompt": prompt,
                    "prompt_hash": take.prompt_hash,
                    "prompt_matches": matches,
                    "camera_move": str(package.get("camera_move") or "") or None,
                    "seconds": take.seconds,
                    "resolution": take.resolution,
                    "model_id": take.model_id,
                    "series_look_version": package.get("series_look_version"),
                    "approved_by": take.approved_by,
                    "approved_at": str(take.updated_at or take.created_at),
                    "written_at": utc_now(),
                }
            )
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in added:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    rows = read_manifest(path)
    clips = sum(
        1 for row in rows if row.get("serial") and row.get("kind") in ("test_shot", "motion")
    )
    milestone = False
    if added or clips >= MILESTONE_CLIPS:
        with Session(context.engine) as session, session.begin():
            lock_for_write(session)
            if added:
                append_event(
                    session,
                    SAMPLE_EVENT,
                    "training_set",
                    "manifest",
                    1,
                    {
                        "added": len(added),
                        "total": len(rows),
                        "serial_clips": clips,
                        "kinds": sorted({row["kind"] for row in added}),
                        "path": str(path),
                    },
                    context.correlation_id,
                )
            if clips >= MILESTONE_CLIPS:
                reached = session.scalar(
                    select(DomainEvent.event_id)
                    .where(DomainEvent.event_type == MILESTONE_EVENT)
                    .limit(1)
                )
                if reached is None:
                    milestone = True
                    append_event(
                        session,
                        MILESTONE_EVENT,
                        "training_set",
                        "manifest",
                        1,
                        {"serial_clips": clips, "total": len(rows), "path": str(path)},
                        context.correlation_id,
                    )
                    director = agent_for_role(session, "Director")
                    post_message(
                        session,
                        intent="STATUS",
                        subject="Setul de antrenare LTX are destule clipuri: decizia ta",
                        body={"kind": LETTER_KIND, "serial_clips": clips, "total": len(rows)},
                        body_text=(
                            f"Către Owner. Setul de antrenare al studioului are {clips} clipuri "
                            f"aprobate ale serialului ({len(rows)} înregistrări în total, cu "
                            "prompturile lor exacte). Așa cum ai hotărât pe 11 octombrie 2026, "
                            "antrenarea unui LoRA imagine→video pentru personajele și look-ul "
                            "serialului se face doar cu decizia ta: urmează cardul cu costul "
                            "ei (ore de GPU pe RunPod). Până atunci nu se cheltuie nimic."
                        ),
                        from_agent_id=director.id if director else None,
                        to_owner=True,
                        correlation_id=context.correlation_id,
                    )
    return {"added": len(added), "total": len(rows), "clips": clips, "milestone": milestone}
