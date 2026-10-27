"""DEVELOPER/CI ONLY. Network downloads never occur inside the shipped application.
Download immutable model revisions and a hash-pinned FFmpeg archive. Retain provenance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audiocards.utils import atomic_json, sha256_file


def download(url: str, path: Path, expected: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and expected and sha256_file(path) == expected:
        return
    temp = path.with_name(path.name+'.download.part')
    request = urllib.request.Request(url, headers={'User-Agent':'AudioCards-Build/2.0'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temp.open('wb') as out:
            count = 0
            while data := response.read(1024*1024):
                count += len(data)
                if count > 500_000_000:
                    raise ValueError('Asset exceeds the allowed build-time size.')
                out.write(data)
        digest = sha256_file(temp)
        if expected and digest != expected:
            raise ValueError(f'Hash mismatch for {path.name}; download NOT accepted.')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def prepare(root: Path = ROOT):
    lock = json.loads((root/'assets.lock.json').read_text(encoding='utf-8'))
    resolved = {'schema_version':1, 'assets':{}}
    for lang, voice in lock['voices'].items():
        prefix = f"https://huggingface.co/rhasspy/piper-voices/resolve/{voice['revision']}/{voice['directory']}"
        for source_name, relative, expected in [
            (voice['voice_id']+'.onnx', f'models/{lang}_voice.onnx', voice['model_sha256']),
            (voice['voice_id']+'.onnx.json', f'models/{lang}_voice.onnx.json', None),
            ('MODEL_CARD', f'licenses/{lang}_voice_MODEL_CARD.txt', None),
        ]:
            url = prefix+'/'+source_name; destination = root/relative
            download(url, destination, expected)
            resolved['assets'][relative] = {'url':url, 'sha256':sha256_file(destination)}
        config = json.loads((root/f'models/{lang}_voice.onnx.json').read_text(encoding='utf-8'))
        if config.get('phoneme_type', 'espeak') != 'espeak':
            raise ValueError('The selected model requires an unsupported phonemizer.')
    binary = lock['ffmpeg']; archive = root/'build-cache'/'ffmpeg-windows.zip'
    download(binary['url'], archive, binary['sha256'])
    (root/'tools').mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in ('ffmpeg.exe', 'ffprobe.exe'):
            candidates = [info for info in z.infolist() if Path(info.filename).name.lower() == name]
            if len(candidates) != 1:
                raise ValueError(f'Expected exactly one {name} in the official archive.')
            # Do not extract arbitrary paths or symlinks supplied by a zip.
            destination = root/'tools'/name
            with z.open(candidates[0]) as src, destination.open('wb') as dest:
                shutil.copyfileobj(src, dest)
            resolved['assets'][f'tools/{name}'] = {
                'archive_url':binary['url'], 'archive_sha256':binary['sha256'],
                'sha256':sha256_file(destination)}
        for info in z.infolist():
            base = Path(info.filename).name
            if not info.is_dir() and any(s in base.upper() for s in ('LICENSE','COPYING','README')):
                if info.file_size > 2_000_000: continue
                destination = root/'licenses'/('ffmpeg_'+base)
                destination.write_bytes(z.read(info))
    atomic_json(root/'assets.resolved.json', resolved)
    return resolved

if __name__ == '__main__':
    prepare()
    print('Build-time assets downloaded and hashes verified. No runtime downloads are configured.')
