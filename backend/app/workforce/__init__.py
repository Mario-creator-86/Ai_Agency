"""Phase 8 — evidence-driven workforce changes and safe reassignment.

Deliberately re-exports nothing. ``app/models.py`` imports ``app.workforce.models`` to register
the tables, and pulling the router in from here would drag the service layer — and through it
``app.agents.models`` — into that import, closing a cycle.
"""
