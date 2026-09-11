"""Character Bible carries persona, speech, expressions, behaviour and reference-asset slots.

The bible already described how a recurring employee looks and sounds. The narrative half of
the specification (`24_VISUAL_CONTINUITY_ASSET_SYSTEM.md` personality notes and reference
images, `64_NARRATIVE_PERSONA_RELATIONSHIP_ENGINE.md` traits, speech cadence, quirks, recurring
jokes) had nowhere to live, so a story engine had no stored answer to "how does this character
talk" and would have had to invent one per episode.

Existing rows get empty objects here. `seed_default_character_bibles` fills the canonical seven
from the studio canon on the next read, and never overwrites a field an Owner has edited.
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_character_persona"
down_revision = "0019_provider_resources"
branch_labels = None
depends_on = None

COLUMNS = (
    "personality_json",
    "speech_style_json",
    "expressions_json",
    "behavior_json",
    "reference_assets_json",
)


def upgrade() -> None:
    with op.batch_alter_table("character_bible") as batch:
        for column in COLUMNS:
            batch.add_column(
                sa.Column(column, sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
            )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
