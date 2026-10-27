"""DEVELOPMENT ONLY. eSpeak is not the promised Piper voice or a product fallback.
Used to exercise real spoken-audio assembly where neural model downloads are unavailable.
This module is excluded from the packaged application's entry point and PyInstaller graph.
"""
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audiocards.utils import run_command, sha256_file

class DevelopmentESpeakProvider:
    provider_name = 'ESPEAK_DEVELOPMENT_DEMO_NOT_PIPER'
    def __init__(self):
        binary = shutil.which('espeak')
        if not binary: raise RuntimeError('Development eSpeak not present.')
        self.binary = Path(binary).resolve(); self.digest = sha256_file(self.binary)
        self.calls = 0
    def fingerprint(self, language):
        return {'provider':self.provider_name, 'binary_sha256':self.digest, 'language':language}
    def synthesize(self, text, language, speed, destination, token):
        self.calls += 1
        run_command([str(self.binary), '-v', 'it' if language == 'it' else 'en-us',
                     '-s', str(round(155*speed)), '-b', '1', '-w', str(destination), '--stdin'],
                     token, timeout=120, input_bytes=text.encode('utf-8'))
