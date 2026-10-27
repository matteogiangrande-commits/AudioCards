from __future__ import annotations
import hashlib
import math
from pathlib import Path
import random
import shutil
import struct
import wave
import pytest
from audiocards.models import Card, Asset, frames
from audiocards import SAMPLE_RATE
from audiocards.audio import AudioTools


def dataset(n: int, seed: int = 10):
    randomizer = random.Random(seed)
    cards = []; assets = {}
    for i in range(n):
        cid = f'card-{i:05d}'
        card = Card(cid, f'Domanda {i}?', f'Risposta {i}.', f'Domanda {i}?', f'Risposta {i}.', source_order=i)
        q = Asset(f'q{i}', Path(f'q{i}.wav'), frames(randomizer.uniform(.3, 15)), 'not-a-real-hash')
        a = Asset(f'a{i}', Path(f'a{i}.wav'), frames(randomizer.uniform(.4, 50)), 'not-a-real-hash')
        cards.append(card); assets[cid] = (q, a)
    return cards, assets


class ToneProvider:
    """A clearly synthetic test double, not a speech provider used in the product."""
    provider_name = 'TEST_TONE_NOT_SPEECH'
    def __init__(self): self.calls = 0
    def fingerprint(self, language): return {'provider': self.provider_name, 'lang': language, 'version': 1}
    def synthesize(self, text, language, speed, destination, token):
        token.check(); self.calls += 1
        count = round(SAMPLE_RATE * (.12 + len(text) / 500) / speed)
        frequency = 330 + int(hashlib.sha256(text.encode()).hexdigest()[:4], 16) % 500
        with wave.open(str(destination), 'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(SAMPLE_RATE)
            f.writeframes(b''.join(struct.pack('<h', int(3000*math.sin(2*math.pi*frequency*i/SAMPLE_RATE))) for i in range(count)))
        token.check()


@pytest.fixture
def tools():
    a = shutil.which('ffmpeg'); b = shutil.which('ffprobe')
    if not a or not b:
        pytest.skip('Real FFmpeg/ffprobe not available in this test environment.')
    return AudioTools(Path(a), Path(b))


@pytest.fixture
def tone(): return ToneProvider()
