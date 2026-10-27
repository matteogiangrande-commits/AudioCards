# Decisioni, deviazioni e gate di rilascio

## D01 - La consegna e sorgente, non release Windows

La specifica P0 richiede Windows 11 x64, EXE PyInstaller e test su VM pulita.
L'ambiente effettivamente disponibile e Linux x64. Non sono stati eseguiti build
Windows, emulazione di Windows o collaudo su Windows 11. L'interfaccia e il nucleo
sono stati realizzati e verificati qui anziche fermare l'intero lavoro al Gate 0.
**Deviazione esplicita:** i gate non sono stati completati in ordine e la Definition
of Done della specifica non e raggiunta. Il pacchetto e nominato Sorgente, non Windows Portable.

## D02 - Demo e test parlati usano eSpeak, non Piper

I download nell'ambiente container non hanno funzionato. L'adapter Piper e scritto
contro l'API primaria della versione 1.8.0, ma non e stato eseguito con i modelli reali.
Per non simulare una prova vocale, gli MP3 dimostrativi sono etichettati eSpeak.
La GUI del prodotto non effettua fallback a eSpeak. L'assenza delle risorse Piper
produce un errore comprensibile, senza download, servizi a pagamento o cloud.

## D03 - Tempi esatti in campioni, non floating point cumulativo

La pipeline usa PCM mono 24 kHz/16 bit e indici interi di campione. I secondi sono
una vista del manifest. Un evento include attesa iniziale eventuale, domanda,
transizione INTRO o pausa RECALL, risposta e gap finale. L'intervallo al richiamo
successivo si misura dalla fine dell'evento precedente, incluso il gap finale.
Questo elimina deriva fra scheduler e renderer. Il controllo MP3 ammette 0,25 s
per il ritardo/padding dell'encoder, senza tagliare parti del contenuto.

## D04 - Timing in piccoli dataset e a fine percorso

Si mantengono 1 INTRO + 2 RECALL, delay obiettivo 180 e 600 s, fairness 3/120 s,
separazione minima preferita 15 s e attesa aggiunta al massimo 20 s. Quando non c'e
altro materiale, il richiamo e anticipato e lo scostamento e registrato. Non si
pretende che un percorso cosi compresso conservi gli intervalli ideali. Non si
riempiono MP3 con minuti di silenzio. Le finestre non vengono azzerate al chunking.

## D05 - Determinismo e generazione vocale

L'ordine e il timing sono deterministici a parita di schede, configurazione e durate
PCM effettive. I segmenti sono riutilizzati dalla cache. Nell'adapter Piper rumore
prosodico e durata stocastica sono impostati a zero; questa scelta deve passare il
test di qualita vocale. Non e promessa identita binaria dei risultati ONNX fra CPU
architetturalmente diverse o dopo cambiamenti delle librerie.

## D06 - Testo lungo e annullamento

La sintesi divide internamente il testo in gruppi di massimo 600 caratteri, cercando
punteggiatura o spazi. L'ordine delle parole non cambia. Il singolo evento didattico
rimane indivisibile fra MP3. La cancellazione viene controllata fra i gruppi e durante
il montaggio. Un token di oltre 600 caratteri senza separatori e rifiutato con errore.
La GUI non uccide a forza il thread che esegue inferenza nativa.

## D07 - Gate Windows candidati contro release

Gli script forniti creano solo una CANDIDATE e controllano anche l'EXE frozen in una
cartella trasferita con caratteri Unicode. Questi controlli, se eseguiti, NON dimostrano
l'indipendenza dalle librerie gia presenti nel runner. Richiesti separatamente:

- Windows 11 x64 pulito, utente standard e rete disabilitata.
- Nessuna dipendenza da Python, Visual C++ Redistributable o FFmpeg di sistema.
- Qualita vocale italiana/inglese con materiale reale dell'utente.
- Monitoraggio rete anche delle librerie native.
- Comportamento reale SmartScreen/Smart App Control senza bypass.
- Controllo licenze, sorgente corrispondente dei componenti GPL e MSVC runtime.

## D08 - Dati e ripresa

Una sola istanza per cartella dati, lock del sistema operativo, SQLite DELETE/FULL,
connessione separata per operazione. Nessun WAL condiviso tra processi. I lavori
interrotti mantengono gli MP3 gia verificati. Al successivo avvio del motore, i temporanei
propri dell'app vengono rimossi e i manifest incompleti marcati `interrupted`.
Una nuova generazione usa la cache ma produce un nuovo run: non finge di riprendere
un ascolto. Evitare uso concorrente della cartella da computer diversi via cloud.

## D09 - Fedelta alla scheda di progetto

Per mantenere un CSV senza header importato esplicitamente, il formato di input viene
salvato nel progetto JSON/SQLite. Le correzioni vocali e di lingua restano associate
all'identificatore della coppia originale. Un cambiamento del testo originale crea
una nuova versione semantica della coppia e non ricicla una correzione ormai estranea.

## D10 - Nessuna approvazione automatica scientifica o giuridica

I test dimostrano proprieta del software, non apprendimento. Le schede dei modelli
forniscono indicazioni di provenienza/licenza, non una revisione completa della catena
di distribuzione. La mancanza di un gate e dichiarata, non trasformata in PASS.
