"""Removed: there is no offline substitute for what a platform measured.

This module used to hold `DeterministicAnalyticsAdapter`, which produced plausible-looking
audience figures — views between 1,500 and 65,000, retention between 40% and 75%, CTR between
3.5% and 11% — by hashing a video id, and the analytics router fell back to it whenever no
YouTube credentials were configured.

Those numbers do not stop at the screen. The learning loop reads stored snapshots back,
computes cohort performance from them, and issues Director recommendations that change the
topic and hook weights the studio writes to. A fabricated view count would therefore have
steered real editorial decisions, which is why the adapter was deleted outright rather than
kept behind a flag: a flag that can be turned on is a fabrication that will eventually be
believed. See D-P7-001.

With no analytics provider configured the studio answers HTTP 503 and stores nothing.

The file is kept only as this note so the removal is discoverable from where the adapter used
to live; it defines nothing and can be deleted.
"""

from __future__ import annotations

__all__: list[str] = []
