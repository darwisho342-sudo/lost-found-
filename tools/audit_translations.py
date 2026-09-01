"""Report user-facing gettext source strings missing from local PO catalogs.

This complements Django's ``makemessages`` command on local Windows machines
where the external GNU gettext tools are not installed. It does not modify PO
files and is intentionally limited to literal gettext calls and Django template
translation tags.
"""

from __future__ import annotations

import ast
from io import StringIO
from pathlib import Path
import tokenize

from django.utils.translation.template import templatize

from compile_locales import read_catalog


ROOT = Path(__file__).resolve().parents[1]


def literal_messages(tree: ast.AST) -> set[str]:
    messages: set[str] = set()
    singular_calls = {"_": 0, "gettext": 0, "gettext_lazy": 0, "pgettext": 1}
    plural_calls = {"ngettext": (0, 1), "ngettext_lazy": (0, 1), "npgettext": (1, 2)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        positions = ()
        if node.func.id in singular_calls:
            positions = (singular_calls[node.func.id],)
        elif node.func.id in plural_calls:
            positions = plural_calls[node.func.id]
        for position in positions:
            if position < len(node.args):
                value = node.args[position]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    messages.add(value.value)
    return messages


def source_messages() -> set[str]:
    messages: set[str] = set()
    for path in (*((ROOT / "items").rglob("*.py")), *((ROOT / "config").rglob("*.py"))):
        if "migrations" in path.parts or path.name.startswith("test"):
            continue
        messages.update(literal_messages(ast.parse(path.read_text(encoding="utf-8"))))
    for path in (ROOT / "templates").rglob("*.html"):
        translated_python = templatize(path.read_text(encoding="utf-8"), origin=str(path))
        tokens = list(tokenize.generate_tokens(StringIO(translated_python).readline))
        call_positions = {
            "gettext": (0,), "pgettext": (1,),
            "ngettext": (0, 1), "npgettext": (1, 2),
        }
        for index, token in enumerate(tokens):
            if token.type != tokenize.NAME or token.string not in call_positions:
                continue
            arguments = []
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor].string != ")":
                if tokens[cursor].type == tokenize.STRING:
                    arguments.append(ast.literal_eval(tokens[cursor].string))
                cursor += 1
            for position in call_positions[token.string]:
                if position < len(arguments):
                    messages.add(arguments[position])
    return {message for message in messages if message}


if __name__ == "__main__":
    messages = source_messages()
    failed = False
    for language in ("tr", "ar"):
        catalog = read_catalog(ROOT / "locale" / language / "LC_MESSAGES" / "django.po")
        catalog_ids = {
            message
            for key in catalog
            for message in key.split("\0")[:2]
        }
        missing = sorted(messages - catalog_ids)
        print(f"{language}: {len(messages)} source messages; {len(missing)} missing")
        for message in missing:
            print(f"  {message}")
        failed = failed or bool(missing)
    raise SystemExit(1 if failed else 0)
