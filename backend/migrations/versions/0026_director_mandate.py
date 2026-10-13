"""The Director's charge and powers, as the Owner ordered them (2026-09-11, second decree).

Data-only migration, two changes:

1. The Director role's mission becomes what the Owner named as her primary charge: growing
   the studio's audience — views and retention — and directing every department in writing,
   from measured analytics, with every decision documented.
2. The role-contract seed moved to version 3 (the Director's powers: direct any employee in
   writing, steer channels and topics from measured performance, request a larger budget
   from the Accountant with the reason written down; the Accountant's matching duty: answer
   every budget request from the books and escalate it to the Owner, who alone decides).
   The new seed is offered to every role still at an older seed version; a role the Owner
   has edited keeps the Owner's text, exactly as `seed_role_contracts` promises.

Fresh databases need none of this: bootstrap creates the roles with the new mission and
seeds version 3 directly. Nothing is deleted.
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0026_director_mandate"
down_revision = "0025_role_contracts_v2"
branch_labels = None
depends_on = None

SEED_PATH = Path(__file__).resolve().parents[3] / "config" / "role_contracts.json"

DIRECTOR_MISSION = (
    "Grow the studio's audience: raising views and retention is her primary charge. She "
    "directs every department in writing, steers channels and topics from measured "
    "analytics, and documents every decision"
)

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
    connection = op.get_bind()

    # 1. The Director's mission, as ordered.
    connection.execute(
        sa.text("UPDATE role SET mission = :mission WHERE name = 'Director'"),
        {"mission": DIRECTOR_MISSION},
    )

    # 2. The version-3 contract seed, offered to roles still at an older seed version.
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    version = int(seed["version"])
    rows = connection.execute(sa.text("SELECT id, name, contract_version FROM role")).fetchall()
    for role_id, name, contract_version in rows:
        contract = seed["roles"].get(name)
        if contract is None:
            continue
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
    # A mandate is not taken back by rewriting rows; the Owner's decision stands until they
    # change it. Nothing to revert to.
    pass
