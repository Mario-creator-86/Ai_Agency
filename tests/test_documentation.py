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
