"""Idioma de las páginas de pantalla: d3_interface_node pasa ?lang= según su parámetro `language`."""
import os
import re

import yaml

from d3_capabilities.interface_node import page_lang

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PAGES = os.path.join(ROOT, "d3_agent", "pages")
CONFIG = os.path.join(ROOT, "d3_bringup2", "config", "d3.yaml")


def test_page_lang_accepts_naoqi_names_and_iso_codes():
    assert page_lang("English") == "en"
    assert page_lang("Spanish") == "es"
    assert page_lang("es-CO") == "es"
    assert page_lang("pt_BR") == "pt"


def test_page_lang_falls_back_to_english():
    assert page_lang("") == "en"
    assert page_lang(None) == "en"
    assert page_lang("Klingon") == "en"


def test_interface_language_default_matches_driver():
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    assert cfg["d3_interface_node"]["ros__parameters"]["language"] == \
        cfg["d3_driver_node"]["ros__parameters"]["language"]


def test_input_page_has_labels_for_every_code_and_no_hardcoded_buttons():
    with open(os.path.join(PAGES, "input.html"), encoding="utf-8") as fh:
        html = fh.read()
    for code in ("en", "es"):
        assert re.search(r"\b%s:\s*\{" % code, html), "falta la traducción %s en input.html" % code
    for literal in ('button("Sí"', 'button("No"', 'button("Enviar"'):
        assert literal not in html, "texto fijo en input.html: %s" % literal
