"""Actual Tk tests. Run under a desktop or xvfb-run; no screenshot mockups."""
import os
from pathlib import Path
import time
import tkinter as tk
from tkinter import messagebox
import pytest
from audiocards.gui import AudioCardsApp
from audiocards.engine import Engine

pytestmark = pytest.mark.skipif(os.name != 'nt' and not os.environ.get('DISPLAY'), reason='A display/Xvfb is required for real Tk tests.')

@pytest.fixture
def gui(tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(messagebox, 'showerror', lambda title, text, **kw: errors.append(text))
    monkeypatch.setattr(messagebox, 'showinfo', lambda *a, **kw: None)
    monkeypatch.setattr(messagebox, 'askyesno', lambda *a, **kw: True)
    root = tk.Tk(); root.withdraw()
    app = AudioCardsApp(root, tmp_path/'data', tmp_path/'output')
    yield app, errors
    try:
        if app.busy:
            app.cancel()
            pump(app)
        for task in root.tk.call('after','info'):
            root.after_cancel(task)
        root.destroy()
    except tk.TclError:
        pass


def pump(app, timeout=20):
    start = time.monotonic()
    while app.busy:
        app.root.update()
        if time.monotonic()-start > timeout:
            raise AssertionError('GUI worker did not finish; potential deadlock.')
        time.sleep(.01)
    app.root.update()


def test_gui_parse_save_and_restore_csv(gui):
    app, errors = gui
    app._parser_format = 'csv'
    app.text.insert('1.0','What is this?,A test')
    app._update_count(); app.save_project()
    assert len(app._parse().cards) == 1
    data = app.store.load(app.project_id)
    app._load_payload(data)
    assert app._parser_format == 'csv' and not app._parse().errors
    assert not errors


def test_gui_advanced_panel_and_preview(gui):
    app, errors = gui
    app.text.insert('1.0','Che cosa e questo? | Un esempio.')
    app._toggle_advanced(); app.root.update()
    assert app.advanced.winfo_manager() == 'pack'
    app._toggle_advanced(); app.root.update()
    assert not app.advanced.winfo_manager()
    app.preview(); app.root.update()
    assert len([w for w in app.root.winfo_children() if isinstance(w,tk.Toplevel)]) == 1
    assert not errors


def test_gui_runs_actual_generation_without_blocking_main_thread(gui, tmp_path, tone, tools):
    app, errors = gui
    app.engine = Engine(tone,tools,tmp_path/'data',tmp_path/'output')
    app.text.insert('1.0','What is the test? | A short example.')
    app.generate()
    assert app.busy
    heartbeat = []
    app.root.after(1,lambda: heartbeat.append(True))
    pump(app)
    assert heartbeat and not errors
    assert app.last_output and (app.last_output/'manifest.json').is_file()
    assert str(app.generate_btn['state']) == 'normal'


def test_gui_callback_error_is_visible_not_unhandled(gui):
    app, errors = gui
    def broken(_): raise OSError('Synthetic storage error')
    app._start(lambda token,progress: None, broken)
    pump(app)
    assert errors == ['Synthetic storage error']
    assert not app.busy


def test_gui_cancel_worker_without_orphan(gui):
    app, errors = gui
    def job(token,progress):
        while True:
            token.check(); time.sleep(.01)
    app._start(job)
    app.root.after(40, app.cancel)
    pump(app)
    assert not errors and not app.busy
    assert 'annullata' in app.status.get().lower()
