# 3d-Site

Interfaccia web per consultare il magazzino dei filamenti e stimare tempi/costi di stampa
3D partendo da modelli caricati localmente o scaricati da URL. L'applicazione è composta
da una API FastAPI che normalizza i dati provenienti da [Spoolman](https://github.com/Donkie/Spoolman)
e offre endpoint di upload/fetch dei modelli, e da una singola pagina statica di frontend che
visualizza l'inventario in tempo reale e consente l'interazione con l'utente.

## Funzionalità principali
- **Palette filamenti**: aggregazione dei dati Spoolman con calcolo del prezzo minimo €/kg per
  colore/materiale e riconoscimento dei colori trasparenti.
- **Viewer & stima**: caricamento di file STL/OBJ/3MF (anche zippati) via drag&drop, upload o
  download da URL/Thingiverse; restituisce un link diretto al file elaborato.
- **Aggiornamento periodico**: la palette viene ricaricata automaticamente ogni 60 secondi.
- **API normalizzate**: endpoint `/spools` e `/inventory` con risposta JSON coerente, pronta per
  essere usata dal frontend o da integrazioni esterne.
- **Distribuzione containerizzata**: Dockerfile e `docker-compose.yml` per un avvio rapido.

## Struttura del progetto
```
.
├── api/                 # Codice FastAPI e dipendenze
│   ├── main.py          # Endpoint REST e integrazione con Spoolman
│   ├── requirements.txt # Dipendenze Python
│   └── Dockerfile       # Immagine backend
├── web/
│   └── index.html       # Frontend statico (vanilla JS + CSS inline)
├── docker-compose.yml   # Stack di esecuzione (API + frontend statico)
├── LICENSE              # Testo licenza GPLv3
└── README.md            # Questo file
```

## Prerequisiti
- [Docker](https://www.docker.com/) e Docker Compose.
- Istanza raggiungibile di **Spoolman** (API v1) da cui leggere le bobine.
- Opzionale: Python 3.11+ se si preferisce eseguire l'API localmente senza container.

## Avvio rapido con Docker Compose
1. Clona il repository e posizionati nella cartella del progetto.
2. Aggiorna nel `docker-compose.yml` la variabile `SPOOLMAN_URL` con l'endpoint corretto della tua
   istanza di Spoolman.
3. (Facoltativo) Personalizza `HOURLY_RATE` e `CURRENCY` in base alle tue tariffe.
4. Avvia i servizi:
   ```bash
   docker compose up --build
   ```
5. Apri il browser su `http://localhost:8088/ui` per utilizzare l'interfaccia.

I file caricati o scaricati saranno salvati nella directory locale `./uploads`.

### Build manuale dell'immagine `slicer-api`
Se preferisci costruire l'immagine senza Docker Compose assicurati di passare
la **root del repository** come contesto di build, altrimenti le cartelle
`profiles/` e `web/` non verranno copiate e la build fallirà con errori tipo
```
failed to calculate checksum of ref ...: "/profiles": not found
```
Puoi:

1. Lanciare direttamente il wrapper incluso nel repository, che si occupa di
   impostare automaticamente il contesto corretto **e verificare che il binario
   `PrusaSlicer` sia disponibile**:
   ```bash
   ./scripts/build-slicer-api.sh -t slicer-api:local
   ```
   (il parametro `-t` è facoltativo e permette di impostare il tag desiderato).
   Al termine della build lo script esegue automaticamente `PrusaSlicer --version`
   all'interno dell'immagine per confermare che l'eseguibile sia presente; puoi
   disattivare il controllo aggiungendo l'opzione `--skip-verify`.
2. Oppure eseguire manualmente il build command assicurandoti di rimanere nella
   root del repository:
   ```bash
   docker build -f services/slicer-api/Dockerfile .
   ```

Se vuoi testare manualmente la presenza di PrusaSlicer dopo la build (ad esempio
quando non utilizzi lo script di supporto), puoi lanciare:
```bash
docker run --rm slicer-api:local PrusaSlicer --version
```
Sostituisci `slicer-api:local` con il tag assegnato all'immagine.

In entrambi i casi otterrai un'immagine pronta per essere avviata con
`docker run` oppure tramite `docker compose`.

## Configurazione
Le variabili di ambiente principali, configurabili via `docker-compose.yml` o direttamente sulla
macchina, sono:

| Variabile       | Default                     | Descrizione |
|-----------------|-----------------------------|-------------|
| `SPOOLMAN_URL`  | `http://192.168.10.164:7912` | URL base dell'API Spoolman (v1). |
| `HOURLY_RATE`   | `1`                         | Costo orario della stampante (usato nelle risposte JSON). |
| `CURRENCY`      | `EUR`                       | Codice valuta utilizzato nei prezzi. |

Ulteriori directory montate nel compose:
- `./web` → `/app/web` (frontend statico, modalità read-only)
- `./uploads` → `/app/uploads` (persistenza file caricati)

## Endpoint principali
| Metodo | Percorso        | Descrizione |
|--------|-----------------|-------------|
| GET    | `/health`       | Verifica stato dell'API. |
| GET    | `/spools`       | Elenco bobine individuali con prezzi €/kg e metadati. |
| GET    | `/inventory`    | Aggregazione per colore/materiale con quantità residue e miglior prezzo. |
| POST   | `/upload_model` | Upload di file `.stl`, `.obj`, `.3mf` o `.zip` (anche drag&drop). |
| POST   | `/fetch_model`  | Download di un modello da URL o pagina con link a STL/OBJ/3MF/ZIP. |
| GET    | `/files/...`    | Accesso ai file caricati/elaborati (serviti come static files). |
| GET    | `/ui`           | Frontend statico. |

Tutte le risposte JSON sono restituite con header `Cache-Control: no-store` per evitare caching.

## Utilizzo del frontend
- Apri `http://localhost:8088/ui` (o l'host configurato).
- Carica un modello tramite drag&drop, pulsante "Carica" o incolla una URL/Thingiverse.
- Seleziona un materiale dalla palette per collegare il prezzo €/kg corrispondente.
- Il riquadro "Viewer 3D" mostra il nome del file caricato e un link diretto al file ospitato
  dall'API (in attesa di una vera anteprima 3D).
- La palette si aggiorna automaticamente ogni minuto; puoi forzare un refresh ricaricando la pagina.

## Sviluppo locale senza Docker
1. Crea un ambiente virtuale Python 3.11+ e installa le dipendenze:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r api/requirements.txt
   ```
2. Imposta le variabili d'ambiente richieste (`SPOOLMAN_URL`, ecc.).
3. Avvia l'API dalla cartella `api/`:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8080
   ```
4. Servi la cartella `web/` (ad esempio con `python -m http.server`) oppure lascia che FastAPI
   risponda al percorso `/ui` direttamente.

## License
Questo progetto è distribuito sotto i termini della [GNU General Public License v3.0](LICENSE).
