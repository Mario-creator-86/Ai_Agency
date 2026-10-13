"""Pages found every day: discovered search addresses and the reason a host cannot be read.

Measured before this revision: page discovery worked only through the search address the
Owner typed by hand per host (migration 0030), and only en/ro Wikipedia carried one; 14 of
the 36 authorised hosts failed retrieval behind bot walls or script-only pages; the latest
live run fetched 0 pages and verified 0 claims, and the studio was living off the 98 claims
verified on 2026-09-12.

Additive, every existing row keeping its meaning:

- ``research_allowed_host.discovered_search_template``: the OpenSearch Suggestions address the
  studio found on the host's own front page (``<link rel="search">`` or ``/opensearch.xml``).
  The Owner's ``search_template`` stays what it was and wins whenever both exist.
- ``research_allowed_host.discovered_at``: when the discovered address was last read.
- ``research_allowed_host.last_test_reason``: a closed-vocabulary reason for a FAILED test
  (HTTP_403, HTTP_ERROR, RATE_LIMITED, SCRIPT_ONLY, NETWORK, OTHER), so the preflight and
  the health report can say why a host is not a source without parsing the detail text.

Numbering: the economy implementer took 0039 (``pricing_truth_and_reservations``) and this
file is 0040, chained after it; ``app.main`` pins 0040 as the head.
"""

import sqlalchemy as sa
from alembic import op

revision = "0040_research_sources"
down_revision = "0039_pricing_truth_and_reservations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable columns need no rebuild on SQLite: plain ADD COLUMN, as 0030 did.
    with op.batch_alter_table("research_allowed_host") as batch:
        batch.add_column(sa.Column("discovered_search_template", sa.String(500), nullable=True))
        batch.add_column(sa.Column("discovered_at", sa.String(40), nullable=True))
        batch.add_column(sa.Column("last_test_reason", sa.String(30), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
