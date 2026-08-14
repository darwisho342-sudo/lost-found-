"""Compile simple gettext PO catalogs without external dependencies.

This development fallback exists for Windows machines where GNU gettext is not
installed. Deployment should use Django's ``compilemessages`` command.
"""

from __future__ import annotations

import ast
import struct
from pathlib import Path


def read_catalog(path: Path) -> dict[str, str]:
    catalog: dict[str, str] = {}
    current_key: str | None = None
    plural_key: str | None = None
    current_value: str | None = None
    plural_values: dict[int, str] = {}
    section: str | None = None

    def save() -> None:
        nonlocal current_key, plural_key, current_value, plural_values
        if current_key is not None:
            if plural_key is not None and plural_values:
                catalog[f"{current_key}\0{plural_key}"] = "\0".join(
                    plural_values[index] for index in sorted(plural_values)
                )
            elif current_value is not None:
                catalog[current_key] = current_value
        current_key = plural_key = current_value = None
        plural_values = {}

    for raw_line in [*path.read_text(encoding="utf-8").splitlines(), ""]:
        line = raw_line.strip()
        if line.startswith("msgid "):
            save()
            current_key = ast.literal_eval(line[6:])
            current_value = ""
            section = "id"
        elif line.startswith("msgid_plural "):
            plural_key = ast.literal_eval(line[13:])
            section = "plural_id"
        elif line.startswith("msgstr["):
            index = int(line[7 : line.index("]")])
            plural_values[index] = ast.literal_eval(line.split(" ", 1)[1])
            section = f"str:{index}"
        elif line.startswith("msgstr "):
            current_value = ast.literal_eval(line[7:])
            section = "str"
        elif line.startswith('"'):
            value = ast.literal_eval(line)
            if section == "id":
                current_key = (current_key or "") + value
            elif section == "plural_id":
                plural_key = (plural_key or "") + value
            elif section and section.startswith("str:"):
                index = int(section.split(":", 1)[1])
                plural_values[index] = plural_values.get(index, "") + value
            elif section == "str":
                current_value = (current_value or "") + value
        elif not line:
            save()
            section = None
    return catalog


def write_mo(catalog: dict[str, str], path: Path) -> None:
    items = sorted((key.encode(), value.encode()) for key, value in catalog.items())
    ids = b"\0".join(key for key, _ in items) + b"\0"
    values = b"\0".join(value for _, value in items) + b"\0"
    count = len(items)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    key_data_offset = value_table_offset + count * 8
    value_data_offset = key_data_offset + len(ids)
    key_table = []
    value_table = []
    offset = 0
    for key, _ in items:
        key_table.extend((len(key), key_data_offset + offset))
        offset += len(key) + 1
    offset = 0
    for _, value in items:
        value_table.extend((len(value), value_data_offset + offset))
        offset += len(value) + 1
    output = struct.pack("<7I", 0x950412DE, 0, count, key_table_offset, value_table_offset, 0, 0)
    output += struct.pack(f"<{count * 2}I", *key_table)
    output += struct.pack(f"<{count * 2}I", *value_table)
    output += ids + values
    path.write_bytes(output)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    for language in ("tr", "ar"):
        po_path = root / "locale" / language / "LC_MESSAGES" / "django.po"
        write_mo(read_catalog(po_path), po_path.with_suffix(".mo"))
        print(f"Compiled fallback catalog: {po_path.with_suffix('.mo')}")
