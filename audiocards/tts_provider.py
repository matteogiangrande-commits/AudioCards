from __future__ import annotations
import atexit
import importlib.metadata
import json
import os
import shutil
import tempfile
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
        self._espeak_data_dir = None
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
        if self._espeak_data_dir is None:
            self._espeak_data_dir = _native_safe_espeak_dir(espeak_dir)
        if language not in self._voices:
            self._voices[language] = PiperVoice.load(
                self.models_dir / f'{language}_voice.onnx', use_cuda=False,
                espeak_data_dir=self._espeak_data_dir)
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


def _is_ascii_path(path: Path) -> bool:
    try:
        os.fspath(path).encode('ascii')
        return True
    except UnicodeEncodeError:
        return False


def _native_safe_espeak_dir(source: Path) -> Path:
    """Stage eSpeak data to an ASCII path when the native Windows library cannot
    open Unicode paths. No network, admin rights, or modification of the bundle.

    The location is a private per-process temporary directory. A normal ASCII
    installation loads data directly from the bundle without copying.
    """
    source = source.resolve()
    if not (source / 'phontab').is_file():
        raise RuntimeError('Tabelle fonetiche eSpeak assenti: ' + str(source))
    if os.name != 'nt' or _is_ascii_path(source):
        return source

    roots = [Path(tempfile.gettempdir())]
    system_root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    roots.append(system_root / 'Temp')
    for root in roots:
        if not _is_ascii_path(root):
            continue
        try:
            staging_parent = Path(tempfile.mkdtemp(prefix='AudioCards-espeak-', dir=root))
        except OSError:
            continue
        try:
            staged = staging_parent / 'espeak-ng-data'
            shutil.copytree(source, staged)
            if not (staged / 'phontab').is_file():
                raise RuntimeError('Copia temporanea eSpeak incompleta.')
            atexit.register(shutil.rmtree, staging_parent, ignore_errors=True)
            return staged
        except Exception:
            shutil.rmtree(staging_parent, ignore_errors=True)
            raise
    raise RuntimeError(
        'Il componente fonetico richiede una cartella temporanea scrivibile '
        'con percorso ASCII; nessuna delle directory di sistema e adatta.'
    )
