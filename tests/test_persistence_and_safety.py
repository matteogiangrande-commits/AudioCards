from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time
import pytest
from audiocards.project_store import ProjectStore, export_project, import_project
from audiocards.models import Config
from audiocards.utils import (safe_filename, atomic_json, CancelToken, Cancelled, run_command, InstanceLock)
from conftest import dataset

@pytest.mark.parametrize('name', ['CON','nul.txt','COM1','LPT9.mp3','NUL','A/B:C*D?','..','  '])
def test_safe_filenames(name):
    safe = safe_filename(name)
    assert safe and '/' not in safe and '\\' not in safe
    assert not safe.endswith('.')
    assert safe.upper().split('.')[0] not in ('CON','NUL','COM1','LPT9')


def test_sqlite_roundtrip_and_copy(tmp_path):
    cards,_ = dataset(3)
    root = tmp_path/'Progetto con spazi \u00e8'
    store = ProjectStore(root/'data'/'projects.sqlite')
    pid = store.save('Esempio', 'Q | A', cards, Config(), last_output='Esempio/run1')
    assert store.load(pid)['cards'] == [asdict(c) for c in cards]
    copied = tmp_path/'copia'
    shutil.copytree(root, copied)
    other = ProjectStore(copied/'data'/'projects.sqlite')
    assert other.load(pid) == store.load(pid)
    assert len(other.list_projects()) == 1


def test_project_json_export_import(tmp_path):
    cards,_ = dataset(2)
    store = ProjectStore(tmp_path/'db.sqlite')
    pid = store.save('name', 'text', cards, Config())
    path = tmp_path/'project.json'
    export_project(path, store.load(pid))
    assert import_project(path) == store.load(pid)


def test_future_schema_fails_without_overwriting(tmp_path):
    path = tmp_path/'db.sqlite'
    with sqlite3.connect(path) as con: con.execute('PRAGMA user_version=999')
    with pytest.raises(RuntimeError): ProjectStore(path)
    with sqlite3.connect(path) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 999


def test_atomic_json_leaves_no_part(tmp_path):
    path = tmp_path/'a.json'
    atomic_json(path, {'v':1})
    with pytest.raises(ValueError): atomic_json(path, {'v':float('nan')})
    assert json.loads(path.read_text()) == {'v':1}
    assert list(tmp_path.glob('*.part')) == []


def test_subprocess_cancel_is_reaped():
    token = CancelToken()
    timer = threading.Timer(.15, token.cancel); timer.start()
    start = time.monotonic()
    with pytest.raises(Cancelled):
        run_command([sys.executable, '-c', 'import time; time.sleep(30)'], token)
    timer.join()
    assert time.monotonic()-start < 5


def test_subprocess_timeout_and_failure():
    with pytest.raises(TimeoutError):
        run_command([sys.executable,'-c','import time; time.sleep(10)'], CancelToken(), timeout=.1)
    with pytest.raises(RuntimeError):
        run_command([sys.executable,'-c','raise SystemExit(2)'], CancelToken())


def test_arguments_are_not_shell_commands(tmp_path):
    marker = tmp_path/'DO_NOT_CREATE'
    text = f'; touch {marker}; & echo injected'
    output = run_command([sys.executable, '-c', 'import sys; print(sys.argv[1])', text], CancelToken())
    assert output.decode().strip() == text and not marker.exists()


def test_instance_lock_prevents_parallel_instances(tmp_path):
    path = tmp_path/'lock'
    lock = InstanceLock(path)
    try:
        with pytest.raises(RuntimeError): InstanceLock(path)
    finally: lock.close()
    other = InstanceLock(path); other.close()


def test_csv_input_format_survives_save_and_reload(tmp_path):
    from audiocards.parser import parse_cards
    raw = 'Q without header,A without header'
    cards = parse_cards(raw, 'csv').cards
    store = ProjectStore(tmp_path/'db.sqlite')
    pid = store.save('CSV', raw, cards, Config(), input_format='csv')
    payload = store.load(pid)
    restored = parse_cards(payload['raw_text'], payload['input_format'])
    assert not restored.errors and restored.cards == cards
