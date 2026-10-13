"""The hero preview must include priced motion that is waiting for its stills."""

import pytest
from app.media.assembler import hero_gate
from app.models import OwnerPolicy
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    ("remaining_status", "remaining_credits", "explicit_cap", "requires_owner"),
    [
        ("NEEDS_STILL", 60, None, True),
        ("NEEDS_STILL", 0, None, False),
        ("NEEDS_STILL", 60, 0, False),
        ("NEEDS_STILL", 60, 100, True),
        ("BOUGHT", 60, None, False),
    ],
)
def test_pending_priced_motion_is_not_presented_as_a_free_step(
    engine, remaining_status, remaining_credits, explicit_cap, requires_owner
):
    plan = {
        "hero_scene": 1,
        "credit_usd": 0.01,
        "steps": {"motion": {"cap_credits": 0}},
        "scenes": [
            {"scene_index": 1, "kind": "LIVE", "status": "NEEDS_STILL", "credits": 100},
            {
                "scene_index": 2,
                "kind": "LIVE",
                "status": remaining_status,
                "credits": remaining_credits,
            },
        ],
    }
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.autonomy_stopped = False
        policy.paid_media_approval = "EVERY_PAID_STEP"
    with Session(engine) as session:
        preview = hero_gate(
            session,
            plan,
            storyboard_id="preview-only",
            plan_hash="unchanged-plan",
            cap_credits=explicit_cap,
        )
        assert preview["rule_accepts"] is not requires_owner
        assert preview["policy_status"] == ("NEEDS_APPROVAL" if requires_owner else "ALLOWED")
        assert not session.new and not session.dirty
