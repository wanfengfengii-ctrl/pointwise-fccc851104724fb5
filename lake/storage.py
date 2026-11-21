from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


class LakeError(ValueError):
    def __init__(self, code: str, message: str, *, missing: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.missing = missing


def require_name(value: str, label: str, *, code: str = 'invalid_name') -> None:
    if not isinstance(value, str) or not value.strip():
        raise LakeError(code, f'{label} must be a nonblank string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise LakeError(code, f'{label} must contain valid Unicode text') from error


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), sort_keys=True)


def encode_quantity(value: int | None) -> str | None:
    # Text keeps quantities outside SQLite's fixed-width integer domain exact.
    return None if value is None else hex(value)


def decode_quantity(value: str | None) -> int | None:
    return None if value is None else int(value, 16)


Checkpoint = Callable[[str, str], None]


def notify(checkpoint: Checkpoint | None, phase: str, supplement_id: str) -> None:
    if checkpoint is not None:
        checkpoint(phase, supplement_id)


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    @contextmanager
    def transaction(self, *, write: bool = False, create: bool = False) -> Iterator[sqlite3.Connection]:
        mode = 'rwc' if create else 'rw' if write else 'ro'
        conn = sqlite3.connect(f'{self.path.as_uri()}?mode={mode}', uri=True, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys = ON')
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
