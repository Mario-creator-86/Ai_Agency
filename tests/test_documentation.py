import importlib.util
import shutil

from app.config import ROOT

spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/check_docs.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_all_original_documents_exist_and_match_reviewed_architecture():
    assert checker.check_docs() == []


def test_unreviewed_architecture_edit_is_detected(tmp_path):
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    master = tmp_path / "docs/architecture/00_MASTER_PROMPT.md"
    master.write_text(
        master.read_text(encoding="utf-8") + "\nChanged requirement\n", encoding="utf-8"
    )
    assert any("Architecture changed" in error for error in checker.check_docs(tmp_path))


def test_missing_specification_is_detected(tmp_path):
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    (tmp_path / "docs/architecture/00_MASTER_PROMPT.md").unlink()
    assert any("Missing:" in error for error in checker.check_docs(tmp_path))


def test_autonomy_semantics_states_the_owner_paid_media_rule_the_code_enforces():
    # 51 says which of its sentences are code; the paid-media gate in may_act is stricter
    # than the modes, so 51 must name it exactly as services.py enforces it.
    from app.models import PAID_MEDIA_APPROVALS
    from app.services import ACTION_RISK_TIERS, PAID_MEDIA_STEPS

    text = (ROOT / "docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md").read_text(encoding="utf-8")
    assert "`paid_media_approval`" in text
    assert "`plan_hash`" in text
    assert "`BLOCKED_NO_PLAN`" in text
    assert "`change_paid_media_approval`" in text
    for action in PAID_MEDIA_STEPS:
        assert f"`{action}` ({ACTION_RISK_TIERS[action]})" in text
        assert ACTION_RISK_TIERS[action] != "T4"
    for value in PAID_MEDIA_APPROVALS:
        assert f"`{value}`" in text
