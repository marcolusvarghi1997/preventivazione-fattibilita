# Preventivi Carpenteria

MVP Django per la preventivazione e la verifica di fattibilità di componenti di carpenteria metallica. L'applicazione è server-rendered, in italiano, utilizzabile da browser sul PC Windows locale o dai computer della rete aziendale. Durante l'uso non richiede Internet: CSS, JavaScript e HTMX sono inclusi nel progetto.

## Requisiti

- Windows 10/11 o Windows Server;
- Python 3.13 a 64 bit, con il comando `py` disponibile;
- browser moderno;
- per uso LAN, autorizzazione aziendale alla porta scelta (predefinita `8000`).

SQLite è il database predefinito e resta la scelta consigliata per l'installazione portatile: centinaia di righe e pochi utenti LAN sono gestiti senza introdurre un servizio database separato. Le liste sono indicizzate e paginate. Docker e PostgreSQL restano opzionali per installazioni più grandi.

## Installazione Windows

Aprire PowerShell nella cartella del progetto ed eseguire:

```powershell
.\scripts\setup_windows.bat
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Lo script crea `.venv`, installa le dipendenze, applica le migrazioni, inizializza fasi/risorse/gruppi e raccoglie i file statici. È idempotente e può essere rieseguito dopo un aggiornamento.

Per configurazioni permanenti impostare le variabili d'ambiente illustrate in [.env.example](.env.example). Il file è un modello: Django legge le variabili del processo/sistema, non carica automaticamente file `.env`.

## Avvio dell'applicazione

```powershell
.\scripts\start_local.bat
```

Aprire `http://127.0.0.1:8000`. Il server è in ascolto anche sull'interfaccia di rete, ma il middleware applicativo blocca ogni dispositivo remoto finché il superadmin non abilita **Accesso dalla rete LAN**.

## Accesso dalla rete locale

1. Avviare normalmente l'applicazione oppure eseguire `scripts\start_lan.bat`.
2. Accedere come superuser e aprire **Gestione LAN** dalla dashboard o dal menu superiore.
3. Attivare o disattivare l'accesso dagli altri dispositivi e salvare.

La pagina è disponibile soltanto al superadmin, mostra la modalità di avvio, la porta e gli indirizzi IPv4 rilevati. La modifica è immediata e non richiede riavvio né comandi. La porta deve essere autorizzata nel firewall Windows/aziendale da un amministratore. Non esporre l'app direttamente su Internet: usarla solo in LAN o tramite VPN.

`start_lan.bat` prepara automaticamente database e file statici e, al primo avvio, genera una chiave privata in `dati\django_secret_key.txt`. Il file viene riutilizzato agli avvii successivi e non va condiviso. Non è più necessario impostare manualmente `DJANGO_SECRET_KEY`; una variabile di sistema già presente continua comunque ad avere precedenza.

```powershell
$env:DJANGO_ALLOWED_HOSTS = "192.168.1.20,nome-pc-server"
.\scripts\start_lan.bat
```

Per trovare l'IPv4 del PC server:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' }
```

In presenza di HTTPS impostare `DJANGO_SECURE_COOKIES=True` e `DJANGO_CSRF_TRUSTED_ORIGINS=https://nome-server`.

Gli script tentano prima la porta `8000`. Se Windows la riserva o un altro processo la occupa, passano automaticamente alla `8765` e mostrano nel terminale l'indirizzo effettivo. La porta può essere scelta esplicitamente impostando `SERVER_PORT`; in quel caso lo script non usa fallback e segnala chiaramente se non è disponibile.

Per controllare lo script senza lasciare il server in esecuzione: `scripts\start_lan.bat --check`.

Esempio di scelta manuale in PowerShell:

```powershell
$env:SERVER_PORT = "8765"
.\scripts\start_local.bat
```

## Primo utilizzo e utenti

1. Accedere con il superuser a `/admin/`.
2. Aprire **Risorse produttive** e valorizzare i costi orari reali. Le righe a zero mostrano “Da configurare”.
3. Creare i materiali con il costo corrente al kg, se noto.
4. Creare i clienti.
5. Creare un utente commerciale e assegnarlo al gruppo **Commerciale**.

Solo un vero superuser può entrare nell'Admin, anche se un altro account ha `is_staff` o permessi amministrativi. Il gruppo Commerciale usa soltanto l'interfaccia principale: crea, modifica, cerca, duplica, archivia e genera PDF, ma vede esclusivamente i preventivi di cui è autore. Cataloghi aziendali, clienti e risorse restano condivisi. La cancellazione definitiva di un preventivo è disponibile soltanto al superuser.

Il comando seguente può essere rilanciato senza duplicare dati:

```powershell
.\.venv\Scripts\python.exe manage.py seed_initial_data
```

## Uso essenziale

La dashboard propone **Nuovo preventivo** e **Cerca preventivo**. La compilazione segue quattro passaggi:

1. dati generali, cliente e referente;
2. articoli, materiali/pesi, costi esterni e documentali opzionali;
3. undici fasi di lavorazione, attivabili singolarmente;
4. riepilogo, fattibilità, prezzo offerto, PDF e completamento.

Il cliente si cerca scrivendo nel campo con suggerimenti. Può essere registrato in una finestra rapida senza lasciare il preventivo. Ogni cliente può avere più referenti, anche omonimi con email diverse; scegliendone uno, nome ed email vengono compilati e restano modificabili nello snapshot del preventivo.

I dati non valorizzati che non impediscono il lavoro sono segnalati come avvisi. Un costo orario pari a zero su una lavorazione attiva blocca invece il completamento, perché produrrebbe un costo industriale incompleto; resta possibile salvare il preventivo in bozza. Le fasi si attivano con un checkbox e vengono salvate automaticamente.

## Formule economiche

Tutti i calcoli usano `Decimal`. I valori sono arrotondati a due decimali solo in presentazione.

```text
costo lavorazione = minuti / 60 × costo orario per persona × operatori
costo per pezzo = costo lavorazione × quantità
costo attrezzaggio = minuti attrezzaggio / 60 × costo orario × operatori
costo operazione = lavorazione totale + attrezzaggio
costo materiale = peso per pezzo × costo/kg acquisito × quantità
costi accessori articolo = acquisti esterni + lavorazioni esterne + certificati/burocrazia selezionati
guadagno % = (prezzo commerciale - costo industriale) / costo industriale × 100
```

L'attrezzaggio è sempre per lotto. Ogni uso di risorsa salva nome, costo orario e operatori come snapshot; ogni materiale propone il costo/kg corrente, ma può essere modificato per il solo preventivo. Le variazioni successive del catalogo non cambiano lo storico.

## PDF cliente

Dal riepilogo usare **Genera PDF cliente**. Il PDF A4 è generato in memoria con ReportLab e scaricato come `Preventivo_PR-AAAA-NNNNN.pdf`. Non contiene costi industriali, costi orari, operatori o guadagni. Se il prezzo offerto manca, riporta “Importo da definire”. Intestazione, logo, favicon, colori, condizioni e contatti si configurano da **Superadmin → Configurazione azienda e rete**; le variabili `COMPANY_*` restano fallback di deployment.

I preventivi usano il progressivo `PR-<anno>-<cinque cifre>`. Lo stato visibile è giallo per bozza/non completato, verde per completato/accettato e rosso per rifiutato. L'esito cliente si aggiorna dal riepilogo.

## Backup e ripristino SQLite

Arrestare preferibilmente il server e avviare:

```powershell
.\scripts\backup_database.bat
```

Il file viene copiato in `backups\db_YYYYMMDD_HHMMSS.sqlite3`; uno stesso nome non viene mai sovrascritto.

Per ripristinare: arrestare il server, fare un ulteriore backup del database corrente, quindi copiare il backup scelto come `db.sqlite3` nella root. Esempio:

```powershell
Copy-Item .\backups\db_20260716_120000.sqlite3 .\db.sqlite3
.\.venv\Scripts\python.exe manage.py migrate
```

Conservare copie anche su un supporto protetto esterno al PC server.

## PostgreSQL futuro

Impostare:

```powershell
$env:DB_ENGINE = "postgresql"
$env:DB_NAME = "preventivi"
$env:DB_USER = "preventivi"
$env:DB_PASSWORD = "password-riservata"
$env:DB_HOST = "server-postgresql"
$env:DB_PORT = "5432"
.\.venv\Scripts\python.exe manage.py migrate
```

Prima del passaggio occorre migrare i dati SQLite con una procedura concordata e collaudata; la sola modifica delle variabili crea uno schema PostgreSQL vuoto.

## Docker opzionale

Con Docker Desktop installato, configurare almeno `DJANGO_SECRET_KEY`, `DB_PASSWORD` e `DJANGO_ALLOWED_HOSTS`, quindi:

```powershell
docker compose up --build
docker compose exec web python manage.py createsuperuser
```

Il compose avvia applicazione e PostgreSQL con volume persistente. Docker non è richiesto per l'installazione Windows standard.

## Distribuzione portatile come eseguibile

[`portable_launcher.py`](portable_launcher.py) è il punto di ingresso grafico predisposto per la distribuzione: avvia Waitress, applica migrazioni e dati iniziali, apre il browser e permette di arrestare il servizio senza terminale. Database, upload e chiave privata vengono conservati nella cartella `dati` accanto all'eseguibile, quindi l'installazione rimane trasportabile.

Per produrre l'eseguibile su una macchina di build Windows:

```powershell
py -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.build-venv\Scripts\python.exe -m nuitka portable_launcher.py
```

Le direttive Nuitka necessarie (one-file, interfaccia Tk, template, statici e package Django) sono incluse nel sorgente del launcher. Il file risultante può essere rinominato `Preventivazione.exe`; all'utente finale basta un doppio clic e non serve Python installato.

Nuitka compila i moduli applicativi in codice nativo e non distribuisce semplicemente i `.py`, rendendo l'analisi molto più difficile rispetto a un pacchetto Python tradizionale. Nessun eseguibile può essere tecnicamente garantito come impossibile da analizzare: per protezione ulteriore vanno aggiunte firma digitale, controllo degli accessi alla cartella dati e procedure aziendali di distribuzione.

## Test e controlli

```powershell
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

I test end-to-end dei flussi critici usano Playwright con un database SQLite temporaneo, senza modificare `db.sqlite3`:

```powershell
npm install
npm run test:playwright
```

È richiesto Microsoft Edge oppure Google Chrome. La variabile opzionale `PYTHON_EXE` permette di indicare un interprete diverso da `.\.venv\Scripts\python.exe`; `PLAYWRIGHT_BROWSER_PATH` permette di indicare esplicitamente il browser.

## Struttura

- `apps/catalog`: clienti, materiali, fasi, risorse e seed;
- `apps/quotes`: modelli economici generici, form, view, validazione, duplicazione;
- `apps/quotes/phases`: un modulo di configurazione/validazione per ciascuna delle 11 fasi;
- `apps/reports`: PDF cliente separato dalle view operative;
- `portable_launcher.py`: interfaccia desktop e ingresso per la compilazione Nuitka;
- `templates` e `static`: interfaccia server-rendered e risorse locali;
- `scripts`: setup, avvio locale/LAN e backup;
- `tests`: calcoli, snapshot, validazioni, permessi, duplicazione, PDF, numerazione e seed.

## Estensioni future

Per una nuova fase: aggiungere un piccolo modulo in `apps/quotes/phases`, registrarlo in `registry.py`, inserirlo nel seed e aggiungere test. Non creare una nuova tabella se i dati rientrano in operazioni temporali, costi diretti o trattamenti.

Per il calcolo automatico dei tempi di piegatura (o altre fasi): implementare un servizio puro che restituisca minuti, richiamarlo dal modulo della fase e mantenere sempre la possibilità di modifica manuale. Le formule economiche restano in `services/calculations.py`.

## Decisioni ancora da definire

- costi orari reali;
- prezzi materiali reali;
- regole di margine o ricarico;
- IVA;
- condizioni commerciali;
- validità del preventivo;
- logo e dati aziendali definitivi;
- eventuali allegati tecnici;
- eventuale importazione dal vecchio Excel.
