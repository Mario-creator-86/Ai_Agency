"""Correct historical records that asserted external state which never existed.

Data-only migration answering docs/project/AUDIT_2026-09-09_EXTERNAL.md (decision D-AUDIT-001).

Existing databases contain three classes of untrue rows produced by the pre-audit code:

1. Channels seeded with invented remote IDs (``UC_main_factual_studio_01`` /
   ``UC_office_serial_studio_02``) and a hardcoded ``CONFIGURED`` status, although no channel
   was ever configured and no credentials were ever stored.
2. Publications recorded as ``PUBLISHED`` with ``yt_sim_*`` identifiers and
   ``https://youtube.com/shorts/...`` URLs. Those uploads were simulated locally; the URLs
   resolve to nothing. Left as-is, the UI would keep offering them as working links.
3. Quality-control reports produced by the previous gate, which read the resolution and
   duration the renderer had written to the database instead of measuring the file. Per
   ``50_CONTENT_GATE_MATRIX.md`` ("gate immutability"), a pass certifies a specific content and
   policy version; the gate itself changed, so every earlier pass is invalidated and must be
   re-run rather than inherited.

Nothing is deleted: rows are corrected in place so the history remains auditable.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_correct_fabricated_records"
down_revision = "0006_phase6_publishing"
branch_labels = None
depends_on = None

FABRICATED_CHANNEL_IDS = ("UC_main_factual_studio_01", "UC_office_serial_studio_02")


def upgrade() -> None:
    connection = op.get_bind()

    # 1. Channels: drop invented identity, fall back to NOT_CONFIGURED.
    connection.execute(
        sa.text(
            """
            UPDATE channel_record
               SET remote_channel_id = NULL,
                   credentials_ref = NULL,
                   status = 'NOT_CONFIGURED',
                   last_sync_at = NULL
             WHERE remote_channel_id IN (:a, :b)
                OR (credentials_ref IS NULL AND status <> 'NOT_CONFIGURED')
            """
        ),
        {"a": FABRICATED_CHANNEL_IDS[0], "b": FABRICATED_CHANNEL_IDS[1]},
    )

    # 2. Publications: simulated uploads are not publications.
    connection.execute(
        sa.text(
            """
            UPDATE publication_record
               SET status = 'PUBLISHED_SIMULATED',
                   remote_url = NULL,
                   error_detail = 'Corrected by migration 0007: this upload was simulated '
                                  || 'locally; no video exists on any platform.'
             WHERE remote_video_id LIKE 'yt_sim_%'
                OR remote_video_id LIKE 'sim:%'
                OR remote_url LIKE '%yt_sim_%'
            """
        )
    )

    # 3. Quality control: invalidate passes granted by the previous, self-referential gate.
    connection.execute(
        sa.text(
            """
            UPDATE quality_control_report
               SET status = 'INVALIDATED',
                   failure_reasons_json = '["Invalidated by migration 0007: this report was '
                                          || 'produced by a QC gate that read the renderer''s '
                                          || 'own metadata instead of measuring the file. '
                                          || 'Re-run QC to obtain a valid verdict."]'
             WHERE status = 'PASSED'
            """
        )
    )


def downgrade() -> None:
    """No downgrade.

    This migration removes assertions about external state that were never true. Restoring them
    would mean writing false data back into the database, so the downgrade is intentionally a
    no-op rather than a reversal.
    """
