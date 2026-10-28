from __future__ import annotations
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Protocol
import wave
from .utils import CancelToken, sha256_file


class TTSProvider(Protocol):
    provider_name: str
    def fingerprint(self, language: str) -> dict: ...
    def synthesize(self, text: str, language: str, speed: float,
                   destination: Path, token: CancelToken) -> None: ...


class PiperProvider:
    provider_name = 'piper'

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._voices = {}
        self._fingerprints = {}
        # No Piper imports or networking until the worker actually needs speech.

    def fingerprint(self, language: str) -> dict:
        if language not in ('it', 'en'):
            raise ValueError('Voce non supportata.')
        if language not in self._fingerprints:
            model = self.models_dir / f'{language}_voice.onnx'
            config = Path(str(model) + '.json')
            if not model.is_file() or not config.is_file():
                raise RuntimeError('Le voci Piper non sono presenti. Questo pacchetto sorgente '
                                   'non e la distribuzione Windows completa con le voci incluse.')
            try:
                version = importlib.metadata.version('piper-tts')
            except importlib.metadata.PackageNotFoundError:
                raise RuntimeError('Motore Piper assente: occorre il pacchetto Windows completo.') from None
            data = json.loads(config.read_text(encoding='utf-8'))
            if data.get('phoneme_type', 'espeak') != 'espeak':
                raise RuntimeError('Sono ammesse solo le voci espeak IT/EN approvate, senza download ausiliari.')
            if data.get('espeak', {}).get('voice', '').split('-')[0] not in (language,):
                raise RuntimeError('Il modello vocale non corrisponde alla lingua dichiarata.')
            self._fingerprints[language] = {
                'provider': self.provider_name, 'version': version, 'language': language,
                'model_sha256': sha256_file(model), 'config_sha256': sha256_file(config),
                'noise_scale': 0.0, 'noise_w_scale': 0.0,
            }
        return self._fingerprints[language]

    def synthesize(self, text: str, language: str, speed: float,
                   destination: Path, token: CancelToken):
        token.check()
        self.fingerprint(language)
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        from piper import PiperVoice, SynthesisConfig
        from piper import phonemize_espeak
        # The Windows Piper wheel can contain an eSpeak fallback path pointing
        # to the machine where its native library was compiled. Always select
        # the data included in the *current* frozen bundle (not the build path).
        espeak_dir = Path(phonemize_espeak.__file__).resolve().parent / 'espeak-ng-data'
        if not (espeak_dir / 'phontab').is_file():
            raise RuntimeError(
                'Dati fonetici eSpeak NG mancanti nel pacchetto: ' + str(espeak_dir)
            )
        os.environ['ESPEAK_DATA_PATH'] = str(espeak_dir)
        if language not in self._voices:
            self._voices[language] = PiperVoice.load(
                self.models_dir / f'{language}_voice.onnx', use_cuda=False,
                espeak_data_dir=espeak_dir)
        voice = self._voices[language]
        # Fixed zero noise avoids a fresh stochastic duration at every regeneration.
        settings = SynthesisConfig(length_scale=1.0/speed, noise_scale=0.0,
                                   noise_w_scale=0.0, normalize_audio=False, volume=1.0)
        with wave.open(str(destination), 'wb') as out:
            for index, part in enumerate(speech_chunks(text)):
                token.check()
                voice.synthesize_wav(part, out, syn_config=settings, set_wav_format=index == 0)
        token.check()


def speech_chunks(text: str, limit: int = 600) -> list[str]:
    """Bound native inference size and cancellation latency without reordering words."""
    remaining = text.strip(); parts = []
    while len(remaining) > limit:
        candidates = [i+1 for i in range(limit) if remaining[i] in '.!?;:'
                      and i+1 < len(remaining) and remaining[i+1].isspace()]
        split = candidates[-1] if candidates and candidates[-1] >= limit//2 else remaining.rfind(' ', 0, limit)
        if split <= 0:
            raise ValueError('Un token vocale e troppo lungo: inserire una lettura esplicita e piu breve.')
        parts.append(remaining[:split].strip()); remaining = remaining[split:].strip()
    if remaining: parts.append(remaining)
    return parts
