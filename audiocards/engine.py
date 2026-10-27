from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile
from typing import Callable
import uuid
from . import __version__, SAMPLE_RATE, SCHEDULER_VERSION
from .audio import AudioCache, AudioTools, render_chunk
from .chunker import split_session
from .models import Card, Config
from .scheduler import plan_learning, plan_review
from .tts_provider import TTSProvider
from .utils import Cancelled, CancelToken, atomic_json, atomic_text, safe_filename, sha256_file

Progress = Callable[[str, int, int], None]


def verify_bundle(root: Path, token: CancelToken):
    manifest = root / 'bundle_checksums.json'
    if not manifest.is_file():
        raise RuntimeError('Manifest delle dipendenze mancante: distribuzione incompleta.')
    items = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(items, dict) or not items:
        raise RuntimeError('Manifest delle dipendenze non valido.')
    for relative, expected in items.items():
        token.check()
        path = (root/relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise RuntimeError('Un componente incluso e mancante o non valido. Estrarre di nuovo lo ZIP.')
        if sha256_file(path, token) != expected:
            raise RuntimeError(f'Il componente {Path(relative).name} e modificato. Ripristinare il pacchetto originale.')


class Engine:
    def __init__(self, provider: TTSProvider, tools: AudioTools, data_root: Path,
                 output_root: Path, bundle_root: Path | None = None):
        self.provider = provider; self.tools = tools
        self.data_root = data_root; self.output_root = output_root
        data_root.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)
        self.cache = AudioCache(data_root/'cache', provider, tools)
        self.bundle_root = bundle_root
        self._preflight_done = False

    def preflight(self, token: CancelToken, progress: Progress = lambda *_: None):
        if self._preflight_done: return
        progress('Controllo componenti locali', 0, 3)
        if self.bundle_root is not None:
            verify_bundle(self.bundle_root, token)
        self.recover_interrupted(token)
        self.provider.fingerprint('it'); self.provider.fingerprint('en')
        token.check()
        progress('Controllo del codificatore MP3', 1, 3)
        with tempfile.TemporaryDirectory(dir=self.data_root) as tmp:
            self.tools.smoke_test(Path(tmp), token)
        progress('Controllo voce italiana e inglese', 2, 3)
        for lang, text in [('it', 'Controllo della voce italiana.'),
                           ('en', 'English voice check.')]:
            self.cache.get(text, lang, 1.0, token)
        progress('Componenti verificati', 3, 3)
        self._preflight_done = True

    def recover_interrupted(self, token: CancelToken):
        # Called under the application's single-instance lock. Never remove completed MP3s.
        for directory in (self.data_root/'cache', self.output_root):
            if directory.exists():
                for path in directory.rglob('.*.part.*'):
                    token.check()
                    if path.is_file():
                        path.unlink(missing_ok=True)
        for path in self.output_root.rglob('manifest.json'):
            token.check()
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
                if payload.get('status') == 'generating':
                    payload['status'] = 'interrupted'
                    payload.setdefault('warnings', []).append('Generazione interrotta: file verificati conservati.')
                    atomic_json(path, payload)
            except (OSError, ValueError, AttributeError):
                logging.getLogger('audiocards').warning('Manifest non recuperabile: directory %s', path.parent.name)

    def generate(self, name: str, cards: list[Card], config: Config, token: CancelToken,
                 progress: Progress = lambda *_: None, raw_text: str = '',
                 project_id: str = '', input_format: str = 'auto') -> Path:
        if not cards or len(cards) > 10000:
            raise ValueError('Inserire da 1 a 10.000 flashcard.')
        if len({c.card_id for c in cards}) != len(cards):
            raise ValueError('Identificatori scheda duplicati.')
        self.preflight(token, progress)
        token.check()
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        folder = self.output_root/safe_filename(name)/run_id
        folder.mkdir(parents=True, exist_ok=False)
        manifest_path = folder/'manifest.json'
        manifest = {
            'schema_version': 1, 'app_version': __version__, 'scheduler_version': SCHEDULER_VERSION,
            'sample_rate': SAMPLE_RATE, 'name': name, 'run_id': run_id,
            'status': 'generating', 'listened': None, 'mastery': None,
            'config': asdict(config), 'cards': [asdict(c) for c in cards],
            'provider': self.provider.provider_name, 'sessions': [], 'audio_files': [],
            'warnings': [], 'created_at': datetime.now(timezone.utc).isoformat(),
        }
        atomic_json(manifest_path, manifest)
        atomic_json(folder/'progetto.audiocards.json', {
            'schema_version': 1, 'project_id': project_id or uuid.uuid4().hex,
            'name': name, 'raw_text': raw_text, 'cards': [asdict(c) for c in cards],
            'config': asdict(config), 'last_output': None, 'input_format': input_format,
        })
        try:
            pairs = {}; by_asset = {}
            for i, card in enumerate(cards):
                for label, text, language, part in (
                    ('domanda', card.question_spoken, card.question_lang, 0),
                    ('risposta', card.answer_spoken, card.answer_lang, 1)):
                    token.check()
                    progress(f'Voce: scheda {i+1}/{len(cards)}, {label}', 2*i+part, 2*len(cards))
                    asset = self.cache.get(text, language, config.speed, token)
                    by_asset[asset.asset_id] = asset
                    if part == 0: q = asset
                    else: pairs[card.card_id] = (q, asset)
            progress('Programmazione dei richiami', 0, 1)
            sessions = ([plan_learning(cards, pairs, config)] if config.mode == 'learn'
                        else plan_review(cards, pairs, config))
            chunks = [c for s in sessions for c in split_session(s, config.target_minutes*60)]
            all_events = [e for s in sessions for e in s.events]
            early = [e for e in all_events if e.due_frame is not None and e.question_start_frame < e.due_frame]
            if early:
                manifest['warnings'].append(
                    f'{len(early)} richiami anticipati per non inserire lunghi silenzi; '
                    'gli scostamenti sono registrati negli eventi.')
            if config.mode == 'learn' and len(cards) < 3:
                manifest['warnings'].append('Poche schede: distribuzione compressa, non equivalente a intervalli pieni.')
            if any(config.pause_frames(a.frame_count) < a.frame_count for q, a in pairs.values()):
                manifest['warnings'].append('Alcune risposte superano la pausa disponibile: aumentare la pausa massima o dividere le schede.')
            manifest['assets'] = {
                aid: {'frame_count': a.frame_count, 'sha256': a.sha256} for aid, a in by_asset.items()}
            manifest['voices'] = {lang: self.provider.fingerprint(lang) for lang in ('it', 'en')}
            manifest['sessions'] = [
                {'session_id': s.session_id, 'relative_day': s.relative_day,
                 'suggested_date': s.suggested_date, 'seed': s.seed,
                 'listened': None, 'events': [e.to_dict() for e in s.events]} for s in sessions]
            for c in chunks:
                relative = f'{c.session_id}/{c.session_id}_{c.index:03d}.mp3'
                manifest['audio_files'].append({
                    'path': relative, 'status': 'planned', 'session_id': c.session_id,
                    'index': c.index, 'event_ids': [e.event_id for e in c.events],
                    'expected_duration_s': c.duration_frames/SAMPLE_RATE,
                    'duration_exception': abs(c.duration_frames/SAMPLE_RATE-config.target_minutes*60) > config.target_minutes*6,
                })
            atomic_json(manifest_path, manifest)
            for i, (chunk, record) in enumerate(zip(chunks, manifest['audio_files'])):
                token.check()
                progress(f'Montaggio MP3 {i+1}/{len(chunks)}', i, len(chunks))
                info = render_chunk(chunk, by_asset, folder/record['path'], self.tools, token)
                record.update(info); record['status'] = 'generated_verified'
                atomic_json(manifest_path, manifest)
            manifest['status'] = 'completed'
            manifest['completed_at'] = datetime.now(timezone.utc).isoformat()
            manifest['cache'] = {'hits': self.cache.hits, 'misses': self.cache.misses}
            atomic_json(manifest_path, manifest)
            atomic_text(folder/'LEGGIMI.txt', self._instructions(manifest))
            progress('Generazione completata', len(chunks), len(chunks))
            return folder
        except Exception as error:
            manifest['status'] = 'cancelled' if isinstance(error, Cancelled) else 'failed'
            manifest['error_type'] = type(error).__name__
            try:
                atomic_json(manifest_path, manifest)
            except OSError:
                pass
            # Do not log text or exception details from TTS libraries.
            logging.getLogger('audiocards').warning('Job %s: %s', run_id, type(error).__name__)
            raise

    @staticmethod
    def _instructions(manifest: dict) -> str:
        introduction = (
            'Ascoltare le parti in ordine. Una nuova scheda contiene domanda e risposta; '
            'i richiami successivi contengono una pausa per rispondere mentalmente. '
            'Le distanze sono espresse in tempo di audio, non in giorni realmente trascorsi.'
            if manifest['config']['mode'] == 'learn' else
            'Ogni cartella e una sessione di ripasso. Completare le parti della stessa sessione in ordine. '
            'G+01, G+03, G+07, G+14 sono giorni indicativi dopo il completamento dichiarato dello studio; '
            'non indicano ascolti verificati.')
        return ('AUDIOCARDS - '+manifest['name']+'\n\n'+introduction+
                '\n\nIl software programma occasioni di recupero: non verifica risposte o apprendimento.\n'
                'Non usare questi esercizi durante attivita che richiedono attenzione continua.\n\n'
                'Progetto modificabile: progetto.audiocards.json.\n'
                'manifest.json contiene testi, sequenze e metadati: condividerlo solo consapevolmente.\n\n'
                +'\n'.join(manifest['warnings'])+'\n')
