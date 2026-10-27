# Windows x64 candidate build. This file has not been executed in the Linux session.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

if sys.platform != 'win32':
    raise SystemExit('Build AudioCards.spec on Windows x64; do not cross-compile this spec.')
ROOT = Path(SPECPATH)

datas = collect_data_files('piper', includes=['espeak-ng-data/**'])
datas += copy_metadata('piper-tts') + copy_metadata('onnxruntime')
binaries = collect_dynamic_libs('piper') + collect_dynamic_libs('onnxruntime')
a = Analysis(
    [str(ROOT/'AudioCards.py')], pathex=[str(ROOT)], binaries=binaries, datas=datas,
    hiddenimports=['piper', 'piper.config', 'piper.voice', 'piper.espeakbridge',
                   'piper.phonemize_espeak', 'onnxruntime',
                   'onnxruntime.capi.onnxruntime_pybind11_state', 'winsound'],
    hookspath=[], runtime_hooks=[],
    excludes=['pytest', 'IPython', 'matplotlib', 'pandas', 'torch', 'piper.train',
              'piper.http_server', 'tools', 'tests'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AudioCards',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False, target_arch=None,
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AudioCards')
