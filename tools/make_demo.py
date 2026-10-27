"""Generate real spoken demonstrations, explicitly labelled as non-Piper."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev_espeak import DevelopmentESpeakProvider
from audiocards.audio import AudioTools
from audiocards.engine import Engine
from audiocards.models import Config
from audiocards.parser import parse_cards
from audiocards.exporter import export_zip
from audiocards.utils import CancelToken, atomic_json

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--count', type=int, default=8)
parser.add_argument('--minutes', type=int, default=20)
args = parser.parse_args()
raw = '''Che cosa contiene una flashcard? | Una domanda e una risposta.
Quando ascolti la prima risposta? | Subito dopo la prima domanda.
What comes after a review question? | A pause, followed by the answer.
A cosa serve la pausa? | A provare a formulare mentalmente la risposta.
How are long courses divided? | Into consecutive audio files.
Quale data compare in questo esempio? | 2026-10-27
What does the app measure? | Planned retrieval opportunities, not learning success.
Che cosa succede al termine della pausa? | Viene riprodotta la risposta di riferimento.'''
if args.count != 8:
    words = ['albero','ponte','fiume','montagna','libro','giardino','finestra','sentiero','nuvola','stella']
    raw = '\n'.join(f'Quale parola corrisponde alla scheda numero {i+1}? | La parola assegnata a questa scheda e {words[i%10]}.' for i in range(args.count))
result = parse_cards(raw)
assert not result.errors, result.errors
provider = DevelopmentESpeakProvider()
engine = Engine(provider, AudioTools.from_root(Path(__file__).resolve().parents[1], True),
                args.root/'data', args.root/'output')
last = ''
def progress(message, current, total):
    global last
    if message.startswith('Montaggio') or current % 20 == 0:
        print(message, flush=True)
config = Config(target_minutes=args.minutes)
folder = engine.generate(f'Demo {len(result.cards)} schede - voce tecnica eSpeak', result.cards,
                         config, CancelToken(), progress, raw_text=raw)
manifest = json.loads((folder/'manifest.json').read_text())
summary = {
    'status':manifest['status'], 'speech_provider':provider.provider_name,
    'piper_tested':False, 'windows_tested':False,
    'card_count':len(result.cards),
    'event_count':sum(len(s['events']) for s in manifest['sessions']),
    'mp3_count':len(manifest['audio_files']),
    'durations_s':[r['duration_s'] for r in manifest['audio_files']],
    'total_audio_s':sum(r['duration_s'] for r in manifest['audio_files']),
    'output_directory':str(folder), 'tts_calls':provider.calls,
    'warnings':manifest['warnings'],
}
atomic_json(args.root/'demo_report.json', summary)
print(json.dumps(summary, indent=2))
