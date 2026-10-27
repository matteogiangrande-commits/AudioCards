from __future__ import annotations
import json
import os
from pathlib import Path
import uuid
import zipfile
from .utils import CancelToken, require_space, sha256_file


def export_zip(folder: Path, destination: Path, token: CancelToken,
               progress=lambda *_: None) -> Path:
    folder = folder.resolve()
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'completed':
        raise ValueError('Il percorso non e completo. I file validi restano nella cartella di output.')
    files = [folder/'manifest.json', folder/'LEGGIMI.txt', folder/'progetto.audiocards.json']
    for record in manifest['audio_files']:
        path = (folder/record['path']).resolve()
        if not path.is_relative_to(folder) or record['status'] != 'generated_verified':
            raise ValueError('Manifest non valido.')
        if sha256_file(path, token) != record['sha256']:
            raise ValueError('Un MP3 e stato modificato dopo la generazione.')
        files.append(path)
    destination = destination.resolve()
    if destination.is_relative_to(folder):
        # Still allow a zip in the output folder, but it is never included recursively.
        if destination.name in {f.name for f in files}:
            raise ValueError('Non sovrascrivere un file del percorso.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    require_space(destination.parent, sum(f.stat().st_size for f in files))
    temp = destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.part')
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as out:
            for i, path in enumerate(files):
                token.check(); progress(f'Esportazione {i+1}/{len(files)}', i, len(files))
                with path.open('rb') as src, out.open(path.relative_to(folder).as_posix(), 'w', force_zip64=True) as dest:
                    while data := src.read(1024*1024):
                        token.check(); dest.write(data)
        token.check()
        with zipfile.ZipFile(temp) as check:
            if check.testzip() is not None:
                raise ValueError('Verifica archivio ZIP non riuscita.')
        os.replace(temp, destination)
        return destination
    finally:
        temp.unlink(missing_ok=True)
