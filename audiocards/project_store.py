from __future__ import annotations
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from .models import Card, Config
from .utils import atomic_json

SCHEMA_VERSION = 1

class ProjectStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        with closing(self._connect()) as con:
            current = con.execute('PRAGMA user_version').fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RuntimeError('Archivio creato da una versione piu recente. Usare quella versione.')
            if current < SCHEMA_VERSION:
                if existed:
                    with closing(sqlite3.connect(str(path.with_suffix('.before-migration.sqlite')))) as backup:
                        con.backup(backup)
                with con:
                    con.execute('BEGIN IMMEDIATE')
                    con.execute('''CREATE TABLE IF NOT EXISTS projects (
                        project_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        payload TEXT NOT NULL, updated_at TEXT NOT NULL)''')
                    con.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def _connect(self):
        con = sqlite3.connect(str(self.path), timeout=10)
        con.execute('PRAGMA journal_mode=DELETE')
        con.execute('PRAGMA synchronous=FULL')
        return con

    def save(self, name: str, raw_text: str, cards: list[Card], config: Config,
             project_id: str | None = None, last_output: str | None = None, input_format: str = 'auto') -> str:
        project_id = project_id or uuid.uuid4().hex
        payload = {
            'schema_version': SCHEMA_VERSION, 'project_id': project_id,
            'name': name.strip() or 'Progetto', 'raw_text': raw_text,
            'cards': [asdict(c) for c in cards], 'config': asdict(config),
            'last_output': last_output, 'input_format': input_format,
        }
        self.save_payload(payload)
        return project_id

    def save_payload(self, payload: dict):
        validate_project(payload)
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as con, con:
            con.execute('''INSERT INTO projects VALUES (?,?,?,?)
                ON CONFLICT(project_id) DO UPDATE SET name=excluded.name,
                payload=excluded.payload, updated_at=excluded.updated_at''',
                (payload['project_id'], payload['name'], json.dumps(payload, ensure_ascii=False), now))

    def list_projects(self) -> list[tuple]:
        with closing(self._connect()) as con:
            return con.execute('SELECT project_id,name,updated_at FROM projects ORDER BY updated_at DESC').fetchall()

    def load(self, project_id: str) -> dict:
        with closing(self._connect()) as con:
            row = con.execute('SELECT payload FROM projects WHERE project_id=?', (project_id,)).fetchone()
        if not row:
            raise ValueError('Progetto non trovato.')
        payload = json.loads(row[0]); validate_project(payload)
        return payload


def validate_project(payload: dict):
    if not isinstance(payload, dict) or payload.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Formato progetto non supportato.')
    if not isinstance(payload.get('name'), str) or not isinstance(payload.get('project_id'), str):
        raise ValueError('Progetto incompleto.')
    if not isinstance(payload.get('raw_text', ''), str) or len(payload.get('raw_text', '')) > 2_000_000:
        raise ValueError('Testo progetto non valido.')
    if payload.get('input_format', 'auto') not in ('auto', 'pipe', 'qa', 'tsv', 'csv'):
        raise ValueError('Formato di input del progetto non valido.')
    cards = payload.get('cards', [])
    if not isinstance(cards, list) or len(cards) > 10000:
        raise ValueError('Numero schede non valido.')
    for item in cards:
        Card(**item)
    Config(**payload['config'])


def import_project(path: Path) -> dict:
    if path.stat().st_size > 15_000_000:
        raise ValueError('File progetto troppo grande.')
    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    validate_project(payload)
    return payload


def export_project(path: Path, payload: dict):
    validate_project(payload)
    atomic_json(path, payload)
