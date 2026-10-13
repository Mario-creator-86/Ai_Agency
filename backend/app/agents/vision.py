"""Who in the studio can look at a picture, and how a picture reaches them.

The Director already had this machinery for her own last look: `model_can_see` reads the
provider's own declaration that a model has vision, and `frames_for` cuts one frame per
scene out of the finished file. Both stay where they were written — they are the Director's
and this module does not move them — but they are no longer hers alone, because quality
control now looks at the pictures before she does.

What is new here is `vision_agent`: the employee the studio can ask to look. Her model
(glm-5.3) declares completion, thinking and tools and no vision at all, so a gate that
asked the Director would never run; the Video Editor, whose department owns the pictures,
may be on a model that sees. The rule is the same as everywhere else: a capability is what
the provider declared for that model, never what its name suggests, and when nobody
declares it the caller is told so rather than handed a pass.

Measured 2026-09-18: nobody in a seeded studio could see either, because every employee was
hired on a text model, so this function returned None on every film ever made and the picture
and character checks reported NOT_APPLICABLE for ever. That is fixed where the studio decides
what a job needs, not here: `app.agents.services.ROLE_PREFERENCES` records that the Video
Editor's role *prefers* vision, and `prefer_capable_models` puts her on a seeing model once
the Owner has admitted one. Preferred, never required — a studio with no seeing model still
hires, still cuts film, and is told here, honestly, that nobody looked.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.editorial import VISION, frames_for, model_can_see
from app.agents.models import Agent, Capability, ModelCapability, ModelRecord, Role
from app.media.toolchain import find_ffmpeg

__all__ = [
    "SPAN_FRAME_WIDTH",
    "VISION",
    "frames_at",
    "frames_for",
    "model_can_see",
    "seeing_model",
    "vision_agent",
]

#: The width quality control cuts a film's frames at: the delivered 1080 px, so a face or a
#: letter the viewer will see is there to be seen. `frames_for` cuts 480 px for one quick
#: look per scene; a 480 px frame of a 1080 px film hides exactly the small faces the
#: Nepal bible forbade.
SPAN_FRAME_WIDTH = 1080


def frames_at(
    path: str,
    ffmpeg_path: str | None,
    frame_numbers: Sequence[int],
    work_dir: Path,
    *,
    width: int = SPAN_FRAME_WIDTH,
) -> dict[int, Path]:
    """The film's frames with these numbers, as PNGs ``width`` px wide, cut in one pass.

    Quality control asks for the first, middle and last frame of every scene's span on the
    film's own timeline (`app.media.qc.span_picture_qc`). One decode of the film selects them
    all by number, so a frame is the frame the viewer sees, not the keyframe nearest a
    timestamp. Empty when there is no encoder, no file, nothing asked or the cut fails: the
    caller reads that as "not looked at", never as a pass.
    """
    ffmpeg = find_ffmpeg(ffmpeg_path)
    file = Path(path)
    wanted = sorted({int(n) for n in frame_numbers if int(n) >= 0})
    if not ffmpeg or not file.is_file() or not wanted:
        return {}
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = "span_frame"
    for old in work_dir.glob(f"{stem}_*.png"):
        old.unlink()
    select_frames = "+".join(f"eq(n\\,{n})" for n in wanted)
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-threads",
                "2",
                "-i",
                str(file),
                "-an",
                "-vf",
                f"select='{select_frames}',scale={width}:-2:flags=lanczos",
                "-fps_mode",
                "passthrough",
                str(work_dir / f"{stem}_%d.png"),
            ],
            capture_output=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    out = [work_dir / f"{stem}_{i}.png" for i in range(1, len(wanted) + 1)]
    # A film shorter than a number asked for returns fewer frames, and then the order no
    # longer says which frame is which: nothing is returned rather than a wrong frame.
    if result.returncode != 0 or not all(frame.is_file() for frame in out):
        return {}
    if (work_dir / f"{stem}_{len(wanted) + 1}.png").exists():
        return {}
    return dict(zip(wanted, out, strict=True))


def vision_agent(session: Session, *prefer_roles: str) -> tuple[str, str] | None:
    """An active employee whose model the provider says can see, or None when there is none.

    `prefer_roles` is asked first, in order, so the department that owns the work does it:
    quality control asks the Video Editor before anyone else. Failing that, any employee
    with a seeing model will do — the question ("is this a picture of what was asked for")
    needs eyes, not a job title. Only the primary model counts: a second or third slot is
    the Owner's configuration for other work, and a run here would not use it.
    """
    seeing = (
        select(Agent, Role.name)
        .join(Role, Agent.role_id == Role.id)
        .join(ModelCapability, ModelCapability.model_id == Agent.model_id)
        .join(Capability, Capability.id == ModelCapability.capability_id)
        .where(Agent.lifecycle == "ACTIVE", Capability.name == VISION)
        .order_by(Agent.hired_at)
    )
    found = session.execute(seeing).all()
    if not found:
        return None
    by_role = {role_name: agent for agent, role_name in found}
    for role_name in prefer_roles:
        agent = by_role.get(role_name)
        if agent is not None:
            return agent.id, agent.display_name
    agent = found[0][0]
    return agent.id, agent.display_name


def _sees(session: Session, model_id: str) -> bool:
    """Whether the provider says this model can look at a picture, and it is available."""
    return bool(
        session.scalar(
            select(ModelCapability.capability_id)
            .join(Capability, Capability.id == ModelCapability.capability_id)
            .join(ModelRecord, ModelRecord.id == ModelCapability.model_id)
            .where(
                ModelCapability.model_id == model_id,
                Capability.name == VISION,
                ModelRecord.is_available.is_(True),
            )
            .limit(1)
        )
    )


def seeing_model(session: Session, agent_id: str, *borrow_from: str) -> str | None:
    """The model an employee looks at a picture with (a `model_record.id`), or None.

    Her own model when the provider says it sees; else the first of her second and third
    slots that sees (the Owner's configuration for her); else the model of the studio's
    seeing employee (`vision_agent`, ``borrow_from`` asked first). The run stays hers whichever
    answers: her identity, her policy and her record, only the model changes, and the run
    records the one that answered (`run_agent_task`'s ``model_id``). A decision about a picture
    needs eyes, and an employee's model may have none: 2026-10-10, the Director was to decide
    herself about the stills the gate had refused, on a model chosen for her writing.
    """
    agent = session.get(Agent, agent_id)
    if agent is None:
        return None
    for model_id in (agent.model_id, agent.secondary_model_id, agent.tertiary_model_id):
        if model_id and _sees(session, model_id):
            return str(model_id)
    looker = vision_agent(session, *borrow_from)
    if looker is None:
        return None
    other = session.get(Agent, looker[0])
    if other is None or not other.model_id or not _sees(session, other.model_id):
        return None
    return str(other.model_id)
