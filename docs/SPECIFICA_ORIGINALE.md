# AudioCards — Specifica tecnico-funzionale vincolante, v2.0
## Edizione Windows portable, offline, zero-installazione

**Stato:** specifica di implementazione per uno sviluppatore operativo; non attestazione di software già realizzato.  
**Destinatario:** sviluppatore Python/Windows.  
**Priorità:** P0 = obbligatorio, P1 = utile nell'MVP, P2 = successivo.  
**Data:** 27 ottobre 2026.

## 0. Decisione architetturale

AudioCards deve essere una **applicazione desktop Windows 11 x64**, distribuita in uno ZIP contenente una cartella con `AudioCards.exe`, modelli vocali, librerie e codificatore audio. L'utente estrae lo ZIP, apre la cartella ed esegue **un doppio clic**. Non deve installare Python, FFmpeg, Piper, modelli vocali, browser supplementari, estensioni o server. Non deve eseguire comandi, configurare variabili d'ambiente o possedere privilegi amministrativi.

**Correzione alla v1.0:** sostituire Streamlit con **Tkinter + ttk**, GUI nativa della libreria standard Python. È una scelta deliberata per ridurre i rischi di packaging e rimuovere web server localhost, browser, gestione porte, firewall e processi residui. Non usare Electron, Docker, WSL, Node.js, runtime Java o installer MSI per l'MVP.

**Build:** PyInstaller in modalità `onedir`, **non `onefile`**, su Windows x64. Un solo eseguibile *visibile* all'utente, ma più file interni nella cartella: non promettere un unico file autonomo. La directory estratta deve essere autosufficiente per l'esecuzione e la generazione offline.

**Limitazione esterna non eliminabile dal software gratuito:** Windows SmartScreen/Smart App Control, antivirus e policy aziendali possono segnalare o bloccare un eseguibile nuovo non firmato. Non disabilitare o aggirare protezioni. Non promettere esecuzione su qualsiasi PC; usare provenienza verificabile, checksum, test su macchina pulita e, se in futuro necessario, una firma attendibile (eventualmente a pagamento).

## 1. Contratto d'uso (P0)

1. Scaricare `AudioCards_Windows_x64_v2.0.zip` (o riceverlo dallo sviluppatore).
2. Estrarre **l'intera cartella**; non eseguire l'EXE direttamente dall'anteprima dello ZIP.
3. Aprire `AudioCards.exe` con doppio clic.
4. Incollare flashcard in righe `Domanda | Risposta`.
5. Selezionare **Apprendimento** o **Ripasso** e durata per MP3 (10, 20, 40, 60 minuti; default 20).
6. Premere **Genera audio**; vedere progresso e, al termine, **Apri cartella** / **Esporta ZIP**.

Nessun account, cloud, abbonamento o connessione Internet durante l'uso. I file MP3 devono essere riproducibili da normali app musicali di smartphone, autoradio e PC. Nessuna musica, effetti o annunci inseriti automaticamente.

## 2. UI: una finestra, quattro controlli principali (P0)

- Campo multilinea **Incolla le flashcard**.
- Selettore **Apprendimento / Ripasso**.
- Selettore **Durata MP3: 10 / 20 / 40 / 60 min**.
- Pulsante **Genera audio**.

Informazioni contestuali non obbligatorie: conteggio schede valide/errori, breve stima, barra progresso, errore comprensibile, pulsanti **Anteprima**, **Apri cartella**, **Esporta ZIP**. Il pannello **Avanzate** è inizialmente chiuso (lingua, voce, velocità, pausa, cartella dati, diagnostica). Non mostrare numeri di algoritmo, Fibonacci, code prioritarie o formule nel percorso ordinario. Non consentire doppi click che avviino job simultanei.

**Threading:** il thread GUI non esegue sintesi, scansione file o encoding. Worker dedicato con comunicazione tramite coda; aggiornamenti UI soltanto dal main thread mediante `after(...)`. Possibile annullare: fermare il job dopo un'unità atomica, terminare il sottoprocesso FFmpeg in modo controllato e lasciare cache valida. Alla chiusura, chiedere conferma se c'è un job attivo; evitare processi orfani.

## 3. Input e modello dati (P0)

Input principale `Domanda | Risposta` per riga; anche TSV e coppie `Q:`/`A:`; CSV esplicito come importazione secondaria. Parsing deterministico, senza LLM. Testi UTF-8 e caratteri Unicode (accenti, greco, simboli, apostrofi), con normalizzazione che **non altera il significato**. Scartare righe vuote; mostrare errori e duplicati senza correggere risposte in autonomia.

Schema `Card`: `card_id` stabile, `question_original`, `answer_original`, `question_spoken`, `answer_spoken`, `question_lang`, `answer_lang`, `source_order`, `content_version`. Una singola parola può essere linguisticamente ambigua: rilevamento automatico **best-effort**; default italiano quando manca evidenza, correzione manuale per singola scheda. Distinguere date ambigue e formule che richiedono lettura esplicita. Non inviare mai il testo a servizi esterni.

Schema `Event`: `event_id`, `card_id`, `kind` (`INTRO`, `RECALL_1`, `RECALL_2`, `REVIEW`), `due_s`, `start_s`, `end_s`, `duration_s`, `q_asset_id`, `a_asset_id`, `pause_s`, `gap_s`, `session_id`, `scheduler_version`.

## 4. DARS: modello didattico e programmazione (P0)

**Apprendimento:** per ogni scheda esattamente 1 `INTRO` = domanda → transizione tecnica ~0,3 s → risposta **senza pausa di recupero**, seguita da esattamente 2 richiami = domanda → pausa → risposta. Niente ripetizioni iniziali extra. Intervalli-obiettivo configurabili nel codice: `RECALL_1` a +180 s dalla fine dell'introduzione, `RECALL_2` a +600 s dalla fine del richiamo precedente. Non sono valori scientificamente ottimali; versionarli come euristiche.

**Ripasso:** una sola domanda → pausa → risposta per scheda per sessione; nessuna INTRO. Per la prima versione creare sessioni di ripasso nei giorni suggeriti +1, +3, +7, +14 rispetto a **una data di completamento scelta o dichiarata dall'utente**, non rispetto a un ascolto presunto. Se la data non è indicata, usare etichette relative `G+1`, `G+3` ecc.; non scrivere date di calendario inventate. Ogni sessione è autonoma e può richiedere più chunk. Ordine delle schede pseudo-casuale con seed salvato; nessun duplicato nella sessione.

**Tempo di scheduling Apprendimento:** tempo audio cumulativo, non tempo di orologio. Lo scheduler opera **dopo** che sono state misurate le durate reali dei segmenti TTS. Il confine fra due MP3 non azzera tempo, intervalli o priorità. La pausa reale dell'utente fra MP3 non è tracciata; il prodotto non dichiara di misurare l'apprendimento effettivo.

**Pausa di recupero:** `pause_s = min(35, max(4, 1.3 * durata_risposta_s))`. Può essere diversa per ogni scheda. Parametri opzionali nel pannello Avanzate. Distinguere pausa di recupero dalla distanza temporale fra richiami.

**Scheduling deterministico:** due strutture: schede ancora da introdurre nell'ordine originale, min-heap dei richiami per scadenza. A ogni iterazione:

1. Se esiste un richiamo scaduto (`due <= clock`), programmarne uno, privilegiando il maggior ritardo; tie-break stabile per tipo, origine, id.
2. Se si sono succeduti almeno 3 richiami e restano INTRO, introdurre una nuova scheda quando il ritardo massimo dei richiami in attesa è <=120 s; altrimenti recuperare il più urgente.
3. Se nessun richiamo è scaduto e restano schede nuove, introdurre la successiva.
4. Dopo ciascun evento, aggiornare `clock` e creare il richiamo successivo (solo dopo la fine dell'evento precedente).
5. Se non restano INTRO ma il prossimo richiamo è futuro, anticipare **solo** per colmare un vuoto altrimenti silenzioso: mantenere, se possibile, una separazione minima di 15 s; usare silenzio di attesa per massimo 20 s. Registrare nel manifest la deviazione negativa/positiva. Segnalare spacing limitato in serie di 1–2 flashcard.
6. Terminare quando tutte le INTRO e i due richiami di tutte le schede risultano emessi. È vietato terminare per il raggiungimento del target MP3; la durata regola solo il chunking.

**Invarianti verificabili:** 1 INTRO e 2 RECALL per card; nessun RECALL precede INTRO; nessun evento spezzato; nessun segmento perso; nessun aumento spurio dei richiami; ogni event contiene Q e A; timeline monotona e senza sovrapposizioni; riproducibilità con stessi input e parametri; terminazione per dataset finiti e durate positive.

**Nota epistemica:** il feedback è la risposta audio che segue il tentativo mentale, ma il software non verifica che il recupero sia avvenuto né che sia corretto. Non chiamare questa implementazione Leitner adattivo.

## 5. Sintesi vocale: dipendenza risolta e inclusa (P0)

**Provider:** Piper TTS mantenuto dal progetto OHF-Voice (`piper-tts`), utilizzato attraverso API Python diretta; CPU, italiano e inglese. Includere nel bundle esattamente due modelli vocali validati (uno IT, uno EN), file `.onnx`, `.onnx.json`, e tutte le risorse fonetiche native necessarie. Niente download automatici al primo avvio. **Non assumere** che `pip install` per sviluppatore produca automaticamente un binario Windows autonomo: testare PyInstaller con `onnxruntime`, librerie native di Piper, espeak-ng e relativi file dati. Se la modalità Python in-process non supera il test su Windows pulito, sostituire l'adapter TTS con un eseguibile CLI Piper compilato e corredato di dipendenze, senza modificare la UI o il contratto d'uso. Il CLI C++ può richiedere runtime MSVC: verificarne la disponibilità e includere legalmente i DLL necessari oppure scegliere la variante con meno prerequisiti; **nessun installer VC++ manuale ammesso**.

**Scelta delle voci:** test comparativo preventivo su italiano, inglese, date, termini tecnici e formule; verificare prima la licenza/`MODEL_CARD` esatta di ciascuna voce. La scelta dei modelli è bloccata in un file di lock con hash SHA-256 e attribuzioni; evitare URL `latest` non versionati. Il TTS deve essere un adapter sostituibile, ma l'MVP include un solo provider concreto.

**Cache:** una generazione per ciascuna combinazione `hash(text_spoken, lang, voice_model_hash, speed, tts_version, normalization_version)`. Scrivere in file temporaneo e rinominare atomicamente a completamento; correggere asset incompleti. Generare in PCM/WAV, mai ricreare le medesime frasi a ogni richiamo. Preview vocale facoltativa su richiesta, senza sintetizzare tutto il dataset durante il semplice incolla.

**Preflight obbligatorio al primo avvio:** presenza e checksum di modelli e binari; prova locale di sintesi per entrambe le lingue con output non vuoto; prova encoder FFmpeg. Non fermare il programma in silenzio: errore diagnostico con descrizione leggibile e file log.

## 6. Rendering audio (P0)

- PCM di lavoro: mono, 16-bit, frequenza canonica definita (es. 24 kHz); convertire ciascun segmento una volta nella cache se necessario.
- Eventi assemblati da segmenti normalizzati e silenzi generati con Python `wave`, scrivendo a blocchi su disco; **non accumulare un percorso di molte ore in RAM**.
- Transizione domanda-risposta per INTRO ~0,3 s; distanza inter-evento ~1 s configurabile e inclusa nel calcolo delle durate.
- Al completamento di ogni chunk WAV, convertire una sola volta con FFmpeg incluso, chiamato con `subprocess.run([...], shell=False)` e percorsi assoluti, senza dipendere dal PATH.
- Bundle FFmpeg con una build verificata che supporti `libmp3lame` (o encoder MP3 selezionato), preferibilmente variante LGPL ove appropriato; `ffmpeg -encoders` e encode/decode smoke test sono parte del build. Non scaricare binari da siti non verificati.
- MP3: 128 kbps mono, metadati titolo e numero della parte facoltativi. Niente suoni/musica introduttivi.
- Controllare con `ffprobe` incluso o altro parser affidabile: file presente, codec MP3, durata coerente con la timeline (tolleranza definita per encoder delay), dimensione non nulla; in caso di errore non pubblicare il file.
- Lasciare in RAM soltanto i buffer audio strettamente necessari; temp files eliminati alla fine o recuperati dopo crash.

## 7. Chunking senza perdita (P0)

**Prima scheduling globale, poi chunking.** Le durate obiettivo 10/20/40/60 min valgono per **singolo MP3**, mai per il numero di flashcard. Suddividere la lista degli eventi soltanto fra eventi completi. Usare algoritmo lineare che scelga il confine vicino al target senza spezzare eventi; ribilanciare facoltativamente gli ultimi 2 chunk per evitare un finale minuscolo, senza riordinare nulla. Tolleranza ordinaria ±10%, salvo chunk finale o evento più lungo del target. Mai riempire con ripetizioni artificiali o silenzi lunghi. Il manifest deve permettere di ricostruire l'intera timeline concatenando gli eventi dei file.

Una sessione Ripasso è un blocco separato: vietato concatenare eventi di giorni diversi nello stesso file. I nomi sono ordinali e ordinabili lessicograficamente: `Apprendimento_001.mp3`, `Ripasso_G+01_001.mp3` ecc.

## 8. Persistenza e vera portabilità dei dati (P0)

Due modi espliciti:

- **Modo portatile, preferito:** dati in `AudioCards/data/` e output in `AudioCards/output/` adiacenti al programma. L'intera cartella può essere copiata su un altro PC. Usarlo quando la cartella è scrivibile.
- **Modo protetto, fallback:** se la directory non è scrivibile, chiedere conferma per usare `%LOCALAPPDATA%\\AudioCards` e mostrare chiaramente «I progetti sono salvati su questo PC, non nella cartella portatile». Non spostare i dati silenziosamente.

Usare sempre path risolti da `sys.executable` (cartella EXE), non dalla current working directory. Le risorse impacchettate si risolvono separatamente con `__file__` / `sys._MEIPASS`; **non scrivere** dentro `_internal`. Supportare percorsi con spazi e Unicode, utenti non amministratori, cartelle OneDrive/Downloads, copie su USB e disco quasi pieno. Se archivio su USB viene rimosso durante la generazione: arrestare e segnalare il problema, non corrompere i file completi.

SQLite: schema versionato, migrazioni transazionali, connessione di scrittura gestita dal worker appropriato, database chiuso all'uscita, backup prima di migrazioni. I file MP3 di output e i progetti devono poter essere esportati in ZIP. Aggiornare l'app sostituendo solo i binari, conservando `data/` e `output/` mediante istruzione di aggiornamento esplicita; non sovrascrivere mai i dati dell'utente.

## 9. Distribuzione Windows (P0)

### 9.1 Layout artefatto

```text
AudioCards_Windows_x64_v2.0.zip
└── AudioCards/
    ├── AudioCards.exe               # unico eseguibile da cliccare
    ├── _internal/                   # Python embedded, Tcl/Tk, Piper, ONNX e librerie
    ├── models/
    │   ├── it_voice.onnx
    │   ├── it_voice.onnx.json
    │   ├── en_voice.onnx
    │   └── en_voice.onnx.json
    ├── tools/
    │   ├── ffmpeg.exe
    │   └── ffprobe.exe
    ├── licenses/                    # dipendenze, modelli, attribuzioni
    ├── README_PRIMA_APERTURA.txt
    ├── VERSION.json
    └── checksums.sha256
```

`data/` e `output/` vengono create all'avvio quando la cartella è scrivibile; non vanno inserite con dati di sviluppo in una release. In alternativa, fornire directory vuote solo se necessario per il packaging. Eseguire il programma **dopo aver estratto lo ZIP**.

### 9.2 Build deterministica

- Build **su Windows 11 x64**, non cross-compilazione Linux→Windows.
- Ambiente pulito e versioni **pin** (`requirements.lock` e versione Python).
- PyInstaller `--onedir --windowed`; file `.spec` versionato con data/native DLL esplicitamente inclusi; `--clean` in CI.
- `sys.executable` per posizione dell'EXE; `sys._MEIPASS`/`__file__` per risorse embedded; non assumere un path assoluto.
- `multiprocessing.freeze_support()` all'entrypoint se usati processi Python su Windows frozen.
- No installazione in Registry, no servizio Windows, no cron, no autostart, no elevazione UAC, no download a runtime.
- Se sono necessari runtime C/C++, devono essere già inclusi con licenza verificata. Una build che richiede all'utente di installare Visual C++ Redistributable fallisce il requisito P0.
- Pubblicare checksum SHA-256 di ZIP ed EXE, dimensioni finali e elenco esatto dei componenti.

### 9.3 SmartScreen: eccezione non mascherabile

Gli eseguibili unsigned possono essere segnalati o bloccati da SmartScreen/Smart App Control, anche se innocui. Non è garantibile «nessun avviso» a costo zero. La release personale deve essere distribuita tramite canale fidato con checksum verificabile. Mai consigliare di disattivare Defender o i controlli di sicurezza. Se i criteri di Windows bloccano l'EXE, documentare il limite e valutare firma attendibile o percorso di distribuzione diverso.

### 9.4 Licenze

Piper attuale è GPL-3.0: **prima di distribuire il bundle**, definire licenza del progetto compatibile, obblighi di sorgente e copyright/notice; la soluzione più semplice per un progetto personale distribuibile è rendere AudioCards open source compatibile con GPL-3.0. Le voci hanno licenze proprie da controllare sui rispettivi `MODEL_CARD`. FFmpeg è LGPL o GPL in funzione delle opzioni di compilazione; includere note, fonte e condizioni pertinenti. Non assumere che «gratis» equivalga a «libero da obblighi di redistribuzione». Nessuna licenza viene automaticamente applicata agli MP3 prodotti senza analisi specifica dei termini delle voci selezionate.

## 10. Sicurezza, privacy e robustezza (P0)

- Nessuna connessione di rete, nessuna telemetria o analytics, nessuna apertura di porte TCP; testare con rete disabilitata e monitoraggio richieste in uscita.
- Sanitizzare i **nomi file** separatamente dal testo parlato; non usare mai il contenuto della flashcard come comando shell o percorso diretto.
- Limiti difensivi configurabili per lunghezza input, singolo testo, disco necessario e numero di schede; un dataset eccessivo deve produrre errore leggibile e non crash.
- Operazioni atomiche: output temporaneo + rinomina; file incompleti non devono apparire come file finali.
- Se manca spazio, il dispositivo viene scollegato o FFmpeg fallisce, preservare database e file già riusciti, consentire riprova.
- Log locale con timestamp, versione, exception e fase, senza registrare integralmente le flashcard per default; esportazione diagnostica volontaria.
- Controllare checksum delle dipendenze all'avvio/installazione del bundle; evitare script `.bat` o PowerShell e qualunque aggiornamento automatico.
- GUI responsiva; elaborazione seriale di default per evitare saturazione CPU/RAM; parallelismo solo se misurato come vantaggioso.
- Uso personale: non costruire protezioni DRM né login.

## 11. Obiezioni prevedibili e decisioni finali

| Obiezione | Soluzione vincolante |
|---|---|
| «Un file EXE solo è più semplice» | Un solo EXE **visibile**, ma release `onedir`: avvio più rapido, file di modelli grandi e DLL più gestibili. |
| «Streamlit era già previsto» | Sostituire con Tkinter/ttk: niente server/porte/browser/firewall. |
| «Piper potrebbe non avviarsi dopo packaging» | Preflight TTS su PC pulito; inclusione esplicita DLL/dati; adapter sostituibile con CLI testato. |
| «Il PC non ha Python, VC++, FFmpeg» | Bundle completo; nessuna dipendenza manuale P0. |
| «Antivirus/SmartScreen blocca EXE» | Non occultare: checksum, provenienza fidata, diagnosi, futura firma se necessaria. |
| «Se copio la cartella perdo i progetti» | Preferire `data/` adiacente; fallback AppData solo comunicato. |
| «Scarico lo ZIP e apro EXE senza estrarre» | `README_PRIMA_APERTURA` e messaggio sullo ZIP: estrazione obbligatoria. |
| «L'interfaccia si blocca per 1000 flashcard» | Worker con coda e UI nel thread principale; progressi, annullamento e cache. |
| «Durata MP3 errata» | Durate PCM reali, chunking post-scheduling, controllo ffprobe. |
| «FFmpeg non converte in MP3» | Check encoder durante build e preflight con test di conversione. |
| «Un evento supera 20 min» | Non tagliare; chunk eccezionalmente lungo e avviso. |
| «100 card non entrano in 20 minuti» | Generare N chunk preservando la sequenza globale. |
| «Le scadenze delle ripetizioni collidono» | Heap con priorità stable; overdue log; fairness condizionata. |
| «Pochissime flashcard creano silenzi lunghissimi» | Attesa limitata, intervallo compresso dichiarato. |
| «Date/formule sono pronunciate male» | Campo spoken separato, warning per ambiguità e correzione per scheda. |
| «Il ripasso non sa quando ho davvero studiato» | Sessioni relative; data di completamento richiesta solo per date assolute. |
| «Aggiorno e perdo file» | Separazione dati/binari, backup e migrazione transazionale. |
| «L'app fa chiamate nascoste a internet» | Test offline, network access proibito per l'MVP. |
| «Uso cartella con lettere accentate o USB» | Pathlib/Unicode, path assoluti, test di scrittura e disconnessione. |
| «Windows ARM o policy restrittive» | Supporto nativo garantito solo x64 testato; non promettere bypass policy. |

## 12. Piano di build e collaudo (P0)

**Gate 0 — Fattibilità vocale:** due modelli IT/EN scelti per qualità e licenza; sintetizzare almeno 10 schede miste; verificare ONNX/espeak, FFmpeg e licenze. **Se non funziona su PC Windows pulito, non procedere all'interfaccia.**

**Gate 1 — Core senza audio:** parser, data model, scheduler, chunker e manifest con durate simulate; tests per 1, 2, 10, 100, 1.000 schede, eventi lunghi, conflitti e determinismo.

**Gate 2 — Audio reale:** cache, PCM canonico, salvataggio atomic, FFmpeg MP3, verifica durata e ascolto manuale; test 100 flashcard in più chunk.

**Gate 3 — Windows frozen:** PyInstaller `onedir`, test **solo del pacchetto ZIP estratto** su una **VM Windows 11 x64 pulita**, utente standard, senza Python/FFmpeg/Piper e senza internet. Testare con percorso con spazi e caratteri Unicode, disco non scrivibile, USB/disco rimosso, app chiusa durante generazione, secondo avvio, copia su altra directory e aggiornamento. Verificare che non compaia console né richiesta UAC e che l'app si chiuda completamente. SmartScreen non può essere bypassato: registrare l'esito reale separatamente.

**Gate 4 — Usabilità:** un utente non tecnico deve generare un archivio completo partendo da 100 flashcard usando solo i quattro controlli principali, senza istruzioni di terminale e senza riaprire impostazioni avanzate.

## 13. Test minimi automatizzati (P0)

- `T01` INTRO = Q + risposta, senza pausa di recupero.
- `T02` N card -> N INTRO e 2N RECALL; zero perdite.
- `T03` RECALL segue sempre INTRO, con clock monotono.
- `T04` Pause = clamp(1.3*T,4,35) e match audio entro tolleranza PCM.
- `T05` Concatenare la lista eventi dei chunk restituisce la timeline globale byte-per-byte nel manifest.
- `T06` L'ultimo file può essere breve, nessun evento spezzato.
- `T07` Review: una Q-pausa-A per card per sessione; +1/+3/+7/+14, no INTRO.
- `T08` Stesso seed + stesso input/config -> stesso planning.
- `T09` Cache: secondo render senza nuova sintesi per segmenti identici.
- `T10` Audio MP3 file decodificabile con durata e contenuto consoni.
- `T11` Un job annullato non lascia MP3 corrotto contrassegnato come completo.
- `T12` Avvio ZIP estratto su Windows pulito senza installare nulla.
- `T13` Nessun traffico rete o porta TCP durante uso offline.
- `T14` Data portatile copiata su secondo PC e progetto riapribile.
- `T15` Path Unicode e file di testo misto IT/EN funzionali.
- `T16` README, license cards, checksums e file sorgente/obblighi di licenza verificati.

## 14. Output e directory di lavoro

- Percorso apprendimento: `output/<progetto>/Apprendimento/Apprendimento_001.mp3`, `...002.mp3`, ecc.
- Ripassi: `output/<progetto>/Ripasso/G+01/Ripasso_G+01_001.mp3` ecc.
- Esportazione ZIP con MP3 ordinati, breve `LEGGIMI.txt` e `manifest.json` (sessioni, ordine file, date relative, timeline di pianificazione, checksum, versioni).
- I `manifest` distinguono eventi **programmati**, MP3 **generati** e sessioni **ascoltate** (sconosciute). Nessun messaggio «hai imparato 100 schede» o avanzamento cognitivo inventato.
- Una voce italiana e una inglese predefinite; anteprima e correzione parlato disponibili nel pannello avanzato.

## 15. Definition of Done

È pronto quando **un normale utente Windows 11 x64, senza Python e senza privilegi amministrativi**, può estrarre lo ZIP, avviare `AudioCards.exe`, incollare 100 flashcard, scegliere Apprendimento e 20 minuti, generare tutti gli MP3 necessari, ascoltare una prima presentazione domanda-risposta senza pausa e richiami successivi con pausa, riaprire il progetto, produrre il ciclo di Ripasso, copiare cartella e dati su altro PC e ottenere identico funzionamento offline. Il codice sorgente, lock dei pacchetti, spec PyInstaller, manifest delle dipendenze/licenze e risultati dei test devono essere consegnati insieme al bundle.

**Non può essere garantito universalmente** l'avvio di un EXE nuovo e non firmato su sistemi soggetti a Smart App Control, SmartScreen restrittivo, antivirus o policy IT; il limite va documentato, non nascosto. Il software può restare interamente gratuito, ma una firma attendibile e la distribuzione pubblica professionale potrebbero comportare costi.

## 16. Fonti tecniche primarie da usare nella realizzazione

- Python `tkinter` / `ttk`: https://docs.python.org/3/library/tkinter.html
- PyInstaller `onedir`: https://pyinstaller.org/en/stable/operating-mode.html
- PyInstaller runtime paths: https://pyinstaller.org/en/stable/runtime-information.html
- Piper mantenuto: https://github.com/OHF-Voice/piper1-gpl
- Piper C++ CLI/Windows runtime: https://github.com/OHF-Voice/piper1-gpl/blob/main/libpiper/README.md
- Voci e `MODEL_CARD`: https://huggingface.co/rhasspy/piper-voices
- FFmpeg licenze: https://www.ffmpeg.org/legal.html
- SmartScreen ufficiale Microsoft: https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation
- Smart App Control Microsoft: https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview

## 17. Precedenza e controllo delle modifiche

**v2.0 prevale sulla v1.0** in caso di divergenza, soprattutto per UI (`Tkinter` sostituisce `Streamlit`), confezionamento Windows, localizzazione delle risorse, dati portatili, avvio senza dipendenze, licenze, SmartScreen e test su PC pulito. Mantiene dalla v1.0 le regole didattiche, le durate 10/20/40/60, la sequenza INTRO/RECALL, le pause, le due modalità, il chunking globale e la produzione MP3. Qualsiasi deviazione dai requisiti P0 va registrata in un documento `DECISIONS.md`, con motivazione, impatto per l'utente e test di regressione.
