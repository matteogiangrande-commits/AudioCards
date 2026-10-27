# AudioCards - Rapporto di esecuzione e limiti della consegna

Data: 27 ottobre 2026. Versione: 2.0.0-dev.1.

## Esito principale

**135 test automatici superati, zero fallimenti, zero test saltati nell'esecuzione
finale sotto Xvfb.** Il report JUnit originale e in `reports/junit.xml`.
Sono stati usati Python 3.13.5, Linux x64, Tkinter/Xvfb e
FFmpeg/ffprobe realmente disponibili nell'ambiente di sviluppo.

**Non e stato prodotto un eseguibile Windows.** La consegna e il codice sorgente
con test, demo e procedure di build. Il requisito di avvio Windows con doppio clic
rimane aperto, nonostante il nucleo e l'interfaccia siano stati implementati.

## Cosa coprono i test

Parsing pipe, escaping, virgolette, TSV, CSV, Q/A multilinea, Unicode, duplicati,
formati ambigui, limiti input, configurazioni non valide, date e formule.
Scheduler su 1, 2, 3, 10, 100, 1.000 e 10.000 schede, 20 distribuzioni diverse
di durate simulate, conteggi esatti, ordine, fairness, determinismo, pause,
chunking senza perdite con target 10/20/40/60 minuti, eventi molto lunghi,
sessioni di ripasso separate e nessuna data inventata.

Cache con hash, rigenerazione di asset corrotti, WAV vuoti o troncati, MP3
codificati e decodificati con FFmpeg, durata, ZIP, annullamento, timeout,
argomenti non interpretati da shell, portabilita SQLite, blocco di seconda istanza,
versione database futura, recupero dopo interruzione e protezione da path traversal.

La GUI e stata avviata realmente: parsing, salvataggio, riapertura CSV,
pannello avanzato, anteprima, generazione audio tramite worker con heartbeat del
thread principale, annullamento e gestione di un errore nel callback.

## Prova parlata di 100 flashcard

| Misura | Risultato osservato |
|---|---|
| Flashcard | 100 |
| INTRO | 100 |
| RECALL_1 | 100 |
| RECALL_2 | 100 |
| Eventi complessivi | 300 |
| MP3 | 3 |
| Durata file 1 | 1.195,200 secondi = circa 19:55 |
| Durata file 2 | 1.199,400 secondi = circa 19:59 |
| Durata file 3 | 831,144 secondi = circa 13:51 |
| Durata totale | 3.225,744 secondi = circa 53:46 |
| Schede omesse | 0 |
| Eventi tagliati ai confini | 0 |
| Richiami anticipati a fine coda | 24; scostamenti registrati |
| Verifica formato/durata/decodifica/hash | Superata |

Il tempo target e la durata di ogni file, non del percorso completo.
Il file finale e volutamente piu breve, senza riempimenti artificiali.
Una prima esecuzione e stata interrotta dal limite dell'ambiente dopo parte della
sintesi: la nuova esecuzione ha riutilizzato la cache e completato il percorso.
Il controllo finale ha verificato separatamente conteggi, ordine globale e hash
di tutti e tre gli MP3.

## Demo bilingue allegato

Otto flashcard, 24 eventi, un MP3 di **213,048 secondi** (circa 3:33).
Italiano e inglese, prima presentazione senza pausa di recupero, richiami con
pausa e risposta. Con cosi poche schede gli intervalli sono compressi; il manifest
riporta 16 richiami anticipati. La demo non prova intervalli pieni di 3/10 minuti.

**Voce utilizzata: eSpeak di sviluppo, non Piper.** I test di basso livello usano
anche toni sintetici dichiarati. L'adapter Piper non e stato collaudato con i
modelli reali e non si presume che eSpeak ne rappresenti la qualita acustica.

## Limiti non superati in questa sessione

- Build PyInstaller Windows x64: non eseguita.
- EXE pronto al doppio clic: non presente nell'archivio.
- Installazione del lock delle dipendenze Windows: non eseguita.
- Piper e modelli IT/EN reali: non eseguiti; download non disponibile nel container.
- Collaudo su Windows 11 pulito, senza runtime installati: non eseguito.
- Monitoraggio della rete delle librerie native: non eseguito. I test bloccano
  tentativi Python di connessione nel percorso verificato con la voce di test;
  questo non equivale a certificare l'intero runtime nativo Piper/Windows.
- Qualita vocale per tutto il materiale dell'utente: non misurata.
- Revisione di licenze e sorgente corrispondente del bundle finale: da completare.
- Beneficio mnemonico e superiorita degli intervalli scelti: non misurati.

## Contenuti del pacchetto sorgente

27 file Python, specifica originale, implementazione, test, configurazione
PyInstaller, script di acquisizione risorse con checksum e revisioni fisse,
workflow Windows candidato non avviato, documentazione, decisioni e registri.
Non sono inclusi binari Windows, modelli neurali o file di font.

La presenza degli script di build non dimostra che la build funzioni: e necessario
eseguirla e superare i gate indicati in `docs/RELEASE_CHECKLIST.md`.
