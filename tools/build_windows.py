"""Build and smoke-test an unsigned Windows CANDIDATE, never assert clean-VM approval.
Requires a developer Windows x64 environment, Python 3.12.10 and build dependencies.
The end user does not run this script and installs none of those dependencies.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audiocards import __version__
from audiocards.utils import atomic_json, atomic_text, sha256_file
from fetch_build_assets import prepare
from audit_pe import audit


def run(args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True, shell=False)


def copy_crt(destination: Path):
    # Only use the documented redistributable folder of a developer toolchain,
    # never copy arbitrary DLLs from System32 into a distributable application.
    roots = []
    if os.environ.get('VCToolsRedistDir'):
        roots.append(Path(os.environ['VCToolsRedistDir']))
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if base:
            vs = Path(base)/'Microsoft Visual Studio'
            if vs.exists(): roots.extend(vs.glob('*/*/VC/Redist/MSVC/*'))
    found = {}
    for base in sorted(set(roots), key=lambda p: str(p)):
        for part in ('Microsoft.VC*.CRT', 'Microsoft.VC*.OpenMP'):
            for folder in (base/'x64').glob(part):
                for file in folder.glob('*.dll'):
                    found[file.name.casefold()] = file
    for source in found.values():
        shutil.copy2(source, destination/source.name)
    return {p.name: {'sha256':sha256_file(p), 'source_kind':'Visual Studio Redistributable folder'}
            for p in [destination/x.name for x in found.values()]}


def collect_notices(destination: Path):
    dest = destination/'python-dependencies'; dest.mkdir(parents=True, exist_ok=True)
    records = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get('Name','unknown'); version = dist.version
        records.append({'name':name, 'version':version, 'license':dist.metadata.get('License-Expression') or dist.metadata.get('License','See included metadata')})
        for relative in dist.files or []:
            text = str(relative).lower()
            if any(t in Path(text).name for t in ('license','copying','notice')):
                source = Path(dist.locate_file(relative))
                if source.is_file() and source.stat().st_size < 2_000_000:
                    target = dest/name/str(relative).replace('..','_').replace(':','_')
                    target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source,target)
    atomic_json(destination/'dependency_inventory.json', records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reuse-assets', action='store_true', help='Use assets.resolved.json from a previous verified download')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().upper() not in ('AMD64','X86_64'):
        raise SystemExit('This build must run on Windows x64. No Linux-to-Windows cross-build.')
    if platform.python_version() != '3.12.10':
        raise SystemExit('Build requires pinned Python 3.12.10, not the end-user PC interpreter.')
    if not args.reuse_assets:
        prepare(ROOT)
    resolved_path = ROOT/'assets.resolved.json'
    if not resolved_path.is_file():
        raise SystemExit('Verified build assets missing.')
    resolved = json.loads(resolved_path.read_text(encoding='utf-8'))
    for relative, info in resolved['assets'].items():
        if sha256_file(ROOT/relative) != info['sha256']:
            raise SystemExit('Build assets changed: '+relative)
    # Audio tests explicitly discover these developer binaries; frozen runtime never uses PATH.
    os.environ['PATH'] = str(ROOT/'tools') + os.pathsep + os.environ.get('PATH','')
    run([sys.executable,'-m','pytest','-q','--junitxml=reports/windows-candidate-tests.xml'])
    run([sys.executable,'-m','PyInstaller','--clean','--noconfirm',str(ROOT/'AudioCards.spec')])
    bundle = ROOT/'dist'/'AudioCards'
    for directory in ('models','licenses'):
        shutil.copytree(ROOT/directory, bundle/directory, dirs_exist_ok=True)
    (bundle/'tools').mkdir(exist_ok=True)
    for name in ('ffmpeg.exe','ffprobe.exe'):
        shutil.copy2(ROOT/'tools'/name, bundle/'tools'/name)
    shutil.copy2(ROOT/'LICENSE', bundle/'LICENSE')
    shutil.copy2(ROOT/'docs'/'README_PRIMA_APERTURA.txt', bundle/'README_PRIMA_APERTURA.txt')
    shutil.copy2(resolved_path, bundle/'assets.resolved.json')
    shutil.copy2(ROOT/'requirements.lock', bundle/'requirements.lock')
    collect_notices(bundle/'licenses')
    crt = copy_crt(bundle/'_internal')
    native = audit(bundle)
    atomic_json(ROOT/'reports'/'windows-native-audit.json', native)
    if native['missing_imports']:
        raise SystemExit('Missing native DLLs. See reports/windows-native-audit.json; do not ship this build.')
    atomic_json(bundle/'VERSION.json', {
        'version':__version__, 'status':'CANDIDATE_NOT_CLEAN_VM_APPROVED',
        'python':platform.python_version(), 'build_os':platform.platform(),
        'built_at':datetime.now(timezone.utc).isoformat(), 'msvc_runtime':crt,
        'signature':'unsigned', 'clean_windows_11_test':False,
        'public_redistribution_license_audit':'pending',
    })
    # Source code accompanies the candidate; third-party corresponding source remains a release gate.
    source_zip = bundle/'AudioCards_source.zip'
    with zipfile.ZipFile(source_zip,'w',zipfile.ZIP_DEFLATED) as archive:
        for directory in ('audiocards','tools','tests','docs','.github'):
            for path in (ROOT/directory).rglob('*'):
                if path.is_file() and path.suffix not in ('.pyc','.exe','.dll','.pyd') and '__pycache__' not in path.parts:
                    archive.write(path, path.relative_to(ROOT))
        for name in ('AudioCards.py','AudioCards.spec','pyproject.toml','requirements.lock','requirements-build.lock','assets.lock.json','LICENSE','README.md','DECISIONS.md'):
            archive.write(ROOT/name,name)
    # Do not accidentally include font files or mutable application data.
    forbidden = [p for p in bundle.rglob('*') if p.suffix.lower() in ('.ttf','.otf','.woff','.woff2')]
    if forbidden:
        raise SystemExit('Unexpected font resources in bundle: inspect and remove before distribution.')
    digests = {p.relative_to(bundle).as_posix():sha256_file(p) for p in bundle.rglob('*') if p.is_file()}
    atomic_json(bundle/'bundle_checksums.json', digests)
    # Run ONLY the packaged EXE; no source interpreter arguments are used for synthesis.
    smoke = ROOT/'build'/'frozen-smoke'
    environment = dict(os.environ)
    environment['PATH'] = str(Path(environment.get('SystemRoot',r'C:\Windows'))/'System32')
    process = subprocess.run([str(bundle/'AudioCards.exe'),'--self-test-dir',str(smoke)],
                             env=environment, cwd=smoke.parent, timeout=600, shell=False)
    report_path = smoke/'self_test.json'
    if process.returncode or not report_path.is_file():
        raise SystemExit('The frozen executable did not pass its real speech/MP3 test.')
    result = json.loads(report_path.read_text(encoding='utf-8'))
    if result['status'] != 'passed':
        raise SystemExit('Frozen self-test failed: '+json.dumps(result))
    shutil.copy2(report_path,ROOT/'reports'/'windows-frozen-smoke.json')
    # Relocation smoke test (non-ASCII path, still not a clean VM).
    relocated = ROOT/'build'/'Spostata \u00e8 con spazi'/'AudioCards'
    shutil.copytree(bundle, relocated, dirs_exist_ok=True)
    relocated_report = ROOT/'build'/'relocated-smoke'
    check = subprocess.run([str(relocated/'AudioCards.exe'),'--self-test-dir',str(relocated_report)],
                           env=environment, cwd=relocated.parent, timeout=600, shell=False)
    if check.returncode:
        raise SystemExit('Relocated Windows smoke test failed.')
    archive_path = ROOT/'dist'/'AudioCards_Windows_x64_CANDIDATE_v2.0.zip'
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in bundle.rglob('*'):
            if path.is_file(): z.write(path, Path('AudioCards')/path.relative_to(bundle))
    atomic_text(archive_path.with_suffix('.zip.sha256'), sha256_file(archive_path)+'  '+archive_path.name+'\n')
    print('Candidate created:',archive_path)
    print('NOT a release approval: clean Windows 11, voice quality, offline native telemetry and license gates remain.')

if __name__ == '__main__':
    main()
