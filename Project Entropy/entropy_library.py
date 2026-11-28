"""Local libraries for named palettes and presets."""

import json
import sqlite3

from entropy_engine import validate_colors
from entropy_runtime import decode_preset, preset_document


def clean_name(value):
    value = value.strip()
    if not value or len(value) > 64 or any(ord(char) < 32 for char in value):
        raise ValueError("Use a name with 1 to 64 printable characters.")
    return value


class Library:
    def __init__(self, directory):
        self.path = directory / "library.sqlite3"

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=2)
        try:
            connection.execute("""CREATE TABLE IF NOT EXISTS items (
                kind TEXT NOT NULL, key_name TEXT NOT NULL, name TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY (kind, key_name))""")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def list(self, kind):
        connection = self.connect()
        try:
            return [item[0] for item in connection.execute(
                "SELECT name FROM items WHERE kind = ? ORDER BY key_name", (kind,))]
        finally:
            connection.close()

    def store(self, kind, name, data, replace=False):
        name = clean_name(name)
        connection = self.connect()
        try:
            with connection:
                if replace:
                    updated = connection.execute(
                        "UPDATE items SET body = ? WHERE kind = ? AND key_name = ?",
                        (json.dumps(data, ensure_ascii=False), kind, name.casefold()))
                    if not updated.rowcount:
                        raise ValueError("That entry is no longer in the library.")
                else:
                    connection.execute("INSERT INTO items VALUES (?, ?, ?, ?)",
                                       (kind, name.casefold(), name, json.dumps(data, ensure_ascii=False)))
        except sqlite3.IntegrityError as error:
            raise ValueError(f"“{name}” is already in the library.") from error
        finally:
            connection.close()
        return name

    def read(self, kind, name):
        connection = self.connect()
        try:
            result = connection.execute(
                "SELECT body FROM items WHERE kind = ? AND key_name = ?",
                (kind, clean_name(name).casefold())).fetchone()
            if result is None:
                raise ValueError("Select an entry from the library.")
            return json.loads(result[0])
        finally:
            connection.close()

    def rename(self, kind, old, new):
        new = clean_name(new)
        connection = self.connect()
        try:
            with connection:
                updated = connection.execute(
                    "UPDATE items SET key_name = ?, name = ? WHERE kind = ? AND key_name = ?",
                    (new.casefold(), new, kind, clean_name(old).casefold()))
                if not updated.rowcount:
                    raise ValueError("That entry is no longer in the library.")
        except sqlite3.IntegrityError as error:
            raise ValueError(f"“{new}” is already in the library.") from error
        finally:
            connection.close()
        return new

    def save_palette(self, name, colors):
        return self.store("palette", name, validate_colors(colors))

    def palette(self, name):
        return validate_colors(self.read("palette", name))

    def save_preset(self, name, look, export, replace=False):
        return self.store("preset", name, preset_document(look, export), replace)

    def preset(self, name):
        return decode_preset(self.read("preset", name))
