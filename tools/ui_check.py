"""Developer-only GUI launch, layout screenshot and basic interaction checks."""
import os
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from audiocards.gui import AudioCardsApp

base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
root = tk.Tk()
app = AudioCardsApp(root, base/'data', base/'output')
app.name.set('Esempio - Italiano e inglese')
app.text.insert('1.0', '''Che cosa contiene una flashcard? | Una domanda e una risposta.
Quando compare la prima risposta? | Subito dopo la prima domanda.
What comes after a review question? | A pause, then the answer.
A cosa serve la pausa? | A provare a formulare mentalmente la risposta.
How are long courses divided? | Into consecutive audio files.
Quale data compare nell'esempio? | 2026-10-27''')
app._update_count()
root.update()
assert app._parse().errors == []
assert len(app._parse().cards) == 6
app.save_project()
assert len(app.store.list_projects()) == 1
app.status.set('6 schede pronte. Il numero di MP3 sara calcolato dopo la sintesi vocale.')
root.update()
try:
    from PIL import ImageGrab
    ImageGrab.grab().save(str(base/'interfaccia.png'))
except Exception as e:
    print('Screenshot unavailable:', type(e).__name__)
app._toggle_advanced(); root.update()
app._toggle_advanced(); root.update()
app.preview(); root.update()
try:
    from PIL import ImageGrab
    ImageGrab.grab().save(str(base/'anteprima.png'))
except Exception:
    pass
root.destroy()
print('GUI launch, parsing, save, advanced panel and preview: passed')
