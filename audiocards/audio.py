from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import uuid
import wave
from . import SAMPLE_RATE, NORMALIZATION_VERSION
from .models import Asset, Chunk
from .tts_provider import TTSProvider
from .utils import CancelToken, atomic_json, require_space, run_command, sha256_file

CANONICAL_VERSION = 'pcm24k16mono-loudnorm19-v1'


def wav_frames(path: Path, canonical: bool = True) -> int:
    try:
        with wave.open(str(path), 'rb') as f:
            if f.getsampwidth() != 2 or f.getnchannels() != 1 or f.getcomptype() != 'NONE':
                raise ValueError('Formato WAV non supportato.')
            if canonical and f.getframerate() != SAMPLE_RATE:
                raise ValueError('Frequenza WAV non canonica.')
            expected = f.getnframes()
            seen = 0; audible = False
            while data := f.readframes(16384):
                seen += len(data)//2
                audible = audible or any(data)
            if expected <= 0 or expected != seen or not audible:
                raise ValueError('Segmento WAV vuoto, silenzioso o troncato.')
            return expected
    except (wave.Error, EOFError) as e:
        raise ValueError('File WAV danneggiato.') from e


class AudioTools:
    def __init__(self, ffmpeg: Path, ffprobe: Path):
        self.ffmpeg = ffmpeg.resolve()
        self.ffprobe = ffprobe.resolve()
        for path in (self.ffmpeg, self.ffprobe):
            if not path.is_file():
                raise RuntimeError(f'Componente audio mancante: {path.name}. Usare il pacchetto completo.')
        self._identity = None

    @classmethod
    def from_root(cls, root: Path, developer_system_tools: bool = False):
        suffix = '.exe' if os.name == 'nt' else ''
        a = root/'tools'/('ffmpeg'+suffix); b = root/'tools'/('ffprobe'+suffix)
        if developer_system_tools and not getattr(sys, 'frozen', False):
            a = Path(shutil.which('ffmpeg') or str(a)); b = Path(shutil.which('ffprobe') or str(b))
        return cls(a, b)

    def identity(self, token: CancelToken) -> str:
        if self._identity is None:
            self._identity = sha256_file(self.ffmpeg, token)
        return self._identity

    def canonicalize(self, src: Path, dest: Path, token: CancelToken):
        run_command([str(self.ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                     '-i', str(src), '-vn', '-af', 'loudnorm=I=-19:TP=-1.5:LRA=11',
                     '-ar', str(SAMPLE_RATE), '-ac', '1', '-c:a', 'pcm_s16le', '-f', 'wav', str(dest)],
                    token, timeout=300)

    def encode(self, src: Path, dest: Path, title: str, index: int, token: CancelToken):
        run_command([str(self.ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                     '-i', str(src), '-map', '0:a:0', '-ar', str(SAMPLE_RATE), '-ac', '1',
                     '-c:a', 'libmp3lame', '-b:a', '128k', '-id3v2_version', '3',
                     '-metadata', 'title='+title, '-metadata', 'track='+str(index),
                     '-f', 'mp3', str(dest)], token, timeout=3600)

    def verify_mp3(self, path: Path, expected_frames: int, token: CancelToken) -> dict:
        if not path.is_file() or path.stat().st_size < 100:
            raise ValueError('MP3 vuoto o non creato.')
        data = json.loads(run_command([str(self.ffprobe), '-v', 'error',
                  '-show_entries', 'stream=codec_name,channels,sample_rate:format=duration,size',
                  '-of', 'json', str(path)], token))
        audio = data.get('streams', [])
        if len(audio) != 1 or audio[0].get('codec_name') != 'mp3' or audio[0].get('channels') != 1:
            raise ValueError('L\'output non e un MP3 mono valido.')
        actual = float(data['format']['duration'])
        if not math.isfinite(actual) or abs(actual - expected_frames/SAMPLE_RATE) > .25:
            raise ValueError('La durata MP3 non corrisponde agli eventi programmati.')
        run_command([str(self.ffmpeg), '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
                     '-f', 'null', '-'], token, timeout=3600)
        return {'duration_s': actual, 'size_bytes': path.stat().st_size,
                'sha256': sha256_file(path, token), 'codec': 'mp3', 'channels': 1,
                'sample_rate': int(audio[0]['sample_rate'])}

    def smoke_test(self, temporary_dir: Path, token: CancelToken):
        encoders = run_command([str(self.ffmpeg), '-hide_banner', '-encoders'], token).decode('utf-8', 'replace')
        if 'libmp3lame' not in encoders:
            raise RuntimeError('Il FFmpeg incluso non supporta l\'encoder MP3 richiesto.')
        with tempfile.TemporaryDirectory(dir=temporary_dir) as d:
            source = Path(d)/'probe.wav'; dest = Path(d)/'probe.mp3'
            count = SAMPLE_RATE//2
            with wave.open(str(source), 'wb') as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(SAMPLE_RATE)
                f.writeframes(b''.join(struct.pack('<h', int(2000*math.sin(i*2*math.pi*440/SAMPLE_RATE)))
                                       for i in range(count)))
            self.encode(source, dest, 'Test locale', 0, token)
            self.verify_mp3(dest, count, token)


class AudioCache:
    def __init__(self, directory: Path, provider: TTSProvider, tools: AudioTools):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.provider = provider; self.tools = tools
        self.hits = self.misses = 0

    def get(self, text: str, language: str, speed: float, token: CancelToken) -> Asset:
        token.check()
        identity = {'text': text, 'language': language, 'speed': speed,
                    'tts': self.provider.fingerprint(language),
                    'normalizer': NORMALIZATION_VERSION, 'canonical': CANONICAL_VERSION,
                    'ffmpeg_sha256': self.tools.identity(token)}
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        wav = self.directory/(key+'.wav'); meta = self.directory/(key+'.json')
        if wav.is_file() and meta.is_file():
            try:
                info = json.loads(meta.read_text(encoding='utf-8'))
                count = wav_frames(wav)
                digest = sha256_file(wav, token)
                if info['sha256'] == digest and info['frame_count'] == count:
                    self.hits += 1
                    return Asset(key, wav, count, digest)
            except (ValueError, KeyError, OSError):
                pass
        require_space(self.directory, max(10_000_000, len(text)*SAMPLE_RATE*2//4))
        self.misses += 1
        stem = self.directory/('.'+key+'.'+uuid.uuid4().hex)
        raw = Path(str(stem)+'.raw.part.wav'); normalized = Path(str(stem)+'.canonical.part.wav')
        try:
            self.provider.synthesize(text, language, speed, raw, token)
            wav_frames(raw, canonical=False)
            self.tools.canonicalize(raw, normalized, token)
            count = wav_frames(normalized); digest = sha256_file(normalized, token)
            token.check()
            os.replace(normalized, wav)
            # If a crash occurs between these writes, the next access regenerates safely.
            atomic_json(meta, {'asset_id': key, 'frame_count': count, 'sha256': digest})
            return Asset(key, wav, count, digest)
        finally:
            raw.unlink(missing_ok=True); normalized.unlink(missing_ok=True)


def _silence(out: wave.Wave_write, count: int, token: CancelToken):
    block = b'\0' * (16384*2)
    while count:
        token.check(); n = min(count, 16384)
        out.writeframesraw(block[:n*2]); count -= n


def _append(out: wave.Wave_write, asset: Asset, token: CancelToken):
    count = 0
    with wave.open(str(asset.path), 'rb') as src:
        if src.getframerate() != SAMPLE_RATE or src.getnchannels() != 1 or src.getsampwidth() != 2:
            raise ValueError('Asset non canonico durante il montaggio.')
        while data := src.readframes(16384):
            token.check(); out.writeframesraw(data); count += len(data)//2
    if count != asset.frame_count:
        raise ValueError('Asset modificato o troncato durante il montaggio.')


def render_chunk(chunk: Chunk, assets: dict[str, Asset], destination: Path,
                 tools: AudioTools, token: CancelToken) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    require_space(destination.parent, chunk.duration_frames*2 + round(chunk.duration_frames/SAMPLE_RATE*18000))
    if chunk.duration_frames*2 > 4_000_000_000:
        raise ValueError('Un evento supera il limite WAV: dividere la flashcard lunga.')
    unique = uuid.uuid4().hex
    wav = destination.with_name('.'+destination.stem+'.'+unique+'.part.wav')
    mp3 = destination.with_name('.'+destination.stem+'.'+unique+'.part.mp3')
    try:
        with wave.open(str(wav), 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(SAMPLE_RATE)
            for event in chunk.events:
                token.check()
                _silence(out, event.wait_frames, token)
                _append(out, assets[event.q_asset_id], token)
                _silence(out, event.pause_frames + event.bridge_frames, token)
                _append(out, assets[event.a_asset_id], token)
                _silence(out, event.gap_frames, token)
        if wav_frames(wav) != chunk.duration_frames:
            raise RuntimeError('La timeline PCM e il montaggio non corrispondono.')
        tools.encode(wav, mp3, f'{chunk.session_id} - Parte {chunk.index:03d}', chunk.index, token)
        info = tools.verify_mp3(mp3, chunk.duration_frames, token)
        token.check()
        os.replace(mp3, destination)
        return info
    finally:
        wav.unlink(missing_ok=True); mp3.unlink(missing_ok=True)
