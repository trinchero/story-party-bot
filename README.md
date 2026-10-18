# StoryPartyBot

Bot Python riutilizzabile, con interfaccia in spagnolo per l’anfitrione della casa e giocatori. La dashboard locale gestisce preparazione, assegnazioni, avvio e chiusura. Gli invii successivi e il recupero errori sono disponibili nella chat privata del bot. Il file Numbers viene importato dal responsabile IT tramite Terminale, mai dalla chat. Nessuna storia è incorporata nel codice. La storia di prova è in `examples/TEST_BOT_Telegram_2_personajes_historia_independiente.numbers`.

## Installazione su macOS

Richiede Python 3.11 o successivo; verificato con Python 3.13. La configurazione iniziale è a cura di chi installa il bot. L’anfitrione della casa non deve usare il terminale per gestire le partite.

```bash
cd /Users/andrea/Repository/story-party-bot
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

Lascia il processo acceso; `Ctrl+C` lo arresta. Il Mac deve restare acceso e connesso. Al riavvio si recupera lo stato SQLite. Il token non va inserito nelil file Numbers, condiviso in chat o pubblicato. `.env`, database e cartella `data` sono esclusi da Git; il Docker build include solo codice e dipendenze.

Per una prima installazione senza conoscere nessun ID puoi usare temporaneamente un **numero positivo di configurazione**, senza caricare contenuti: `/start` mostra l'ID all’anfitrione della casa se non coincide con quello configurato. Sostituiscilo subito con il suo vero ID prima dell'uso. L'ID configurato è l'unica identità autorizzata: username e nome visualizzato non concedono accesso.

## Importazione Numbers — responsabile IT

Ferma il bot con `Ctrl+C` prima di importare. Nella cartella del progetto, con il virtualenv attivo:

```bash
python -m narrative_bot import examples/TEST_BOT_Telegram_2_personajes_historia_independiente.numbers
python -m narrative_bot
```

Puoi usare qualsiasi percorso `.numbers`, tra virgolette se contiene spazi. Non è necessario copiare il file nel codice. Il comando valida il file e salva una preparazione in SQLite senza inviare messaggi; non richiede token o ID admin. Usa lo stesso `.env` e `DATABASE_PATH` del bot. L’anfitrione della casa apre `/control`, vede il riepilogo e preme **Confirmar partida**. L'importazione è rifiutata mentre il bot è acceso o esiste una partita non conclusa. Una nuova importazione sostituisce solo una preparazione ancora da confermare; un file non valido lascia intatta quella precedente. Copiare o modificare il file originale dopo l'importazione non cambia la copia salvata nel database.

Su hosting esegui il comando nello stesso ambiente e volume del worker, con il worker fermo. L'accesso IT è quello del sistema operativo; nessun utente Telegram, incluso l’anfitrione della casa, può importare allegati.

## Compilare il file in Numbers

Apri il `.numbers`, modifica e salva con Cmd+S. Non serve esportare o convertire. Usa un file Numbers singolo, non un pacchetto/cartella e senza password. Ogni foglio richiesto deve contenere una sola tabella, con le intestazioni nella prima riga. Non cambiare i nomi dei fogli né delle colonne. I fogli aggiuntivi sono ignorati dal bot.

## Formato Numbers

Il file viene letto come dati; le istruzioni scritte nelle celle non modificano le regole del bot. I nomi dei fogli e delle colonne sono quelli dell'allegato, compresi gli accenti. L'ordine delle colonne può cambiare.

| Foglio | Colonne |
| --- | --- |
| `Personajes` | `Código`, `Nombre` |
| `Fases` | `Fase`, `Título` |
| `Mensajes` | `Fase`, `Orden`, `Destinatarios`, `Texto` |

Tutti i campi del modello sono obbligatori. Codici: 1–32 lettere maiuscole ASCII, cifre, `_` o `-`; unici; `TODOS` è riservato. I destinatari sono `TODOS` da solo oppure uno o più codici separati da virgola. Gli spazi intorno alle virgole vengono ignorati. Le righe vuote vengono ignorate. Fasi e ordini devono essere interi positivi consecutivi a partire da 1; l'ordine è unico all'interno della fase. Ogni fase deve avere almeno un messaggio.

Non usare formule. Testi: massimo 4000 unità UTF-16 (gli emoji possono valerne due), per conservare un messaggio Telegram per consegna. Numbers massimo 5 MB, contenuto ZIP decompresso massimo 30 MB, massimo 3000 righe e 30 colonne per foglio. Gli errori indicano foglio, riga e correzione in spagnolo.

I giocatori ricevono soltanto il campo `Texto` dei messaggi destinati loro. Non vengono generate schede private. Il titolo della partita deriva dal nome del file; i titoli dei messaggi dalla prima riga del testo. I vecchi file sono ancora leggibili, ma i campi aggiuntivi non vengono importati. I messaggi vengono inviati come testo semplice, senza interpretare Markdown o HTML.

## Flusso per l’anfitrione della casa

1. Apri la chat privata e invia `/start` o `/control`.
2. Il responsabile IT ha già importato il file Numbers. Controlla il riepilogo e premi **Confirmar partida**. Non parte alcun messaggio. Se la storia non è pronta o contiene errori, chiedi al responsabile IT di importarla nuovamente.
3. Chiedi a ogni giocatore di inviare `/start` al bot. Apri **Jugadores**, premi **Asignar [código]**, scegli nome e ID. Prima della conferma dei personaggi puoi usare **Liberar** per correggere un'assegnazione.
4. Quando tutti i personaggi sono assegnati, premi **Confirmar personajes** e conferma. Le assegnazioni restano bloccate fino alla fine della partita. Non vengono inviate schede private.
5. Dalla dashboard usa **Iniciar partida**: l'anteprima mostra il primo messaggio della fase 1 e la conferma ne autorizza l'invio.
6. Premi **Iniciar fase siguiente…** e conferma. La fase precedente si chiude; quella nuova si apre **senza inviare nulla**.
7. Usa l'anteprima e **Enviar próximo** per ogni messaggio, nell'ordine unico della fase. Un collettivo è un messaggio di storia, inviato separatamente nelle chat private dei destinatari.
8. **Finalizar partida…** chiude l'ultima fase. Il responsabile IT può poi importare un file Numbers per una nuova partita con associazioni e consegne indipendenti. Gli utenti registrati con `/start` restano disponibili, ma vanno riassegnati.

I contenuti confermati sono sempre immutabili, anche in preparazione: per correggere il file prima di confermare i personaggi usa **Descartar preparación…**, conferma e chiedi al responsabile IT di importare la copia corretta. Dopo la conferma dei personaggi puoi usare **Interrumpir y reiniciar partida** per ripartire con la stessa storia, oppure concludere le fasi e importare una storia diversa. La prima versione gestisce una partita corrente alla volta e conserva quelle concluse nel database.

## Interrompere e ricominciare da Telegram

L’anfitrione della casa apre `/control` → **Interrumpir y reiniciar partida** → **Sí, interrumpir y reiniciar**. La conferma elenca eventuali messaggi incompleti. **Cancelar** mantiene la partita corrente senza modifiche.

Il bot chiude la partita corrente, registra gli incompleti come saltati e crea una nuova partita con la stessa storia, in preparazione. Tutti i personaggi sono liberi, i giocatori restano registrati e occorre confermare nuovamente i personaggi dopo le assegnazioni. Non serve reimportare il file Numbers o riavviare il programma per ogni nuova prova. Nessun messaggio viene inviato dal riavvio della partita.

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

I destinatari e i loro ID sono fotografati all'apertura di ogni fase. I denominatori restano quindi stabili. Le associazioni sono univoche a livello SQLite. Gli update vengono elaborati in sequenza, con lock applicativo; i pulsanti sono monouso, associati a partita e revisione. Un invio cambia revisione prima di accedere alla rete, rendendo obsoleti gli altri pannelli. Se un pulsante è scaduto, riapri `/control`.

## Prova della storia con due giocatori

Il file `examples/TEST_BOT_Telegram_2_personajes_historia_independiente.numbers` contiene VERA e BRUNO, 4 fasi e 7 messaggi. Servono due account giocatore e l’account dell’anfitrione.

1. Importa il file con il bot fermo e riavvia il bot.
2. Conferma la preparazione nella dashboard. I giocatori inviano `/start` al bot.
3. In **Asignaciones**, assegna i due ruoli e premi **Confirmar personajes**. Da questo momento sono bloccati. Nessuna scheda privata viene inviata automaticamente.
4. In **Partida**, premi **Iniciar partida**, leggi l’anteprima e conferma: viene inviato solo il primo messaggio della fase 1, collettivo.
5. Da Telegram apri le fasi successive e autorizza gli invii nell’ordine. In **Mensajes** controlla stati e consegne.
6. **Terminar partida** chiede conferma e conserva lo storico. Per rigiocare usa **Volver a jugar**; per cambiare storia chiudi la partita, ferma il bot e importa il nuovo `.numbers`.

## Dashboard web locale

Il pannello in spagnolo mostra fase corrente, sequenza dei messaggi e consegne per personaggio. Si aggiorna ogni 5 secondi. Gli invii e i cambi fase restano in Telegram. Dal web puoi usare **Cerrar partida…** per chiudere la partita e importare un altro Numbers, oppure **Reiniciar desde cero…** per ricominciare la stessa storia senza assegnazioni. Entrambe le azioni richiedono conferma ed elencano i messaggi incompleti. Lo storico e gli esiti delle consegne sono conservati. “Accettata” significa accettata da Telegram, non letta dal giocatore. Errori, esiti incerti e invii saltati restano distinti; le fasi future non hanno ancora un totale di consegne.

Non serve una password per il pannello locale. Nel primo terminale lascia avviato il bot. In un secondo terminale, dalla cartella del progetto:

```bash
source .venv/bin/activate
python -m narrative_bot dashboard
```

Apri <http://127.0.0.1:8080> sullo stesso Mac: la partita viene mostrata direttamente. Puoi cambiare porta con `--port 8081`. Per fermare il pannello premi Ctrl+C nel suo terminale; il bot continua a funzionare.

Il pannello usa lo stesso `DATABASE_PATH` del bot. Riavvia il bot dopo questo aggiornamento per attivare il coordinamento degli invii con i comandi web. Mostra titoli e destinatari, senza esporre testi delle schede, guida o note private. Prima della conferma della partita mostra una schermata di attesa.

Questa versione è accessibile solo dal computer che la esegue. L'accesso da altri dispositivi o via Internet richiederà una configurazione dedicata con HTTPS e autenticazione; non è stato effettuato alcun deployment.

## Test senza Telegram

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

I test usano SQLite temporaneo e `AsyncMock`, senza token, polling o chiamate Telegram. Le connessioni socket sono bloccate nella suite, salvo il test HTTP della dashboard che ammette soltanto il proprio server locale. Coprono il file originale, errori di importazione, destinatari multipli, permessi dei comandi e callback, unicità delle associazioni, ordine, snapshot e conteggi, duplicati, doppio clic concorrente, fallimenti parziali, timeout, recupero dopo riavvio, conferme e separazione delle partite.

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

`local_import.py` prepara l’importazione IT; `importer.py` valida Numbers; `store.py` mantiene stato e audit SQLite; `delivery.py` gestisce il confine affidabile con Telegram; `bot.py` contiene l'interfaccia; `__main__.py` carica la configurazione, acquisisce il lock e avvia il polling.

Riferimento della libreria: [python-telegram-bot 22.8, Application/run_polling](https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.application.html).

Le persone possono uscire dalla lista con `/leave`, oppure l’anfitrione può usare **Quitar de la lista** nella dashboard. Con un personaggio assegnato in una partita non conclusa, l’uscita è bloccata: occorre liberare l’assegnazione o chiudere la partita. Lo storico resta disponibile; `/start` rende nuovamente disponibile la persona. Eliminare la chat Telegram non equivale a uscire dalla lista.

Quando è disponibile un file Numbers importato e non ci sono partite aperte, la dashboard mostra **Iniciar partida…** con il riepilogo. La conferma crea la preparazione senza inviare messaggi o aprire la fase 1. **Cerrar partida…** chiede **¿Seguro que quieres terminar esta partida?**, con **Sí, terminar** e **No, volver**.

Il formato nativo è letto direttamente con [numbers-parser](https://masaccio.github.io/numbers-parser/quick-start), anche senza l’app Numbers sul server. Il lettore storico XLSX rimane solo per i test di regressione; il comando di importazione accetta esclusivamente `.numbers`.

### Conferme volontarie di lettura

I nuovi messaggi inviati ai giocatori includono **✅ He leído**. Solo il destinatario
può confermare: il clic salva la data in SQLite e tenta una notifica privata
all'ID admin configurato, indicando personaggio, partita, fase e titolo del messaggio.
I clic ripetuti non generano altre notifiche, anche dopo un riavvio. La conferma
compare nei dettagli delle consegne su Telegram e nella dashboard, senza bloccare
l'avanzamento. Non è una conferma automatica di Telegram: l'assenza del clic non
significa che il messaggio non sia stato letto.

La notifica viene tentata una sola volta: timeout o interruzioni possono impedirne
l'arrivo, ma la lettura registrata resta consultabile. Non viene ritentata
automaticamente per evitare duplicati. I messaggi già inviati prima di questo
aggiornamento non ricevono retroattivamente il pulsante. Riavviare il bot prima
di usare la dashboard aggiornata, per creare la tabella delle conferme.
