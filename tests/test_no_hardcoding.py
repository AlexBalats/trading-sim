"""Hard rule 1: every design decision lives in config/, never in the Python code.

Fails if a card id, card name, rarity, tier or persona type from the YAML
appears as text in sim/ or analysis/.
"""

import ast
import re

from conftest import ROOT


def code_files():
    return sorted((ROOT / "sim").glob("*.py")) + sorted((ROOT / "analysis").glob("*.py"))


def string_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_no_card_ids_or_names_in_code(config):
    for path in code_files():
        text = path.read_text(encoding="utf-8")
        for c in config.cards.cards:
            assert not re.search(rf"\b{re.escape(c.id)}\b", text), f"{c.id} appears in {path.name}"
            assert c.name not in text, f"'{c.name}' appears in {path.name}"


def test_no_design_words_as_strings_in_code(config):
    words = (set(config.personas.types) | {c.rarity for c in config.cards.cards}
             | set(config.cards.tracked))
    for path in code_files():
        found = string_literals(path) & words
        assert not found, f"{sorted(found)} written into {path.name}; it belongs in config/"
