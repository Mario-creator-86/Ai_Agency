"""Phase 11 — financial evidence and the VR$ double-entry ledger.

Deliberately re-exports nothing. ``app/models.py`` imports ``app.economy.models`` to register the
tables with ``Base.metadata``, and callers import the services they need directly, so that adding
a table here can never quietly change what another module sees.
"""
