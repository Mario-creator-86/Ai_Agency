"""The sentences that send the Owner to the Settings dialog name its tab, in Romanian.

W33 left six Romanian sentences the Owner can read that still said «Settings», the English
name of a dialog the page calls «Setări», and named no tab of it: the analytics refusal, the
reconnect line of a refused Google account, the two refusals of the research pipeline's agent
picker, the media route's failed render and the reference set with no image provider. A
seventh, the workforce proposal the studio cannot apply by itself, said «din Settings». Each
now names the place as `app.wording.SETTINGS_TABS` does, the words the preflight's places and
the page's `settings.js` tabs use.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.analytics.router import ANALYTICS_NOT_CONFIGURED_DETAIL
from app.factual.agent_pipeline import _resolve_agent
from app.media.services import ReferenceSetError, generate_character_reference_set
from app.wording import SETTINGS_TABS, settings_place
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SETTINGS = ROOT / "frontend" / "src" / "settings.js"

#: The English dialog name inside a sentence: «în Settings», «din Settings», «Settings →».
ENGLISH_PLACE = ("în Settings", "din Settings", "Settings →", "in Settings", "from Settings")


def _strings(path: Path) -> list[tuple[int, str]]:
    """Every string literal of a module that is not a docstring, with its line."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) else "{}" for part in node.values
            )
            found.append((node.lineno, text))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            found.append((node.lineno, node.value))
    return found


def test_no_sentence_in_the_studio_sends_the_owner_to_settings_in_english():
    offenders = []
    for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
        for lineno, text in _strings(path):
            if any(phrase in text for phrase in ENGLISH_PLACE):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {text[:80]}")
    assert offenders == []


def test_the_settings_tabs_are_the_pages_own_words():
    settings_js = FRONTEND_SETTINGS.read_text(encoding="utf-8")
    for tab, label in SETTINGS_TABS.items():
        head, words = label.split(" → ", 1)
        assert head == "Setări"
        if tab == "channels":
            continue  # the tab the page's agent adds in W34; the preflight test pins it
        assert f"['{tab}', '{words}']" in settings_js, tab
    assert settings_place("social") == "Setări → Conturi și e-mail"
    with pytest.raises(KeyError):
        settings_place("nowhere")


def test_the_analytics_refusal_names_the_accounts_tab():
    assert "Settings" not in ANALYTICS_NOT_CONFIGURED_DETAIL
    assert "Setări → Conturi și e-mail" in ANALYTICS_NOT_CONFIGURED_DETAIL


def test_the_research_agent_picker_names_the_employees_tab(engine):
    with Session(engine) as session:
        with pytest.raises(ValueError) as nobody:
            _resolve_agent(session, None)
        assert "Settings" not in str(nobody.value)
        assert "Setări → Angajați" in str(nobody.value)

        with pytest.raises(ValueError) as absent:
            _resolve_agent(session, "no-such-agent")
        assert "Settings" not in str(absent.value)


def test_an_agent_with_no_model_is_sent_to_the_employees_tab():
    """The schema keeps an agent's model NOT NULL, so this refusal guards a row written some
    other way; the sentence is read from a session that hands back such a row."""

    class OneRow:
        def get(self, _model, _key):
            return SimpleNamespace(lifecycle="ACTIVE", provider_id=None, model_id=None)

    with pytest.raises(ValueError) as unassigned:
        _resolve_agent(OneRow(), "agent-without-model")  # type: ignore[arg-type]
    assert "Setări → Angajați" in str(unassigned.value)
    assert "Settings" not in str(unassigned.value)


def test_a_reference_set_with_no_image_provider_names_the_media_tab(engine, tmp_path):
    from app.integrations.vault import CredentialVault
    from app.media.models import CharacterBible
    from app.media.services import seed_default_character_bibles
    from app.models import OwnerPolicy

    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        character_id = session.query(CharacterBible.id).first()[0]
    vault = CredentialVault(tmp_path / "words.credentials.key")
    with pytest.raises(ReferenceSetError) as refused:
        generate_character_reference_set(engine, vault, character_id, "words-test")
    assert refused.value.reason == "NO_IMAGE_PROVIDER"
    assert "Setări → Video și sunet" in str(refused.value)
    assert "Settings" not in str(refused.value)
