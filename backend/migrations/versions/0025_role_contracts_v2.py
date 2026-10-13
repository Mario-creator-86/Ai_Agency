"""The Owner's standing orders reach the employees' contracts (seed version 2).

Data-only migration answering the Owner's direction of 2026-09-11: the sound artist and the
video editor steward their technology — choose it where the channel's policy allows, follow
the Director's written indications, weigh quality, cost and what kept viewers watching — and
the Director decides from measured performance and verifies it weekly, sending her
production indications as messages to the two departments.

The seed file `config/role_contracts.json` moved to version 2. This migration offers the new
seed to every role that still sits at the version-1 seed: a role the Owner has edited (its
contract version moved past the seed it received) keeps the Owner's text, exactly as
`seed_role_contracts` promises. Fresh databases need nothing here — bootstrap seeds version 2
directly. Nothing is deleted; the earlier contract remains in this file's history and in the
role's version column.
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0025_role_contracts_v2"
down_revision = "0024_spending_budget"
branch_labels = None
depends_on = None

#: The seed file, resolved from the repository root regardless of the working directory.
SEED_PATH = Path(__file__).resolve().parents[3] / "config" / "role_contracts.json"

#: The contract fields copied verbatim from the seed into a role's stored contract.
CONTRACT_FIELDS = (
    "reports_to",
    "stages",
    "watch_for",
    "investigate",
    "correct",
    "let_pass",
    "never_let_pass",
    "escalate_when",
    "deliverables",
)


def upgrade() -> None:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    version = int(seed["version"])
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name, contract_version FROM role")).fetchall()
    for role_id, name, contract_version in rows:
        contract = seed["roles"].get(name)
        if contract is None:
            continue
        # A role the Owner edited sits above the seed version it was born from and keeps the
        # Owner's text; an unedited role at an older seed takes the newer one.
        if contract_version is not None and contract_version >= version:
            continue
        work_contract = {field: contract[field] for field in CONTRACT_FIELDS if field in contract}
        connection.execute(
            sa.text(
                "UPDATE role SET work_contract_json = :contract, contract_version = :version "
                "WHERE id = :id"
            ),
            {
                "contract": json.dumps(work_contract, ensure_ascii=False),
                "version": version,
                "id": role_id,
            },
        )


def downgrade() -> None:
    # A contract update is not reversible to a meaningful prior state from here: version 1
    # contracts remain in the repository history and in the role's event trail. Nothing to do.
    pass
