from __future__ import annotations
from dataclasses import asdict, replace
import json
import logging
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import uuid
from . import __version__
from .audio import AudioTools
from .engine import Engine
from .exporter import export_zip
from .models import Card, Config
from .parser import parse_cards
from .project_store import ProjectStore, import_project, export_project
from .tts_provider import PiperProvider
from .utils import CancelToken, Cancelled, InstanceLock, application_root, check_writable


class AudioCardsApp:
    def __init__(self, root: tk.Tk, data_root: Path, output_root: Path,
                 app_root: Path | None = None, developer_system_tools: bool = False):
        self.root = root; self.app_root = app_root or application_root()
        self.data_root = data_root; self.output_root = output_root
        self.developer_system_tools = developer_system_tools
        self.store = ProjectStore(data_root/'projects.sqlite')
        self.engine: Engine | None = None
        self.project_id: str | None = None
        self.overrides: dict[str, Card] = {}
        self.last_output: Path | None = None
        self.worker: threading.Thread | None = None
        self.token: CancelToken | None = None
        self.messages: queue.Queue = queue.Queue()
        self._on_done = None; self._closing = False; self._parse_after = None
        self._parser_format = 'auto'; self._dirty = False
        root.title('AudioCards - Flashcard audio offline')
        root.geometry('1040x760'); root.minsize(820, 620)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.name = tk.StringVar(value='Le mie flashcard')
        self.mode = tk.StringVar(value='learn')
        self.minutes = tk.StringVar(value='20')
        self.language = tk.StringVar(value='auto')
        self.speed = tk.DoubleVar(value=1.0)
        self.factor = tk.DoubleVar(value=1.3)
        self.pmin = tk.DoubleVar(value=4.0)
        self.pmax = tk.DoubleVar(value=35.0)
        self.completion = tk.StringVar()
        self.status = tk.StringVar(value='Incolla le flashcard per iniziare.')
        self.count_text = tk.StringVar(value='Nessuna scheda')
        self._build_ui()
        root.after(80, self._poll)
        if getattr(sys, 'frozen', False):
            root.after(250, self.check_components)

    @property
    def busy(self):
        return self.worker is not None

    def _build_ui(self):
        style = ttk.Style(self.root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
        style.configure('Sub.TLabel', font=('Segoe UI', 10))
        style.configure('Go.TButton', padding=(18, 10))
        style.configure('TButton', padding=(9, 5))
        menu = tk.Menu(self.root)
        project = tk.Menu(menu, tearoff=False)
        for label, command in [('Nuovo', self.new_project), ('Apri progetto salvato', self.open_project),
                               ('Salva progetto', self.save_project), ('Importa progetto JSON', self.import_json),
                               ('Esporta progetto JSON', self.export_json), ('Importa testo o CSV', self.import_text)]:
            project.add_command(label=label, command=command)
        menu.add_cascade(label='Progetto', menu=project)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label='Controlla componenti', command=self.check_components)
        help_menu.add_command(label='Apri cartella dati', command=lambda: self._open_folder(self.data_root))
        help_menu.add_command(label='Informazioni', command=self.about)
        menu.add_cascade(label='Aiuto', menu=help_menu)
        self.root.configure(menu=menu)
        outer = ttk.Frame(self.root, padding=22); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='AudioCards', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Da domande e risposte a un percorso MP3. Tutto sul tuo computer.',
                  style='Sub.TLabel').pack(anchor='w', pady=(2, 16))
        project_row = ttk.Frame(outer); project_row.pack(fill='x', pady=(0, 12))
        ttk.Label(project_row, text='Progetto').pack(side='left')
        self.name_entry = ttk.Entry(project_row, textvariable=self.name, width=36)
        self.name_entry.pack(side='left', padx=(10, 0))
        ttk.Button(project_row, text='Salva', command=self.save_project).pack(side='right')
        ttk.Button(project_row, text='Apri', command=self.open_project).pack(side='right', padx=6)
        ttk.Label(outer, text='Incolla le flashcard', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Una coppia per riga: Domanda | Risposta. Anche TSV e coppie Q: / A:.').pack(anchor='w', pady=(3, 7))
        editor = ttk.Frame(outer); editor.pack(fill='both', expand=True)
        self.text = tk.Text(editor, height=12, wrap='word', undo=True, font=('Segoe UI', 11),
                            relief='solid', bd=1, padx=12, pady=12)
        scroll = ttk.Scrollbar(editor, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
        self.text.bind('<<Modified>>', self._changed)
        counts = ttk.Frame(outer); counts.pack(fill='x', pady=(6, 12))
        ttk.Label(counts, textvariable=self.count_text).pack(side='left')
        self.preview_btn = ttk.Button(counts, text='Controlla schede e pronuncia', command=self.preview)
        self.preview_btn.pack(side='right')
        controls = ttk.Frame(outer); controls.pack(fill='x', pady=(0, 10))
        ttk.Label(controls, text='Modalita').grid(row=0, column=0, sticky='w', padx=(0, 12))
        self.learn_radio = ttk.Radiobutton(controls, text='Apprendimento', variable=self.mode, value='learn')
        self.review_radio = ttk.Radiobutton(controls, text='Ripasso', variable=self.mode, value='review')
        self.learn_radio.grid(row=0, column=1); self.review_radio.grid(row=0, column=2, padx=(12, 28))
        ttk.Label(controls, text='Durata di ogni MP3').grid(row=0, column=3, padx=(0, 10))
        self.duration_combo = ttk.Combobox(controls, textvariable=self.minutes, values=['10', '20', '40', '60'],
                                           width=5, state='readonly')
        self.duration_combo.grid(row=0, column=4)
        ttk.Label(controls, text='minuti circa').grid(row=0, column=5, padx=7)
        ttk.Button(outer, text='Impostazioni avanzate', command=self._toggle_advanced).pack(anchor='w', pady=(0, 7))
        self.advanced = ttk.LabelFrame(outer, text='Opzioni facoltative', padding=10)
        settings = [('Lingua', self.language, ('auto', 'it', 'en')),
                    ('Velocita', self.speed, None), ('Pausa x', self.factor, None),
                    ('Pausa min. (s)', self.pmin, None), ('Pausa max. (s)', self.pmax, None)]
        for i, (label, variable, values) in enumerate(settings):
            ttk.Label(self.advanced, text=label).grid(row=0, column=i, sticky='w', padx=5)
            if values:
                widget = ttk.Combobox(self.advanced, textvariable=variable, values=values, width=8, state='readonly')
                widget.bind('<<ComboboxSelected>>', lambda e: self._update_count())
            else:
                widget = ttk.Entry(self.advanced, textvariable=variable, width=9)
            widget.grid(row=1, column=i, sticky='w', padx=5, pady=5)
        ttk.Label(self.advanced, text='Fine studio (ripasso): AAAA-MM-GG, oppure lascia vuoto').grid(row=2, column=0, columnspan=4, sticky='w', padx=5)
        ttk.Entry(self.advanced, textvariable=self.completion, width=15).grid(row=2, column=4, padx=5)
        ttk.Label(self.advanced, text='Voci: una italiana e una inglese incluse. Nessun servizio cloud.').grid(row=3, column=0, columnspan=5, sticky='w', padx=5, pady=(8, 0))
        self.bottom = ttk.Frame(outer); self.bottom.pack(fill='x', pady=(8, 0))
        self.generate_btn = ttk.Button(self.bottom, text='Genera audio', style='Go.TButton', command=self.generate)
        self.generate_btn.pack(side='left')
        self.cancel_btn = ttk.Button(self.bottom, text='Annulla', command=self.cancel, state='disabled')
        self.cancel_btn.pack(side='left', padx=9)
        self.zip_btn = ttk.Button(self.bottom, text='Esporta ZIP', command=self.export_audio, state='disabled')
        self.zip_btn.pack(side='right')
        self.folder_btn = ttk.Button(self.bottom, text='Apri cartella', command=self.open_output, state='disabled')
        self.folder_btn.pack(side='right', padx=7)
        self.bar = ttk.Progressbar(outer, mode='determinate'); self.bar.pack(fill='x', pady=(14, 6))
        ttk.Label(outer, textvariable=self.status, wraplength=940).pack(anchor='w')
        self.root.bind('<Control-s>', lambda e: self.save_project())

    def _toggle_advanced(self):
        if self.advanced.winfo_manager():
            self.advanced.pack_forget()
        else:
            self.advanced.pack(fill='x', pady=(0, 6), before=self.bottom)

    def _changed(self, event=None):
        if not self.text.edit_modified(): return
        self.text.edit_modified(False); self._dirty = True
        if self._parse_after:
            self.root.after_cancel(self._parse_after)
        self._parse_after = self.root.after(350, self._update_count)

    def _parse(self):
        result = parse_cards(self.text.get('1.0', 'end-1c'), self._parser_format, self.language.get())
        result.cards = [replace(self.overrides[c.card_id], source_order=c.source_order)
                        if c.card_id in self.overrides else c for c in result.cards]
        return result

    def _update_count(self):
        self._parse_after = None
        result = self._parse()
        count = len(result.cards)
        label = f'{count} schede riconosciute'
        if result.errors: label += f' | {len(result.errors)} errori da correggere'
        if result.warnings: label += f' | {len(result.card_warnings)} schede da verificare'
        self.count_text.set(label)

    def _config(self):
        return Config(mode=self.mode.get(), target_minutes=int(self.minutes.get()), speed=float(self.speed.get()),
                      pause_factor=float(self.factor.get()), pause_min=float(self.pmin.get()),
                      pause_max=float(self.pmax.get()), completion_date=self.completion.get().strip())

    def _valid_cards(self):
        result = self._parse()
        if result.errors:
            raise ValueError('\n'.join(result.errors[:8]))
        return result.cards

    def _engine(self):
        if self.engine is None:
            tools = AudioTools.from_root(self.app_root, self.developer_system_tools)
            self.engine = Engine(PiperProvider(self.app_root/'models'), tools,
                                 self.data_root, self.output_root,
                                 self.app_root if getattr(sys, 'frozen', False) else None)
        return self.engine

    def _start(self, operation, done=None):
        if self.busy: return
        self.token = CancelToken(); self._on_done = done
        self.generate_btn.configure(state='disabled'); self.preview_btn.configure(state='disabled')
        self.cancel_btn.configure(state='normal'); self.zip_btn.configure(state='disabled')
        self.text.configure(state='disabled')
        self.bar['value'] = 0
        def progress(message, current, total):
            self.messages.put(('progress', (message, current, total)))
        def run():
            try:
                value = operation(self.token, progress)
                self.messages.put(('done', value))
            except Cancelled as e:
                self.messages.put(('cancelled', str(e)))
            except Exception as e:
                logging.getLogger('audiocards').error('Worker failed: %s', type(e).__name__)
                self.messages.put(('error', str(e)))
        self.worker = threading.Thread(target=run, name='AudioCardsWorker', daemon=False)
        self.worker.start()

    def _poll(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'progress':
                    message, current, total = value
                    self.status.set(message); self.bar['value'] = 100*current/max(1, total)
                else:
                    if self.worker: self.worker.join(timeout=.2)
                    self.worker = None
                    self.generate_btn.configure(state='normal'); self.preview_btn.configure(state='normal')
                    self.cancel_btn.configure(state='disabled'); self.text.configure(state='normal')
                    if self.last_output: self.zip_btn.configure(state='normal')
                    if self._closing:
                        self.root.destroy(); return
                    if kind == 'done':
                        self.bar['value'] = 100
                        callback = self._on_done; self._on_done = None
                        if callback:
                            try:
                                callback(value)
                            except Exception as error:
                                self.status.set('Lavoro terminato, ma il salvataggio o la visualizzazione richiedono attenzione.')
                                messagebox.showerror('AudioCards', str(error), parent=self.root)
                    elif kind == 'cancelled':
                        self.status.set(value)
                    else:
                        self.status.set('Operazione non completata. Nessun file incompleto e stato pubblicato.')
                        messagebox.showerror('AudioCards', value, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def generate(self):
        if self.busy: return
        try:
            cards = self._valid_cards(); config = self._config()
            raw = self.text.get('1.0', 'end-1c'); name = self.name.get().strip() or 'Progetto'
            self.project_id = self.store.save(name, raw, cards, config, self.project_id, input_format=self._parser_format)
            self._dirty = False
        except (ValueError, tk.TclError, OSError) as e:
            messagebox.showerror('Controllare i dati', str(e), parent=self.root); return
        pid = self.project_id
        input_format = self._parser_format
        def run(token, progress):
            return self._engine().generate(name, cards, config, token, progress, raw, pid, input_format)
        def done(folder):
            self.last_output = folder
            relative = folder.relative_to(self.output_root).as_posix()
            self.store.save(name, raw, cards, config, pid, relative, input_format)
            self.folder_btn.configure(state='normal'); self.zip_btn.configure(state='normal')
            manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            self.status.set(f"Creati {len(manifest['audio_files'])} MP3. Tutte le {len(cards)} schede incluse."
                            + (' Sono presenti note nel LEGGIMI.' if manifest['warnings'] else ''))
        self._start(run, done)

    def cancel(self):
        if self.token and self.busy:
            self.token.cancel(); self.status.set('Annullamento in corso: attendo la fine dell\'unita vocale attiva.')

    def check_components(self):
        if self.busy: return
        self._start(lambda token, progress: self._engine().preflight(token, progress),
                    lambda _: self.status.set('Voci e codificatore MP3 verificati. Pronto per generare.'))

    def save_project(self):
        if self.busy: return
        try:
            self.project_id = self.store.save(self.name.get(), self.text.get('1.0', 'end-1c'),
                                              self._parse().cards, self._config(), self.project_id,
                                              self.last_output.relative_to(self.output_root).as_posix() if self.last_output else None,
                                              self._parser_format)
            self.status.set('Progetto salvato sul computer.'); self._dirty = False
        except Exception as e:
            messagebox.showerror('Salvataggio', str(e), parent=self.root)

    def _replace_allowed(self):
        if self.busy: return False
        return not self._dirty or messagebox.askyesno('Sostituire il testo?',
                   'Le modifiche non salvate verranno sostituite. Continuare?', parent=self.root)

    def new_project(self):
        if not self._replace_allowed(): return
        self.project_id = None; self.overrides = {}; self.last_output = None
        self.name.set('Le mie flashcard'); self.text.delete('1.0', 'end')
        self._parser_format = 'auto'; self._dirty = False
        self.folder_btn.configure(state='disabled'); self.zip_btn.configure(state='disabled')
        self._update_count()

    def open_project(self):
        if not self._replace_allowed(): return
        projects = self.store.list_projects()
        if not projects:
            messagebox.showinfo('Progetti', 'Nessun progetto salvato.', parent=self.root); return
        win = tk.Toplevel(self.root); win.title('Apri progetto'); win.geometry('620x330')
        tree = ttk.Treeview(win, columns=('name', 'date'), show='headings', selectmode='browse')
        tree.heading('name', text='Nome'); tree.heading('date', text='Ultimo salvataggio')
        tree.pack(fill='both', expand=True, padx=12, pady=12)
        for pid, name, timestamp in projects:
            tree.insert('', 'end', iid=pid, values=(name, timestamp[:19].replace('T', ' ')))
        def selected():
            if tree.selection():
                self._load_payload(self.store.load(tree.selection()[0])); win.destroy()
        ttk.Button(win, text='Apri', command=selected).pack(pady=(0, 12))
        tree.bind('<Double-1>', lambda e: selected())

    def _load_payload(self, p):
        self.project_id = p['project_id']; self.name.set(p['name'])
        self.overrides = {c['card_id']: Card(**c) for c in p['cards']}
        self._parser_format = p.get('input_format', 'auto')
        self.text.delete('1.0', 'end'); self.text.insert('1.0', p['raw_text'])
        cfg = Config(**p['config'])
        self.mode.set(cfg.mode); self.minutes.set(str(cfg.target_minutes)); self.speed.set(cfg.speed)
        self.factor.set(cfg.pause_factor); self.pmin.set(cfg.pause_min); self.pmax.set(cfg.pause_max)
        self.completion.set(cfg.completion_date)
        relative = p.get('last_output'); self.last_output = None
        if relative:
            path = (self.output_root/relative).resolve()
            if path.is_relative_to(self.output_root.resolve()) and path.is_dir(): self.last_output = path
        self.folder_btn.configure(state='normal' if self.last_output else 'disabled')
        self.zip_btn.configure(state='normal' if self.last_output else 'disabled')
        self._dirty = False; self._update_count(); self.status.set('Progetto aperto.')

    def import_json(self):
        if not self._replace_allowed(): return
        path = filedialog.askopenfilename(filetypes=[('Progetto AudioCards', '*.json')])
        if not path: return
        try:
            payload = import_project(Path(path)); payload['project_id'] = uuid.uuid4().hex
            payload['last_output'] = None
            self.store.save_payload(payload); self._load_payload(payload)
        except Exception as e:
            messagebox.showerror('Importazione', str(e), parent=self.root)

    def export_json(self):
        if self.busy: return
        self.save_project()
        if not self.project_id: return
        path = filedialog.asksaveasfilename(defaultextension='.audiocards.json',
                  initialfile='progetto.audiocards.json', filetypes=[('Progetto JSON', '*.json')])
        if path:
            try: export_project(Path(path), self.store.load(self.project_id))
            except Exception as e: messagebox.showerror('Esportazione', str(e), parent=self.root)

    def import_text(self):
        if not self._replace_allowed(): return
        path = filedialog.askopenfilename(filetypes=[('Testo o CSV', '*.txt *.csv *.tsv'), ('Tutti i file', '*.*')])
        if not path: return
        try:
            p = Path(path)
            if p.stat().st_size > 8_000_000: raise ValueError('File troppo grande.')
            raw = p.read_text(encoding='utf-8-sig')
            self._parser_format = 'csv' if p.suffix.lower() == '.csv' else 'auto'
            self.overrides = {}; self.text.delete('1.0', 'end'); self.text.insert('1.0', raw)
            self._update_count()
        except Exception as e:
            messagebox.showerror('Importazione UTF-8', str(e), parent=self.root)

    def preview(self):
        if self.busy: return
        result = self._parse()
        win = tk.Toplevel(self.root); win.title('Controlla le schede e la pronuncia'); win.geometry('980x560')
        ttk.Label(win, text='Doppio clic su una riga per correggere lingua e testo pronunciato.').pack(anchor='w', padx=12, pady=10)
        tree = ttk.Treeview(win, columns=('n','q','a','lang','note'), show='headings', selectmode='browse')
        for key, title, width in [('n','#',35),('q','Domanda',270),('a','Risposta',300),('lang','Lingue',65),('note','Controllo',200)]:
            tree.heading(key, text=title); tree.column(key, width=width, stretch=key in ('q','a','note'))
        tree.pack(fill='both', expand=True, padx=12)
        cards = {c.card_id: c for c in result.cards}
        def refresh(card):
            values = (card.source_order+1, card.question_spoken, card.answer_spoken,
                      card.question_lang+'/'+card.answer_lang,
                      ' | '.join(result.card_warnings.get(card.card_id, [])))
            if tree.exists(card.card_id): tree.item(card.card_id, values=values)
            else: tree.insert('', 'end', iid=card.card_id, values=values)
        for c in result.cards: refresh(c)
        if result.errors:
            ttk.Label(win, text='\n'.join(result.errors[:5]), wraplength=930).pack(fill='x', padx=12, pady=7)
        def edit():
            if not tree.selection(): return
            key = tree.selection()[0]; card = cards[key]
            dialog = tk.Toplevel(win); dialog.title(f'Scheda {card.source_order+1} - testo vocale'); dialog.geometry('700x480')
            qlang = tk.StringVar(value=card.question_lang); alang = tk.StringVar(value=card.answer_lang)
            ttk.Label(dialog, text='Domanda da pronunciare').pack(anchor='w', padx=12, pady=(12, 4))
            qtext = tk.Text(dialog, height=5, wrap='word'); qtext.pack(fill='both', expand=True, padx=12)
            qtext.insert('1.0', card.question_spoken)
            ttk.Combobox(dialog, textvariable=qlang, values=('it','en'), state='readonly', width=8).pack(anchor='w', padx=12, pady=4)
            ttk.Label(dialog, text='Risposta da pronunciare').pack(anchor='w', padx=12, pady=4)
            atext = tk.Text(dialog, height=5, wrap='word'); atext.pack(fill='both', expand=True, padx=12)
            atext.insert('1.0', card.answer_spoken)
            ttk.Combobox(dialog, textvariable=alang, values=('it','en'), state='readonly', width=8).pack(anchor='w', padx=12, pady=4)
            def save():
                try:
                    updated = replace(card, question_spoken=qtext.get('1.0','end-1c').strip(),
                              answer_spoken=atext.get('1.0','end-1c').strip(), question_lang=qlang.get(),
                              answer_lang=alang.get(), content_version=card.content_version+1)
                    self.overrides[key] = updated; cards[key] = updated; self._dirty = True
                    refresh(updated); dialog.destroy()
                except ValueError as e: messagebox.showerror('Controllare i dati', str(e), parent=dialog)
            ttk.Button(dialog, text='Applica', command=save).pack(pady=10)
        tree.bind('<Double-1>', lambda e: edit())
        buttons = ttk.Frame(win); buttons.pack(fill='x', padx=12, pady=12)
        ttk.Button(buttons, text='Modifica selezionata', command=edit).pack(side='left')
        def listen():
            if not tree.selection() or self.busy: return
            c = cards[tree.selection()[0]]
            try: speed = float(self.speed.get())
            except tk.TclError: speed = 1.0
            win.destroy()
            def job(token, progress):
                engine = self._engine(); engine.preflight(token, progress)
                q = engine.cache.get(c.question_spoken, c.question_lang, speed, token)
                a = engine.cache.get(c.answer_spoken, c.answer_lang, speed, token)
                # Preview both fields as separate canonical WAVs; no output project is created.
                import wave
                from .audio import _append, _silence
                from .models import frames
                from . import SAMPLE_RATE
                path = self.data_root/'preview.wav'
                with wave.open(str(path), 'wb') as f:
                    f.setnchannels(1); f.setsampwidth(2); f.setframerate(SAMPLE_RATE)
                    _append(f, q, token); _silence(f, frames(.3), token); _append(f, a, token)
                return path
            def play(path):
                if os.name == 'nt':
                    import winsound
                    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                    self.status.set('Anteprima vocale in riproduzione.')
                else:
                    self.status.set('Anteprima WAV salvata nella cartella dati: preview.wav')
            self._start(job, play)
        ttk.Button(buttons, text='Ascolta selezionata', command=listen).pack(side='left', padx=8)
        ttk.Button(buttons, text='Chiudi', command=win.destroy).pack(side='right')

    def export_audio(self):
        if self.busy or not self.last_output: return
        path = filedialog.asksaveasfilename(initialfile='AudioCards_MP3.zip', defaultextension='.zip',
                                             filetypes=[('Archivio ZIP', '*.zip')])
        if path:
            source = self.last_output
            self._start(lambda token, progress: export_zip(source, Path(path), token, progress),
                        lambda _: self.status.set('Archivio ZIP esportato e verificato.'))

    def _open_folder(self, path: Path):
        try:
            if os.name == 'nt': os.startfile(str(path))
            else:
                import subprocess
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            messagebox.showinfo('Cartella', str(path), parent=self.root)

    def open_output(self):
        if self.last_output: self._open_folder(self.last_output)

    def about(self):
        messagebox.showinfo('AudioCards', f'AudioCards {__version__}\n\n'
            'Applicazione locale. Nessuna valutazione delle risposte o misura della memoria.\n'
            'I parametri di distribuzione sono euristiche, non intervalli ottimali dimostrati.\n\n'
            'Software GPL-3.0-or-later.\nCartella dati: '+str(self.data_root), parent=self.root)

    def close(self):
        if self.busy:
            if messagebox.askyesno('Generazione in corso',
                'Annullare il lavoro e chiudere dopo la fine dell\'unita attiva?', parent=self.root):
                self._closing = True; self.cancel()
            return
        if self._dirty and not messagebox.askyesno('Chiudi', 'Chiudere senza salvare le ultime modifiche?', parent=self.root):
            return
        self.root.destroy()


def launch(developer_system_tools: bool = False):
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk(); root.withdraw()
    home = application_root()
    if not check_writable(home/'data') or not check_writable(home/'output'):
        answer = messagebox.askyesno('Cartella non scrivibile',
            'La cartella dell\'app non e scrivibile. Salvare su questo computer?\n'
            'In questo modo i progetti NON vengono trasferiti copiando solo la cartella portatile.', parent=root)
        if not answer: root.destroy(); return
        home = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.local/share')))/'AudioCards'
        if not check_writable(home/'data') or not check_writable(home/'output'):
            messagebox.showerror('AudioCards', 'La cartella dati scelta non e scrivibile.', parent=root)
            root.destroy(); return
    lock = None
    try:
        lock = InstanceLock(home/'data'/'instance.lock')
        # Library loggers may include input text in debug messages; keep them quiet.
        logging.getLogger('piper').setLevel(logging.ERROR)
        logging.basicConfig(filename=home/'data'/'diagnostica.log', encoding='utf-8',
                            level=logging.WARNING, format='%(asctime)s %(name)s %(message)s')
        AudioCardsApp(root, home/'data', home/'output', developer_system_tools=developer_system_tools)
        root.deiconify(); root.mainloop()
    except Exception as e:
        messagebox.showerror('AudioCards - avvio non riuscito', str(e), parent=root)
        root.destroy()
    finally:
        if lock: lock.close()
