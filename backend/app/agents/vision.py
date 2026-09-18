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
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.editorial import VISION, frames_for, model_can_see
from app.agents.models import Agent, Capability, ModelCapability, Role

__all__ = ["VISION", "frames_for", "model_can_see", "vision_agent"]


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
