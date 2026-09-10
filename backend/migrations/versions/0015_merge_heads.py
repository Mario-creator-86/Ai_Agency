"""Merge the two parallel migration branches into a single head.

Two concurrent AI sessions each added a revision after 0011_claim_attribution without
seeing the other: 0012_channel_verification and 0012_workforce (-> 0013_story ->
0014_runbook). Alembic refuses `upgrade head` with multiple heads, which broke every
test fixture and bootstrap. This revision merges both branches; it applies no schema
of its own — both parents are meant to have run first.
"""

revision = "0015_merge_heads"
down_revision = ("0012_channel_verification", "0014_runbook")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of unwinding merged branches")
