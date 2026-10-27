from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .utils import application_root, CancelToken, atomic_json


def main():
    parser = argparse.ArgumentParser(description='AudioCards desktop offline')
    parser.add_argument('--self-test-dir', type=Path, help='Developer: real IT/EN/MP3 smoke test and report')
    parser.add_argument('--dev-system-tools', action='store_true', help='Source development only: explicit system FFmpeg')
    args = parser.parse_args()
    if getattr(sys, 'frozen', False) and args.dev_system_tools:
        parser.error('Le build portatili non possono usare strumenti esterni al bundle.')
    if args.self_test_dir:
        from .audio import AudioTools
        from .tts_provider import PiperProvider
        from .engine import Engine
        from .parser import parse_cards
        from .models import Config
        report = args.self_test_dir.resolve(); report.mkdir(parents=True, exist_ok=True)
        root = application_root()
        try:
            engine = Engine(PiperProvider(root/'models'), AudioTools.from_root(root, args.dev_system_tools),
                report/'data', report/'output', root if getattr(sys, 'frozen', False) else None)
            cards = parse_cards('Che cosa ascolto? | Una domanda e una risposta.\nWhat comes next? | A retrieval pause.').cards
            output = engine.generate('Smoke test', cards, Config(), CancelToken())
            atomic_json(report/'self_test.json', {'status':'passed', 'output':str(output), 'platform':sys.platform})
            return 0
        except Exception as e:
            atomic_json(report/'self_test.json', {'status':'failed', 'error':str(e), 'platform':sys.platform})
            return 1
    from .gui import launch
    launch(developer_system_tools=args.dev_system_tools)
    return 0

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
