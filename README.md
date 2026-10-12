# StoryPartyBot

Bot Python riutilizzabile, con interfaccia in spagnolo per l’anfitrione della casa e giocatori. Tutta la regia avviene nella chat privata del bot: conferma della storia, assegnazioni, anteprime, autorizzazioni, invii e recupero errori. L’Excel viene importato dal responsabile IT tramite Terminale, mai dalla chat. Nessuna storia è incorporata nel codice. Il file originale è in `examples/Plantilla_juego_Telegram_demo.xlsx`.

## Installazione su macOS

Richiede Python 3.11 o successivo; verificato con Python 3.13. La configurazione iniziale è a cura di chi installa il bot. L’anfitrione della casa non deve usare il terminale per gestire le partite.

```bash
cd /Users/andrea/Repository/StoryPartyBot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
open -e .env
```

1. Crea un bot con `@BotFather` su Telegram e copia il token **solo in `.env`**.
2. Imposta `ADMIN_TELEGRAM_ID` all'ID numerico personale dell’anfitrione della casa, non al suo username. Per ricavarlo senza servizi esterni, chi installa può configurare temporaneamente un proprio ID admin, avviare il bot e chiedere all’anfitrione della casa di premere `/start`: la risposta mostra il suo ID. Ferma il bot, configura quell'ID e riavvia prima di caricare la storia. In alternativa usa un ID già verificato.
3. Lascia `DATABASE_PATH=data/game.sqlite3` per la prova locale.
4. Proteggi la configurazione e avvia:

```bash
chmod 600 .env
python -m narrative_bot
```

Lascia il processo acceso; `Ctrl+C` lo arresta. Il Mac deve restare acceso e connesso. Al riavvio si recupera lo stato SQLite. Il token non va inserito nell'Excel, condiviso in chat o pubblicato. `.env`, database e cartella `data` sono esclusi da Git; il Docker build include solo codice e dipendenze.

Per una prima installazione senza conoscere nessun ID puoi usare temporaneamente un **numero positivo di configurazione**, senza caricare contenuti: `/start` mostra l'ID all’anfitrione della casa se non coincide con quello configurato. Sostituiscilo subito con il suo vero ID prima dell'uso. L'ID configurato è l'unica identità autorizzata: username e nome visualizzato non concedono accesso.

## Importazione Excel — responsabile IT

Ferma il bot con `Ctrl+C` prima di importare. Nella cartella del progetto, con il virtualenv attivo:

```bash
python -m narrative_bot import examples/Plantilla_juego_Telegram_demo.xlsx
python -m narrative_bot
```

Puoi usare qualsiasi percorso `.xlsx`, tra virgolette se contiene spazi. Non è necessario copiare il file nel codice. Il comando valida il file e salva una preparazione in SQLite senza inviare messaggi; non richiede token o ID admin. Usa lo stesso `.env` e `DATABASE_PATH` del bot. L’anfitrione della casa apre `/control`, vede il riepilogo e preme **Confirmar partida**. L'importazione è rifiutata mentre il bot è acceso o esiste una partita non conclusa. Una nuova importazione sostituisce solo una preparazione ancora da confermare; un file non valido lascia intatta quella precedente. Copiare o modificare il file originale dopo l'importazione non cambia la copia salvata nel database.

Su hosting esegui il comando nello stesso ambiente e volume del worker, con il worker fermo. L'accesso IT è quello del sistema operativo; nessun utente Telegram, incluso l’anfitrione della casa, può importare allegati.

## Formato Excel

Il file viene letto come dati; le istruzioni scritte nelle celle non modificano le regole del bot. I nomi dei fogli e delle colonne sono quelli dell'allegato, compresi gli accenti. L'ordine delle colonne può cambiare.

| Foglio | Colonne |
| --- | --- |
| `Guia` | `Campo`, `Contenido` |
| `Personajes` | `Código`, `Nombre`, `Descripción`, `Ficha privada` |
| `Fases` | `Fase`, `Título`, `Notas admin` |
| `Mensajes` | `Fase`, `Orden`, `Destinatarios`, `Título admin`, `Texto`, `Notas admin` |

Tutti i campi sono obbligatori salvo `Notas admin`. Codici: 1–32 lettere maiuscole ASCII, cifre, `_` o `-`; unici; `TODOS` è riservato. I destinatari sono `TODOS` da solo oppure uno o più codici separati da virgola. Gli spazi intorno alle virgole vengono ignorati. Le righe vuote vengono ignorate. Fasi e ordini devono essere interi positivi consecutivi a partire da 1; l'ordine è unico all'interno della fase. Ogni fase deve avere almeno un messaggio.

Non usare formule. Testi e schede: massimo 4000 unità UTF-16 (gli emoji possono valerne due), per conservare un messaggio Telegram per consegna. Excel massimo 5 MB, contenuto ZIP decompresso massimo 30 MB, massimo 3000 righe e 30 colonne per foglio. Gli errori indicano foglio, riga e correzione in spagnolo.

`Guia`, `Descripción`, titoli e note amministrative non sono mai usati come testo di invio ai giocatori. I giocatori ricevono solo la propria `Ficha privada` e i `Texto` destinati loro. I messaggi vengono inviati come testo semplice, senza interpretare Markdown o HTML.

## Flusso per l’anfitrione della casa

1. Apri la chat privata e invia `/start` o `/control`.
2. Il responsabile IT ha già importato l'Excel. Controlla il riepilogo e premi **Confirmar partida**. Non parte alcun messaggio. Se la storia non è pronta o contiene errori, chiedi al responsabile IT di importarla nuovamente.
3. Chiedi a ogni giocatore di inviare `/start` al bot. Apri **Jugadores**, premi **Asignar [código]**, scegli nome e ID. Prima delle schede puoi usare **Liberar** per correggere un'assegnazione.
4. Consulta **Guía privada**. Quando tutti i personaggi sono assegnati, premi **Autorizar fichas privadas** e conferma. Questo blocca le assegnazioni per tutta la partita, anche prima della fase 1, per evitare di esporre schede di più personaggi allo stesso utente.
5. Le schede sono nella fase di preparazione (fase 0). **Vista previa del próximo** le mostra solo all’anfitrione della casa; **Enviar próximo** invia una sola scheda per clic. Non esiste invio automatico delle schede.
6. Premi **Iniciar fase siguiente…** e conferma. La fase precedente si chiude; quella nuova si apre **senza inviare nulla**.
7. Usa l'anteprima e **Enviar próximo** per ogni messaggio, nell'ordine unico della fase. Un collettivo è un messaggio di storia, inviato separatamente nelle chat private dei destinatari.
8. **Finalizar partida…** chiude l'ultima fase. Il responsabile IT può poi importare un Excel per una nuova partita con associazioni e consegne indipendenti. Gli utenti registrati con `/start` restano disponibili, ma vanno riassegnati.

I contenuti confermati sono sempre immutabili, anche in preparazione: per correggere il file prima di autorizzare le schede usa **Descartar preparación…**, conferma e chiedi al responsabile IT di importare la copia corretta. Dopo l’autorizzazione delle schede puoi usare **Interrumpir y reiniciar partida** per ripartire con la stessa storia, oppure concludere le fasi e importare una storia diversa. La prima versione gestisce una partita corrente alla volta e conserva quelle concluse nel database.

## Interrompere e ricominciare da Telegram

L’anfitrione della casa apre `/control` → **Interrumpir y reiniciar partida** → **Sí, interrumpir y reiniciar**. La conferma elenca eventuali messaggi incompleti. **Cancelar** mantiene la partita corrente senza modifiche.

Il bot chiude la partita corrente, registra gli incompleti come saltati e crea una nuova partita con la stessa storia, in preparazione. Tutti i personaggi sono liberi, i giocatori restano registrati e occorre autorizzare nuovamente le schede dopo le assegnazioni. Non serve reimportare l’Excel o riavviare il programma per ogni nuova prova. Nessun messaggio viene inviato dal riavvio della partita.

Lo storico precedente resta in SQLite, comprese associazioni e consegne riuscite o incerte. I messaggi già ricevuti restano nelle chat dei giocatori. I vecchi pulsanti non possono modificare la nuova partita. La creazione avviene in un’unica transazione; un doppio clic non crea più partite.

## Controllo ed errori

`/control` mostra partita, fase, note private, elenco ordinato con titolo e destinatari, stato di ogni messaggio e destinatari mancanti con errori. I conteggi si riferiscono alla fase visualizzata. **Historial de fases** conserva il dettaglio delle fasi precedenti della partita corrente. La fase 0 conta le schede separatamente dalla storia.

- **Completato**: tutte le consegne sono accettate da Telegram o sono state esplicitamente risolte dall’anfitrione della casa. I messaggi saltati sono contati separatamente.
- **Consegne accettate**: solo risposte positive di Telegram, con `message_id` salvato. Non significa che il giocatore abbia letto.
- **Errore certo** (`Forbidden`, `BadRequest`, `RetryAfter`): la sequenza si ferma. Se il giocatore ha bloccato il bot deve sbloccarlo e usare `/start`; se Telegram richiede attesa, aspetta e premi **Reintentar pendientes**. Si riprovano solo le consegne mancanti del primo messaggio incompleto.
- **Esito incerto**: timeout, errore di rete o arresto durante l'invio. Nessun reintento automatico. **Resolver entrega incierta** consente di dare la consegna per risolta senza reinviare, oppure autorizzare un reintento potenzialmente duplicato. La prima scelta non incrementa il contatore delle accettazioni Telegram. Chiedi al giocatore se il messaggio è arrivato prima di scegliere.
- **Saltar mensaje…** richiede conferma, registra il salto e conserva gli esiti delle consegne già tentate.
- Il cambio fase mostra tutti gli incompleti e i loro destinatari prima della conferma. Confermando, gli incompleti diventano saltati; errori ed esiti incerti restano nello storico. Non si può tornare indietro o ritentare una fase chiusa.

Non è possibile garantire “exactly once” attraverso un timeout: Telegram non fornisce una chiave di idempotenza per `sendMessage`. Il bot non reinvia mai una consegna confermata. Una decisione esplicita dell’anfitrione della casa su un esito incerto può causare un duplicato; viene registrata nell'audit.

I destinatari e i loro ID sono fotografati all'apertura di ogni fase, e all'autorizzazione delle schede. I denominatori restano quindi stabili. Le associazioni sono univoche a livello SQLite. Gli update vengono elaborati in sequenza, con lock applicativo; i pulsanti sono monouso, associati a partita e revisione. Un invio cambia revisione prima di accedere alla rete, rendendo obsoleti gli altri pannelli. Se un pulsante è scaduto, riapri `/control`.

## Prova con l’anfitrione della casa e due giocatori

Usa `examples/Plantilla_juego_Telegram_demo_2_jugadores.xlsx`: contiene MARCO e MARIO, 3 fasi e 11 messaggi. L’anfitrione della casa rimane amministratore. Gli indizi sono adattati per risolvere la storia senza Clara.

Se hai già confermato la demo precedente e non hai autorizzato le schede, L’anfitrione della casa deve prima usare **Descartar preparación…** e confermare in Telegram. Se la preparazione è ancora solo un riepilogo da confermare, la nuova importazione la sostituisce. Una partita con schede già autorizzate deve essere conclusa tramite i normali controlli prima di importarne un'altra.

Ferma il bot con `Ctrl+C`, poi esegui separatamente:

```bash
python -m narrative_bot import examples/Plantilla_juego_Telegram_demo_2_jugadores.xlsx
python -m narrative_bot
```

L’anfitrione della casa apre `/control`, conferma la nuova partita e assegna i due personaggi ai due giocatori registrati con `/start`. Autorizza le schede e le invia con due clic su **Enviar próximo**. Le fasi hanno rispettivamente 3, 3 e 5 messaggi; le consegne sono 4, 4 e 8. Totale: 11 messaggi di storia e 16 consegne, più 2 schede. In fase 3 il messaggio 4 raccoglie le accuse: attendere entrambe prima del messaggio 5, la soluzione.

## Prova guidata della demo con tre giocatori

Servono **L’anfitrione della casa più tre account Telegram giocatore distinti** (quattro account in tutto). Sono invii reali solo se esegui manualmente questa procedura; i test automatici non li eseguono.

1. IT importa `examples/Plantilla_juego_Telegram_demo.xlsx` con il comando sopra e avvia il bot. L’anfitrione della casa apre `/control`, verifica **3 personaggi, 3 fasi, 14 messaggi** e conferma.
2. I tre utenti inviano `/start`. L’anfitrione della casa assegna **MARCO**, **MARIO**, **CLARA**, uno ciascuno. Un quarto utente non assegnato non riceve i collettivi.
3. L’anfitrione della casa autorizza le schede e preme **Enviar próximo** tre volte. Ogni utente deve ricevere esclusivamente la propria scheda. In fase 0: **3/3 messaggi, 3/3 consegne**.
4. L’anfitrione della casa apre fase 1: nessun giocatore deve ricevere messaggi fino al clic successivo. Apre l'anteprima del primo testo e verifica che solo l’anfitrione la veda.
5. Invia il primo messaggio collettivo: **1/4 messaggi, 3/6 consegne**. Invia le tre piste personali: **4/4 e 6/6**.
6. Apri fase 2 e invia i quattro messaggi: **4/4 e 6/6**.
7. Apri fase 3, invia in ordine i messaggi 1–5, raccogli le accuse a voce. **Non premere il prossimo invio finché non vuoi rivelare la soluzione**. Dopo il sesto: **6/6 e 12/12**.
8. Totale storia: **14 messaggi, 24 consegne**; schede separate: **3 consegne**. Premi **Finalizar partida…** e conferma.
9. Verifica un pannello vecchio: non deve avviare un altro invio. Dai giocatori prova `/control` e un documento: nessun contenuto amministrativo deve essere mostrato.
10. Per una prova facoltativa degli errori, in una nuova partita fai bloccare il bot a un giocatore prima di un collettivo. La sequenza si ferma; dopo lo sblocco, **Reintentar pendientes** non deve reinviare ai destinatari già confermati. Timeout, arresti e concorrenza sono coperti automaticamente con trasporti simulati.

## Test senza Telegram

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

I test usano SQLite temporaneo e `AsyncMock`, senza token, polling o chiamate Telegram. Le connessioni socket sono bloccate nella suite. Coprono il file originale, errori di importazione, destinatari multipli, permessi dei comandi e callback, unicità delle associazioni, ordine, snapshot e conteggi, duplicati, doppio clic concorrente, fallimenti parziali, timeout, recupero dopo riavvio, conferme e separazione delle partite.

## Hosting futuro con storage persistente

È incluso un `Dockerfile` per un worker Linux in long polling; nessun deployment è stato effettuato. Richiede un processo sempre acceso e accesso HTTPS in uscita; nessuna porta pubblica, webhook, scheduler o servizio web.

Quando vorrai ospitarlo:

- Avvia **una sola replica**, senza autoscaling o repliche sovrapposte durante gli aggiornamenti. Il file lock protegge le istanze sullo stesso filesystem; database separati non possono coordinarsi.
- Monta un volume persistente locale in `/data`, scrivibile dall'UID `10001`, e imposta `DATABASE_PATH=/data/game.sqlite3`.
- Inserisci token e ID negli environment secrets del provider; non nell'immagine.
- Evita storage effimero, filesystem di rete per SQLite WAL, e piattaforme che sospendono il worker.
- Usa riavvio su arresto e arresto ordinato. I timeout/interruzioni non producono reintenti automatici al riavvio.
- Per backup coerenti usa l'API backup di SQLite oppure arresta il processo e copia tutta la directory dati, inclusi eventuali `-wal` e `-shm`. Non copiare solo il file principale mentre il bot è attivo. Proteggi backup e database: contengono schede private, ID e stato della partita.

## Struttura

`local_import.py` prepara l’importazione IT; `importer.py` valida Excel; `store.py` mantiene stato e audit SQLite; `delivery.py` gestisce il confine affidabile con Telegram; `bot.py` contiene l'interfaccia; `__main__.py` carica la configurazione, acquisisce il lock e avvia il polling.

Riferimento della libreria: [python-telegram-bot 22.8, Application/run_polling](https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.application.html).
