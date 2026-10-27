# Componenti e condizioni di rilascio

Questo archivio contiene codice AudioCards GPL-3.0-or-later, non i binari Windows
ne i modelli vocali. Non contiene file di font.

| Componente previsto | Indicazione da verificare sul pacchetto effettivo |
|---|---|
| CPython/Tkinter/Tcl/Tk | Includere le rispettive licenze Python, Tcl/Tk e notices |
| Piper 1.8.0 | GPL-3.0-or-later; conservare codice sorgente corrispondente e notices |
| ONNX Runtime, NumPy e dipendenze | Includere le licenze delle esatte versioni risolte |
| Paola medium | Dataset dichiarato CC0; model card indica fine-tuning da lessac; verificare la catena |
| LJ Speech medium | Dataset dichiarato public domain; conservare scheda e condizioni del repository |
| FFmpeg Gyan essentials 9.0.2 | Build GPLv3, non LGPL; risolvere obblighi di sorgente corrispondente |
| Microsoft VC runtime | Solo DLL redistribuibili con licenza applicabile; non copiare indiscriminatamente System32 |
| PyInstaller | Rispettare licenza e bootloader exception applicabili alla versione pin |

Le versioni e gli hash del download vengono acquisiti dallo script di build.
I notices da soli non sostituiscono il sorgente corrispondente richiesto da GPL.
Il progetto non dichiara approvata la redistribuzione di un bundle non ancora costruito.

Fonti primarie consultate nella preparazione:
- https://pypi.org/project/piper-tts/1.8.0/
- https://github.com/OHF-Voice/piper1-gpl/tree/v1.8.0
- https://huggingface.co/rhasspy/piper-voices/blob/main/it/it_IT/paola/medium/MODEL_CARD
- https://huggingface.co/datasets/paolapersico1/Voice-Dataset-Italian/blob/main/README.md
- https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD
- https://www.gyan.dev/ffmpeg/builds/
- https://ffmpeg.org/legal.html
- https://pyinstaller.org/en/stable/operating-mode.html
