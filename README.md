# Preventivi Carpenteria

MVP Django per la preventivazione e la verifica di fattibilità di componenti di carpenteria metallica. L'applicazione è server-rendered, in italiano, utilizzabile da browser sul PC Windows locale o dai computer della rete aziendale. Durante l'uso non richiede Internet: CSS, JavaScript e HTMX sono inclusi nel progetto.

## Requisiti

- Windows 10/11 o Windows Server;
- Python 3.13 a 64 bit, con il comando `py` disponibile;
- browser moderno;
- per uso LAN, autorizzazione aziendale alla porta scelta (predefinita `8000`).

SQLite è il database predefinito. Docker e PostgreSQL sono opzionali.

## Installazione Windows

Aprire PowerShell nella cartella del progetto ed eseguire:

```powershell
.\scripts\setup_windows.bat
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Lo script crea `.venv`, installa le dipendenze, applica le migrazioni, inizializza fasi/risorse/gruppi e raccoglie i file statici. È idempotente e può essere rieseguito dopo un aggiornamento.

Per configurazioni permanenti impostare le variabili d'ambiente illustrate in [.env.example](.env.example). Il file è un modello: Django legge le variabili del processo/sistema, non carica automaticamente file `.env`.

## Avvio locale

```powershell
.\scripts\start_local.bat
```

Aprire `http://127.0.0.1:8000`. Il server accetta connessioni solo dal PC locale.

## Avvio sulla rete locale

Impostare almeno una chiave segreta e avviare Waitress:

```powershell
$env:DJANGO_SECRET_KEY = "una-chiave-lunga-casuale-e-riservata"
$env:DJANGO_ALLOWED_HOSTS = "192.168.1.20,nome-pc-server"
.\scripts\start_lan.bat
```

Per trovare l'IPv4 del PC server:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' }
```

Dagli altri PC aprire `http://IP-DEL-PC-SERVER:8000`. La porta 8000 deve essere autorizzata nel firewall Windows/aziendale da un amministratore. Gli script non modificano il firewall. Non esporre l'app direttamente su Internet: usarla solo in LAN o tramite VPN. In presenza di HTTPS impostare `DJANGO_SECURE_COOKIES=True` e `DJANGO_CSRF_TRUSTED_ORIGINS=https://nome-server`.

Gli script tentano prima la porta `8000`. Se Windows la riserva o un altro processo la occupa, passano automaticamente alla `8765` e mostrano nel terminale l'indirizzo effettivo. La porta può essere scelta esplicitamente impostando `SERVER_PORT`; in quel caso lo script non usa fallback e segnala chiaramente se non è disponibile.

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

Il gruppo Commerciale usa solo l'interfaccia principale: crea, modifica, cerca, duplica, archivia e genera PDF. Il gruppo Amministratore dispone dei permessi applicativi e deve avere anche il flag Django `is_staff` (“Accesso staff”) per entrare nell'Admin.

Il comando seguente può essere rilanciato senza duplicare dati:

```powershell
.\.venv\Scripts\python.exe manage.py seed_initial_data
```

## Uso essenziale

La dashboard propone **Nuovo preventivo** e **Cerca preventivo**. La compilazione segue quattro passaggi:

1. dati generali;
2. articoli e relativi materiali/pesi;
3. undici fasi di lavorazione, attivabili singolarmente;
4. riepilogo, fattibilità, prezzo offerto, PDF e completamento.

I dati non valorizzati che non impediscono il lavoro (costo materiale mancante, costo orario zero, risposta “Da verificare”) sono segnalati come avvisi. Gli errori bloccanti impediscono solo il completamento, non il salvataggio in bozza.

## Formule economiche

Tutti i calcoli usano `Decimal`. I valori sono arrotondati a due decimali solo in presentazione.

```text
costo lavorazione = minuti / 60 × costo orario per persona × operatori
costo per pezzo = costo lavorazione × quantità
costo attrezzaggio = minuti attrezzaggio / 60 × costo orario × operatori
costo operazione = lavorazione totale + attrezzaggio
costo materiale = peso per pezzo × costo/kg acquisito × quantità
margine % = (prezzo commerciale - costo industriale) / prezzo commerciale × 100
```

L'attrezzaggio è sempre per lotto. Ogni uso di risorsa salva nome, costo orario e operatori come snapshot; ogni materiale salva il costo/kg corrente. Le variazioni successive del catalogo non cambiano lo storico.

## PDF cliente

Dal riepilogo usare **Genera PDF cliente**. Il PDF A4 è generato in memoria con ReportLab e scaricato come `Preventivo_PREV-AAAA-NNNN.pdf`. Non contiene costi industriali, costi orari, operatori o margini. Se il prezzo offerto manca, riporta “Importo da definire”. Intestazione, logo, condizioni e contatti si configurano con le variabili `COMPANY_*` in `.env.example`.

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

## Test e controlli

```powershell
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

## Struttura

- `apps/catalog`: clienti, materiali, fasi, risorse e seed;
- `apps/quotes`: modelli economici generici, form, view, validazione, duplicazione;
- `apps/quotes/phases`: un modulo di configurazione/validazione per ciascuna delle 11 fasi;
- `apps/reports`: PDF cliente separato dalle view operative;
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
