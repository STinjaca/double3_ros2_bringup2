"""Reglas locales (no versionadas) de check_public_safety.py: rangos y términos extra."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_public_safety as cps  # noqa: E402


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.fixture
def rules(tmp_path, monkeypatch):
    path = write(tmp_path / "rules.local", "# comentario\nnet: 198.51.100.0/24\nterm: Sitio-Secreto  # inline\n")
    monkeypatch.setenv("PUBLIC_SAFETY_LOCAL", path)
    return cps.load_local_rules()


def test_missing_local_file_means_no_extra_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_SAFETY_LOCAL", str(tmp_path / "no-existe"))
    assert cps.load_local_rules() == ([], [])


def test_local_rules_are_parsed(rules):
    nets, terms = rules
    assert [str(n) for n in nets] == ["198.51.100.0/24"]
    assert terms == ["sitio-secreto"]


def test_extra_net_and_term_are_blocked(tmp_path, rules):
    nets, terms = rules
    f = write(tmp_path / "a.md", "host 198.51.100.7\nvisita al SITIO-SECRETO\nnada\n")
    problems = cps.check_file(f, nets, terms)
    assert any("línea 1" in p and "198.51.100.7" in p for p in problems)
    assert any("línea 2" in p and "término" in p for p in problems)
    assert not any("línea 3" in p for p in problems)


def test_terms_cannot_be_skipped_with_public_safe(tmp_path, rules):
    nets, terms = rules
    f = write(tmp_path / "b.py", "x = 'sitio-secreto'  # public-safe\n")
    assert cps.check_file(f, nets, terms)


def test_term_in_file_path_is_blocked(tmp_path, rules):
    nets, terms = rules
    d = tmp_path / "maps"
    d.mkdir()
    f = write(d / "sitio-secreto_piso1.yaml", "resolution: 0.05\n")
    assert any(p.startswith("ruta:") for p in cps.check_file(f, nets, terms))


def test_problem_messages_do_not_echo_the_term(tmp_path, rules):
    nets, terms = rules
    f = write(tmp_path / "c.md", "sitio-secreto\n")
    assert all("sitio-secreto" not in p.lower() for p in cps.check_file(f, nets, terms))


def test_local_rules_file_itself_is_rejected(tmp_path):
    f = write(tmp_path / cps.LOCAL_FILE, "term: x\n")
    assert cps.check_file(f)


def test_invalid_line_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_SAFETY_LOCAL", write(tmp_path / "bad", "hola\n"))
    with pytest.raises(SystemExit):
        cps.load_local_rules()


def test_default_rules_still_apply_without_local_file(tmp_path):
    f = write(tmp_path / "d.md", "ip 10.1.2.3\n")  # public-safe: IP de prueba, se escribe en un temporal
    assert cps.check_file(f)
