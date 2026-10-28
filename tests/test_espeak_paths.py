"""Regression tests for the native eSpeak Unicode-path workaround."""
from pathlib import Path

from audiocards.tts_provider import _is_ascii_path, _native_safe_espeak_dir


def test_ascii_path_detection():
    assert _is_ascii_path(Path("C:/AudioCards/models"))
    assert not _is_ascii_path(Path("C:/Utente/Cartella è/modelli"))


def test_ascii_source_used_without_staging(tmp_path):
    source = tmp_path / "espeak-ng-data"
    source.mkdir()
    (source / "phontab").write_bytes(b"test")
    # Works on the development host independently of the Windows-specific
    # staging branch. The real Windows relocated smoke test covers staging.
    assert _native_safe_espeak_dir(source) == source.resolve()
