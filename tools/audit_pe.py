"""Inspect native imports. Does not substitute for a clean Windows VM execution test."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys


def audit(root: Path) -> dict:
    import pefile
    all_files = [p for p in root.rglob('*') if p.is_file()]
    included = {p.name.casefold() for p in all_files}
    native = [p for p in all_files if p.suffix.casefold() in ('.exe','.dll','.pyd')]
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'
    missing = []
    for path in native:
        pe = pefile.PE(str(path), fast_load=True)
        try:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                                                   pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
            imports = list(getattr(pe,'DIRECTORY_ENTRY_IMPORT',[])) + list(getattr(pe,'DIRECTORY_ENTRY_DELAY_IMPORT',[]))
            for item in imports:
                name = item.dll.decode('ascii').casefold()
                is_msvc = name.startswith(('msvcp','vcruntime','concrt','vcomp'))
                if name in included: continue
                if not is_msvc and (name.startswith(('api-ms-win-', 'ext-ms-win-')) or (system/name).is_file()): continue
                missing.append({'consumer':path.relative_to(root).as_posix(), 'missing_dll':name})
        finally:
            pe.close()
    return {'native_file_count':len(native), 'missing_imports':missing,
            'status':'passed_static_audit' if not missing else 'failed',
            'clean_windows_vm_test':False}

if __name__ == '__main__':
    result = audit(Path(sys.argv[1]).resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result['missing_imports']))
