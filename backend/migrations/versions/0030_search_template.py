"""A search address per authorised site, so the studio finds pages instead of guessing them.

The Researcher named pages from memory and most of them did not exist: three guesses on
UNESCO, DeepMind, Anthropic and Hugging Face returned 404 on the first day of the clean
studio, and nothing was read. A site's own search — in the OpenSearch Suggestions JSON
format most encyclopaedias and documentation sites serve — answers the studio's honest
identity and returns pages that exist. The Owner records that address here, per host, with
`{query}` where the words go; the studio asks it before the Researcher plans, and the plan
starts from pages that are real.
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_search_template"
down_revision = "0029_editorial_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research_allowed_host") as batch:
        batch.add_column(sa.Column("search_template", sa.String(500), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
