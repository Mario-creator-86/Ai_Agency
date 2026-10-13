"""Withdraw the unearned health and availability claims written by the initial seed.

`seed_initial_workforce` used to write the seeded Ollama endpoint as HEALTHY with a
`last_health_check` timestamp, and its three configured models as available with a
`last_verified` timestamp, without ever contacting Ollama. A studio on a machine with no
Ollama installed therefore displayed a healthy provider and three verified models — the
same class of falsehood as the "configured" YouTube channel corrected in 0007.

This migration is data-only. It resets the seeded rows to the state the seed should have
written, so the interface stops asserting an observation nobody made. The reset direction
is deliberately conservative: an owner whose Ollama really is running restores the true
state with one provider check, whereas leaving the claim in place would keep asserting
something false on every machine where it is not.

Rows the provider genuinely declared during a model sync (`discovery_method =
'DECLARED_BY_PROVIDER'`) are left untouched — those were measured.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_unverified_seeded_provider"
down_revision = "0008_integration_settings"
branch_labels = None
depends_on = None

SEEDED_MODELS = ("glm-5.2:cloud", "kimi-k2.6:cloud", "qwen3-coder:480b-cloud")


def upgrade() -> None:
    connection = op.get_bind()

    seeded_providers = [
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT id FROM provider_record "
                "WHERE name = 'local-ollama' AND provider_type = 'OLLAMA'"
            )
        )
    ]
    if not seeded_providers:
        return

    for provider_id in seeded_providers:
        # A model row still carrying the seed's own signature was never verified: the seed
        # wrote DECLARED_BY_PROVIDER without asking the provider anything.
        connection.execute(
            sa.text(
                "UPDATE model_record "
                "SET is_available = 0, last_verified = NULL, "
                "    discovery_method = 'SEEDED_UNVERIFIED', "
                "    notes = notes || '; not verified against the provider' "
                "WHERE provider_id = :provider_id "
                "  AND discovery_method = 'DECLARED_BY_PROVIDER' "
                "  AND model_name IN :names "
                "  AND notes NOT LIKE '%not verified against the provider%'"
            ).bindparams(sa.bindparam("names", expanding=True)),
            {"provider_id": provider_id, "names": list(SEEDED_MODELS)},
        )
        # The provider was recorded HEALTHY by the seed itself; no request was ever made.
        connection.execute(
            sa.text(
                "UPDATE provider_record "
                "SET status = 'NOT_CONFIGURED', last_health_check = NULL "
                "WHERE id = :provider_id AND status = 'HEALTHY'"
            ),
            {"provider_id": provider_id},
        )


def downgrade() -> None:
    raise NotImplementedError("Restoring unverified health claims is not supported")
