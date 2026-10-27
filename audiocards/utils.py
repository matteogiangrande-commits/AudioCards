from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

class Cancelled(Exception):
    """User cancellation, not a successful job and not a corrupted output."""

class CancelToken:
    def __init__(self):
        self.event = threading.Event()
    def cancel(self):
        self.event.set()
    def check(self):
        if self.event.is_set():
            raise Cancelled('Operazione annullata. I file gia verificati sono conservati.')


def sha256_file(path: Path, token: CancelToken | None = None) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while data := f.read(1024 * 1024):
            if token: token.check()
            h.update(data)
    return h.hexdigest()


def atomic_json(path: Path, value: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def safe_filename(value: str, fallback: str = 'Progetto') -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:70]
    if not value:
        return fallback
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I):
        value = '_' + value
    return value


def application_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def check_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as f:
            f.write(b'check'); f.flush()
        return True
    except OSError:
        return False


def require_space(path: Path, needed_bytes: int):
    free = shutil.disk_usage(path).free
    if free < needed_bytes + 50 * 1024 * 1024:
        raise OSError('Spazio su disco insufficiente. Liberare spazio e riprovare.')


def run_command(args: list[str], token: CancelToken, timeout: float = 120,
                input_bytes: bytes | None = None) -> bytes:
    """No shell; bounded logs; no pipe deadlocks; child reaped on cancellation."""
    token.check()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if input_bytes is not None:
            inp.write(input_bytes); inp.seek(0)
        proc = subprocess.Popen(
            [str(a) for a in args], stdin=inp if input_bytes is not None else subprocess.DEVNULL,
            stdout=out, stderr=err, shell=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0,
        )
        started = time.monotonic()
        try:
            while proc.poll() is None:
                token.check()
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Il componente audio ha superato il tempo massimo.')
                time.sleep(.04)
            token.check()
            if proc.returncode:
                # Do not forward tool diagnostics containing arbitrary user text.
                raise RuntimeError(f'Il componente {Path(args[0]).name} ha restituito errore {proc.returncode}.')
            out.seek(0)
            return out.read(8 * 1024 * 1024)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=3)


class InstanceLock:
    """Kernel-backed lock: automatically released even after process death."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            self.file.close()
            raise RuntimeError('AudioCards e gia aperta con questa cartella dati.') from None

    def close(self):
        if self.file.closed: return
        if os.name == 'nt':
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()
