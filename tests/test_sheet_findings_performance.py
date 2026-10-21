"""A film read shares history, but the next read must observe new decisions."""

from app.media import fix_check
from sqlalchemy import event
from sqlalchemy.orm import Session
from test_fix_is_verified import NADIA, NADIA_FIX, decided, rewritten


def test_film_findings_snapshot_preserves_results_and_does_not_repeat_history(engine):
    board = "film-with-history"
    for index in range(1, 6):
        rewritten(engine, board, index, findings=[(NADIA, NADIA_FIX)])
    with Session(engine) as session:
        expected = {i: fix_check.open_findings(session, board, i) for i in range(1, 6)}
        queries = []

        def count(_conn, _cursor, statement, *_args):
            if "FROM domain_event" in statement:
                queries.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            history = fix_check.read_finding_events(session, board)
            actual = {
                i: fix_check.open_findings(session, board, i, events=history) for i in range(1, 6)
            }
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert actual == expected
        assert len(queries) <= 3
    decided(engine, board, [{"scene_index": 1, "verdict": "REAL", "text": "New defect"}])
    with Session(engine) as session:
        history = fix_check.read_finding_events(session, board)
        assert any(
            item["finding"] == "New defect"
            for item in fix_check.open_findings(session, board, 1, events=history)
        )
