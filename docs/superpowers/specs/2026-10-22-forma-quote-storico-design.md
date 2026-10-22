# Forma squadre, movimento quote, schedelle caricate — Design

Data: 2026-10-22

## Obiettivo

Le indicazioni attuali derivano solo dalle quote TheOddsAPI e ripetono il bookmaker.
Si aggiungono informazioni di contesto **solo da mostrare** (il dado non cambia):

1. **Forma squadre** da football-data.org (Serie A).
2. **Movimento quote** nel tempo, da rilevazioni salvate nel DB.
3. **Schedelle caricate**: gli Excel già caricati restano disponibili e riapribili.
4. **Pulsante "Aggiorna quote"** che forza una nuova lettura da TheOddsAPI.

Fuori scopo: modifica pesi del dado, confronto tra bookmaker, Serie B (403 sul piano free football-data),
job schedulati di lettura quote.

## Vincoli verificati

- football-data free: Serie A OK (`/competitions/SA/standings`, `/competitions/SA/matches`), Serie B 403,
  10 richieste/minuto, campo `form` della classifica = `null` → la forma si calcola dai risultati.
- Nomi football-data (`shortName`): uguali all'Excel tranne `Como 1907`, `Venezia FC`.
- Token in env `FOOTBALLDATA_KEY` (locale e Railway). Mai nel codice o nei commit.
- TheOddsAPI: ~3 crediti per partita trovata, 500/mese. Il refresh forzato consuma crediti.

## 1. Forma squadre

### Modulo `src/form_data.py`

- `FootballDataError(Exception)`: errore API con messaggio leggibile (status + `message`).
- `fetch_standings(api_key)` e `fetch_finished_matches(api_key)`: GET su football-data v4,
  header `X-Auth-Token`, timeout 10s, cache in memoria con TTL `FORM_CACHE_TTL_SECONDS = 60 * 60`.
- `find_team(name, standings)`: confronto normalizzato (lowercase, strip) con `shortName`, `name`, `tla`,
  dopo alias `FOOTBALLDATA_TEAM_ALIASES = {'como': 'como 1907', 'venezia': 'venezia fc'}`;
  match esatto su uno dei tre campi, poi substring. Ritorna l'id squadra o `None`.
- `team_form(team_id, venue, standings, matches)` → dict:
  - `name`, `position`, `points`, `played`
  - `last5`: lista di `'V'|'N'|'P'`, ordine cronologico (più recente a destra), da tutte le partite
  - `gf_avg`, `gs_avg`: medie gol fatti/subiti nelle sole partite in `venue` (`'home'` per la squadra di
    casa, `'away'` per l'ospite); `None` se 0 partite in quel venue
  - `over25_pct`, `gg_pct`: % partite stagione con gol totali ≥ 3 / entrambe a segno (interi 0-100)
- `match_form(match_name, api_key)` → `{'home': dict|None, 'away': dict|None}` da `'Casa - Ospite'`;
  `None` per una squadra non trovata.

### Integrazione

- `service.get_form_preview(match_names, api_key=None)` → `{"results": [{"name", "home", "away"}], "error"}`;
  chiave da argomento o `FOOTBALLDATA_KEY`; senza chiave → `error` "Imposta FOOTBALLDATA_KEY…".
  `FootballDataError` interrompe e valorizza `error`.
- `POST /api/form` body `{"matches": [str]}` → risultato sopra (handler sync, come `/api/odds`).
- `prepare_session`: per ogni partita aggiunge `form` (stesso formato di `match_form`, o `None` su errore/
  chiave assente) così il sorteggio salvato conserva la forma del giorno.

### UI

- `configura.html`: sotto la riga quote, una riga per squadra:
  `Napoli 9° 11pt · V N V P V · casa GF 1.8 GS 0.9 · O2.5 57% · GG 43%`; squadra non trovata →
  "forma non disponibile". Caricata al load e dopo rinomina, con riga di stato errori come le quote.
- `sorteggio.html`: stessa riga sotto Best Prob/Best Odds, da `match.form` (sessioni vecchie senza `form`:
  niente riga).
- Rendering via DOM (`textContent`), nessun HTML da dati esterni.

## 2. Movimento quote

### DB

Nuova tabella (in `init_db`, `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS odds_snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL,
    event_name  TEXT NOT NULL,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    odds_json   TEXT NOT NULL      -- lista di 7 float|null, ordine PRONOSTICI
);
CREATE INDEX IF NOT EXISTS idx_odds_snapshot_event ON odds_snapshot(event_id, fetched_at);
```

- `db.add_odds_snapshot(path, event_id, event_name, odds)`: inserisce solo se diverso dall'ultima
  rilevazione dello stesso `event_id`.
- `db.get_first_odds_snapshot(path, event_id)` → `{"odds": [...], "fetched_at": str}` o `None`.

### Logica

- `lookup_theodds_match` aggiunge `event_id` al risultato e accetta `force=False`: con `force=True`
  ignora la cache della partita (sport/eventi restano in cache) e riscrive la cache.
- `service.get_odds_preview(match_names, api_key, db_path, force=False)`: per ogni partita trovata salva lo
  snapshot e aggiunge al risultato `first_odds` e `first_at` (prima rilevazione).
- Movimento mostrato quando `|attuale − prima| ≥ ODDS_MOVE_THRESHOLD = 0.05`.

### UI

- Riga quote in configura: `1 2.83 ↓ (2.95)`; ↓ quota scesa, ↑ salita. Tooltip con data prima rilevazione.

## 3. Pulsante "Aggiorna quote"

- In configura, nella card partite: `↻ Aggiorna quote`. Chiama `/api/odds` con `"force": true`.
- Tooltip/nota: "consuma ~3 crediti per partita". Disabilitato durante il caricamento.

## 4. Schedelle caricate

Gli Excel sono già in `session.excel_bytes`.

- `db.get_recent_uploads(path, limit=10)` → ultimi upload distinti per `excel_filename` (il più recente
  per nome): `[{"session_id", "excel_filename", "created_at"}]`.
- `/nuova`: sezione "Schedelle caricate" con un pulsante per riga (`Schedella2627.xlsx · 22/10 11:40`).
- `POST /nuova/riapri/{session_id}`: crea una **nuova** sessione copiando bytes e nome del file
  (la sessione originale, magari già sorteggiata, non viene toccata) e redirige a `/configura/{nuovo}`.
  Sessione inesistente → redirect `/nuova`.
- Convive con il pulsante "Usa Schedella2627.xlsx" (file su disco locale).

## Errori

- football-data e TheOddsAPI: errori mostrati nella riga di stato della card partite, mai inghiottiti nella
  preview. Nel sorteggio la forma mancante non blocca (`form = None`).

## Test

- `tests/test_form.py`: HTTP mockato; calcolo `last5`, medie venue, `over25_pct`, `gg_pct` su risultati
  finti; alias Como/Venezia; errore 403 → `FootballDataError`; preview senza chiave.
- `tests/test_odds.py`: `force=True` bypassa cache; snapshot salvato solo se cambiato; `first_odds` nel
  risultato preview.
- `tests/test_routes.py`: `/nuova` elenca upload, `/nuova/riapri/{id}` crea nuova sessione e redirige;
  `/api/form` senza chiave risponde con `error`.
