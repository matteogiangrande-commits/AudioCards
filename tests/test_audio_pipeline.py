from dataclasses import replace
import json
from pathlib import Path
import socket
import wave
import zipfile
import pytest
from audiocards.audio import AudioCache, wav_frames
from audiocards.engine import Engine, verify_bundle
from audiocards.exporter import export_zip
from audiocards.models import Config
from audiocards.parser import parse_cards
from audiocards.utils import CancelToken, Cancelled, atomic_json, sha256_file


def test_cache_hit_and_corruption_repair(tmp_path, tone, tools):
    cache = AudioCache(tmp_path/'cache', tone, tools)
    first = cache.get('test sentence', 'en', 1., CancelToken())
    second = cache.get('test sentence', 'en', 1., CancelToken())
    assert first == second and tone.calls == 1
    first.path.write_bytes(b'broken')
    third = cache.get('test sentence', 'en', 1., CancelToken())
    assert tone.calls == 2 and wav_frames(third.path) > 0
    cache.get('test sentence', 'en', 1.1, CancelToken())
    assert tone.calls == 3


def test_full_learning_pipeline_real_mp3_and_zip(tmp_path, tone, tools, monkeypatch):
    def forbidden(*a, **kw): raise AssertionError('Network access forbidden')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    engine = Engine(tone, tools, tmp_path/'data', tmp_path/'output')
    raw = 'Che cosa e un test? | Un controllo.\nWhat is a test? | A check.'
    cards = parse_cards(raw).cards
    out = engine.generate('Progetto \u00e8 & spazi', cards, Config(), CancelToken(), raw_text=raw)
    manifest = json.loads((out/'manifest.json').read_text())
    assert manifest['status'] == 'completed'
    assert len(manifest['sessions'][0]['events']) == 6
    assert manifest['listened'] is None and manifest['mastery'] is None
    assert len(manifest['audio_files']) == 1
    record = manifest['audio_files'][0]
    assert record['status'] == 'generated_verified'
    assert record['sha256'] == sha256_file(out/record['path'])
    archive = export_zip(out, tmp_path/'audio.zip', CancelToken())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert record['path'] in z.namelist()
        assert 'manifest.json' in z.namelist()
    calls = tone.calls
    engine.generate('repeat', cards, Config(), CancelToken())
    assert tone.calls == calls  # Preflight and speech cache both reused.


def test_review_sessions_remain_separate(tmp_path, tone, tools):
    engine = Engine(tone, tools, tmp_path/'data', tmp_path/'output')
    cards = parse_cards('Question? | Answer.').cards
    out = engine.generate('review', cards, Config(mode='review'), CancelToken())
    m = json.loads((out/'manifest.json').read_text())
    assert len(m['audio_files']) == 4
    assert len(set(r['session_id'] for r in m['audio_files'])) == 4
    assert all(s['events'][0]['kind'] == 'REVIEW' for s in m['sessions'])
    assert all(s['suggested_date'] is None for s in m['sessions'])


def test_cancellation_leaves_no_false_completed_file(tmp_path, tone, tools):
    engine = Engine(tone, tools, tmp_path/'data', tmp_path/'output')
    token = CancelToken()
    def progress(message, *_):
        if message.startswith('Montaggio'): token.cancel()
    with pytest.raises(Cancelled):
        engine.generate('cancel', parse_cards('Q | A').cards, Config(), token, progress)
    manifests = list((tmp_path/'output').rglob('manifest.json'))
    assert len(manifests) == 1
    m = json.loads(manifests[0].read_text())
    assert m['status'] == 'cancelled'
    assert not list((tmp_path/'output').rglob('*.mp3'))
    assert not list((tmp_path/'output').rglob('*.part*'))
    with pytest.raises(ValueError): export_zip(manifests[0].parent, tmp_path/'bad.zip', CancelToken())


def test_silent_or_truncated_wav_rejected(tmp_path):
    path = tmp_path/'silent.wav'
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b'\0'*500)
    with pytest.raises(ValueError): wav_frames(path)


def test_integrity_manifest_guards_traversal_and_modification(tmp_path):
    (tmp_path/'component.bin').write_bytes(b'component')
    atomic_json(tmp_path/'bundle_checksums.json', {'component.bin': sha256_file(tmp_path/'component.bin')})
    verify_bundle(tmp_path, CancelToken())
    (tmp_path/'component.bin').write_bytes(b'changed')
    with pytest.raises(RuntimeError): verify_bundle(tmp_path, CancelToken())
    atomic_json(tmp_path/'bundle_checksums.json', {'../outside':'123'})
    with pytest.raises(RuntimeError): verify_bundle(tmp_path, CancelToken())


def test_restart_recovers_interrupted_jobs_not_completed_files(tmp_path, tone, tools):
    output = tmp_path/'output'; old = output/'old'; old.mkdir(parents=True)
    atomic_json(old/'manifest.json', {'status':'generating', 'warnings':[]})
    (old/'.chunk.123.part.wav').write_bytes(b'incomplete')
    (old/'complete.mp3').write_bytes(b'previously verified placeholder')
    engine = Engine(tone, tools, tmp_path/'data', output)
    engine.recover_interrupted(CancelToken())
    assert json.loads((old/'manifest.json').read_text())['status'] == 'interrupted'
    assert not (old/'.chunk.123.part.wav').exists()
    assert (old/'complete.mp3').exists()
