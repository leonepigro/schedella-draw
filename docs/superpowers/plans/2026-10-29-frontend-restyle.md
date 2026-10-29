# Frontend restyle + popup di avanzamento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Popup di avanzamento su "Avanti"/"Avvia Sorteggio" con blocco doppio clic, Excel letto una volta sola, restyle di tutte le pagine in direzione A "Oro scuro, rifinito".

**Architecture:** Il parsing Excel si divide in lettura grezza (cache in memoria per hash dei byte, in `app/service.py`) e normalizzazione (`schedule_from_raw` in `src/schedella.py`). Le POST di Nuova rispondono JSON `{"redirect": url}` solo se la richiesta manda `Accept: application/json`, così il popup sa quando l'upload è finito; senza quell'header restano i 303 attuali. Popup = partial Jinja + `static/progress.js` condiviso. Stili custom spostati in `<style type="text/tailwindcss">` così `@apply` funziona.

**Tech Stack:** FastAPI, Jinja2, Tailwind Play CDN, htmx 2.0.4, JS vanilla, pandas/openpyxl, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-frontend-restyle-design.md` (mockup di riferimento: `docs/superpowers/specs/2026-10-29-frontend-restyle-mockup.html`, opzione A)

## Global Constraints

- Nessuna modifica allo schema DB.
- Nessun framework né build step nuovo; CDN restano: `cdn.tailwindcss.com`, `unpkg.com/htmx.org@2.0.4`, `cdnjs .../three.js/r134`.
- Palette: bg `#12100a`, surface `#1a160d`, border `#2d2410`, accent `#f59e0b`, gold `#fde68a`. Pagina attiva nel menu: sfondo `#2d2410`, testo `#fde68a`.
- Senza `Accept: application/json` tutte le route mantengono status e redirect attuali (303).
- Rendering dati in JS solo con `textContent`. UI in italiano.
- Flusso sorteggio, dado 3D (`static/dice.js`), calcoli quote/forma: invariati.
- Suite: `python -m pytest -q` verde a fine di ogni task (oggi 62).

## Review Focus

1. Pulsante Indietro del browser verso Nuova/Configura dopo un invio: la pagina torna dalla bfcache con popup aperto e pulsante disabilitato → deve tornare utilizzabile (`pageshow` con `event.persisted`). Verifica manuale, Task 4.
2. Il DataFrame in cache viene mutato da `schedule_from_raw` (aggiunge colonne `match`/`date`/`cos`) → la seconda lettura non deve vedere colonne o righe della prima. Test in Task 1.
3. Errore di rete o risposta non-OK durante l'upload → il popup mostra l'errore e riabilita i pulsanti, non resta appeso. Verifica manuale, Task 3.
4. "Riapri" su sessione inesistente in modalità JSON → redirect a `/nuova` dentro il JSON, non 404 né HTML. Test in Task 2.
5. "Avvia Sorteggio" che torna 400 (es. "Nessuna partita selezionata.") → la pagina di errore si mostra con il messaggio leggibile nel nuovo stile, nessun popup residuo. Verifica manuale, Task 4.

---

### Task 1: Excel letto una volta sola

**Files:**
- Modify: `src/schedella.py:228-286` (`read_schedule`)
- Modify: `app/service.py:75-112` (`get_excel_preview`), `app/service.py:292-305` (`prepare_session`)
- Test: `tests/test_service.py`

**Interfaces:**
- Produces: `schedule_from_raw(df: pd.DataFrame, cos_column=None) -> pd.DataFrame` in `src/schedella.py` (tutta la logica attuale di `read_schedule` dopo `pd.read_excel`, lavora su una copia); `read_schedule(path, cos_column=None)` = `pd.read_excel(path, engine='openpyxl', header=1)` + `schedule_from_raw` (la CLI resta com'è).
- Produces: `read_raw_excel(excel_bytes: bytes) -> pd.DataFrame` in `app/service.py`: `pd.read_excel(io.BytesIO(...), engine='openpyxl', header=1)`, colonne già `str().strip()`, cache dict per `hashlib.sha1(bytes).hexdigest()` con al massimo `RAW_EXCEL_CACHE_MAX = 8` voci (scarta la più vecchia), restituisce sempre `df.copy()`. Su file illeggibile solleva come oggi `pd.read_excel`.

- [ ] **Step 1: Misura.** Con il file reale (`~/Downloads/Schedella2627.xlsx` se presente) cronometra `get_excel_preview` e annota nel ledger il tempo delle due letture. Serve a confermare che il costo è nella lettura del workbook.

- [ ] **Step 2: Test che falliscono** in `tests/test_service.py` (riusa un helper Excel come `_excel_bytes` di `tests/test_routes.py`):

```python
def test_excel_read_once_for_preview_and_session(monkeypatch):
    import app.service as svc
    svc._RAW_EXCEL_CACHE.clear()
    calls = []
    real = svc.pd.read_excel
    monkeypatch.setattr(svc.pd, "read_excel", lambda *a, **k: calls.append(1) or real(*a, **k))
    data = _excel_bytes()
    svc.get_excel_preview(data, "t.xlsx")
    svc.prepare_session(data, "t.xlsx", {"players": 1, "per_player": 3})
    assert len(calls) == 1

def test_raw_excel_cache_not_mutated():
    import app.service as svc
    data = _excel_bytes()
    first = svc.read_raw_excel(data)
    first["match"] = "x"
    assert "match" not in svc.read_raw_excel(data).columns

def test_excel_preview_unchanged_shape():
    p = get_excel_preview(_excel_bytes(), "t.xlsx")
    assert "Partita" in p["dropdown_columns"]
    assert [m["name"] for m in p["matches"]][:2] == ["Milan - Inter", "Juve - Napoli"]
```

Adatta i nomi attesi in `test_excel_preview_unchanged_shape` all'output attuale *prima* del refactor (esegui il test sul codice attuale: deve passare già ora — è il test di non-regressione; gli altri due devono fallire).

- [ ] **Step 3: Run** `python -m pytest tests/test_service.py -q` — Expected: i due nuovi test di lettura/cache FAIL (`read_excel` chiamato 2+ volte; `read_raw_excel` non definito).

- [ ] **Step 4: Implementa** `schedule_from_raw`, `read_raw_excel`, e usa `read_raw_excel` in `get_excel_preview` (anteprima = prime `max_rows` righe del df grezzo, `dropna(how='all')`; partite = `schedule_from_raw(raw)`) e in `prepare_session` (sparisce il file temporaneo). `get_excel_preview` mantiene il `try/except` che restituisce liste vuote su file illeggibile.

- [ ] **Step 5: Run** `python -m pytest -q` — Expected: tutto verde. Ripeti la misura dello Step 1 e annota il nuovo tempo.

- [ ] **Step 6: Commit** `perf: read uploaded Excel once and cache raw sheet`

### Task 2: Risposta JSON per le POST di Nuova

**Files:**
- Modify: `app/main.py:58-83` (`nuova_upload`, `nuova_riapri`, `nuova_default`)
- Test: `tests/test_routes.py`

**Interfaces:**
- Produces: helper `_redirect(request: Request, url: str)` in `app/main.py`: se `"application/json"` è nell'header `accept` → `JSONResponse({"redirect": url})` (200), altrimenti `RedirectResponse(url, status_code=303)`. Le tre route lo usano per **tutti** i loro redirect (compresi quelli verso `/nuova`). `nuova_riapri` e `nuova_default` ricevono `request: Request`.

- [ ] **Step 1: Test che falliscono:**

```python
JSON = {"accept": "application/json"}

def test_nuova_upload_json_returns_redirect(client):
    r = client.post("/nuova", files={"excel_file": ("t.xlsx", _excel_bytes(), MIME)}, headers=JSON)
    assert r.status_code == 200 and r.json()["redirect"].startswith("/configura/")

def test_riapri_missing_json_redirects_to_nuova(client):
    r = client.post("/nuova/riapri/9999", headers=JSON)
    assert r.json() == {"redirect": "/nuova"}

def test_nuova_default_json(client, tmp_path, monkeypatch):
    # stessa preparazione di test_nuova_default_excel_button_and_upload
    ...
    assert client.post("/nuova/default", headers=JSON).json()["redirect"].startswith("/configura/")
```

(`MIME` = costante del mime xlsx già usato nel file; se non esiste, definiscila in cima.)

- [ ] **Step 2: Run** `python -m pytest tests/test_routes.py -q` — Expected: i 3 nuovi FAIL (303 / HTML), i vecchi PASS.
- [ ] **Step 3: Implementa** `_redirect` e usalo nelle tre route.
- [ ] **Step 4: Run** `python -m pytest -q` — Expected: tutto verde (i test senza header continuano a vedere 303).
- [ ] **Step 5: Commit** `feat: JSON redirect for upload routes when requested`

### Task 3: Base stilistica, menu e popup di avanzamento su Nuova

**Files:**
- Modify: `templates/base.html`
- Create: `templates/fragments/progress_modal.html`, `static/progress.js`
- Modify: `templates/nuova.html`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: JSON `{"redirect": url}` da Task 2.
- Produces (usati da Task 4–6):
  - classi in `base.html` dentro `<style type="text/tailwindcss">`: `.card`, `.btn-gold`, `.btn-ghost`, `.nav-link`, `.nav-link.active` (pillola), `.badge-won/.badge-lost/.badge-void/.badge-open` (pillole arrotondate), `.badge-pron`, `.input-gold`, `.toggle-*`, più nuove `.page-title`, `.kpi`, `.kpi-label`, `.kpi-value`, `.table-a` (header `#15120b`, celle `px-3 py-2.5`, separatori `#241d0e`, numeri `tabular-nums`), `.muted` (testo secondario leggibile, es. `#a8a29e`).
  - `progress_modal.html`: `{% include "fragments/progress_modal.html" %}` una volta in `base.html`; markup con `id="progress-modal"` (nascosto), titolo `#progress-title`, lista `#progress-steps`, barra/spinner, timer `#progress-elapsed`, area errore `#progress-error`.
  - `static/progress.js` (caricato da `base.html`), globale `Progress`:
    - `Progress.open(title: string, steps: string[], {indeterminate: bool})` — mostra il modale; con `indeterminate` le fasi sono un elenco senza spunte, spinner e timer "mm:ss" che parte da 0.
    - `Progress.done(i: number)` — segna completato il passo `i` e mette "in corso" il successivo.
    - `Progress.fail(message: string)` — mostra errore, bottone "Chiudi", chiama i callback di riabilitazione.
    - `Progress.close()`.
    - `Progress.uploadForm(form: HTMLFormElement)` — `preventDefault`, disabilita tutti i `button[type=submit]` della pagina, `Progress.open("Preparo la schedella…", ["Carico il file", "Leggo le partite dall'Excel", "Apro la configurazione"])`, `fetch(form.action, {method:"POST", body:new FormData(form), headers:{accept:"application/json"}})`; su OK `done(0)` poi `location.href = json.redirect` (il passo 1 resta "in corso" mentre carica Configura); su errore `fail(...)`.
    - listener `pageshow` con `event.persisted` → `close()` e riabilita i pulsanti.

- [ ] **Step 1: Test che falliscono:**

```python
def test_base_uses_tailwind_style_block(client):
    page = client.get("/").text
    assert 'type="text/tailwindcss"' in page
    assert 'id="progress-modal"' in page and "/static/progress.js" in page

def test_nuova_forms_use_progress(client):
    page = client.get("/nuova").text
    assert page.count("Progress.uploadForm(this)") >= 1
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implementa** base (stili nel blocco tailwindcss, menu desktop in stile A: logo, voci con `.nav-link` distanziate, "+ Nuova" come `.btn-gold` spinto a destra con `ml-auto` al posto della voce "Nuova"; nav mobile invariata), modale, `progress.js`, e su `nuova.html` aggiungi `onsubmit="Progress.uploadForm(this)"` ai form upload, default e a ogni form "Riapri". Ristila `nuova.html` in stile A (card, lista Schedelle caricate con `.muted`).
- [ ] **Step 4: Run** `python -m pytest -q` — Expected: verde.
- [ ] **Step 5: Verifica in browser** (avvia `python -m uvicorn app.main:app --port 8765`, apri con Playwright MCP): menu distanziato con pillola su pagina attiva; carica un Excel → popup con "Carico il file" ✓ e "Leggo le partite" in corso fino all'apertura di Configura; doppio clic rapido crea **una** sola voce in "Schedelle caricate"; con server spento (o URL sbagliato) il popup mostra errore e i pulsanti tornano attivi. Screenshot nel ledger.
- [ ] **Step 6: Commit** `feat: dark-gold base styles, nav and upload progress popup`

### Task 4: Popup su "Avvia Sorteggio" e restyle Configura

**Files:**
- Modify: `templates/configura.html`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `Progress.open(..., {indeterminate: true})`, classi di Task 3.

- [ ] **Step 1: Test che fallisce:**

```python
def test_configura_submit_uses_progress(client):
    r = client.post("/nuova", files={"excel_file": ("t.xlsx", _excel_bytes(), MIME)}, follow_redirects=False)
    page = client.get(r.headers["location"]).text
    assert "Progress.open(" in page and "indeterminate" in page
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implementa:** l'`onsubmit` del form di Configura esegue la logica esistente che popola `match_selection` (non romperla), poi disabilita "Avvia Sorteggio" e chiama `Progress.open("Sorteggio in corso…", ["Leggo l'Excel", "Scarico le quote", "Recupero la forma delle squadre", "Sorteggio e salvo"], {indeterminate: true})`; il form si invia normalmente (niente fetch: la risposta è la pagina Sorteggio o la 400 di Configura). Ristila la pagina in stile A: sezioni in `.card` con titoli coerenti, anteprima Excel con `.table-a`, lista partite/quote/forma più ariosa, messaggio d'errore 400 in un riquadro rosso evidente in cima.
- [ ] **Step 4: Run** `python -m pytest -q` — Expected: verde.
- [ ] **Step 5: Verifica in browser:** avvia un sorteggio → popup con fasi, spinner, timer che avanza; deseleziona tutte le partite e avvia → pagina con errore leggibile, nessun popup; da Sorteggio premi Indietro → Configura utilizzabile (pulsante attivo, niente popup). Quote, frecce movimento, forma e "Aggiorna quote" funzionano come prima.
- [ ] **Step 6: Commit** `feat: progress popup on draw start and configura restyle`

### Task 5: Restyle dashboard, storia, analisi, parlay

**Files:**
- Modify: `templates/dashboard.html`, `templates/storia.html`, `templates/analisi.html`, `templates/parlay.html`, `templates/fragments/result_row.html`

**Interfaces:**
- Consumes: classi di Task 3. Nessuna modifica a route o dati passati ai template.

- [ ] **Step 1: Implementa** in stile A (riferimento: mockup opzione A): KPI dashboard con `.kpi`; "Ultime schedelle" con `.table-a`, esiti a pillola (`badge-open` "in corso" quando `outcome` è vuoto, testi `vinta`/`persa`/`annullata` al posto dei codici grezzi), profit a destra con segno e `€`; storia con card distanziate e azioni `.btn-ghost` allineate; analisi e parlay con `.table-a`. Mantieni intatti id, attributi `hx-*` e nomi dei campi dei form (`result_row.html` è sostituito via htmx).
- [ ] **Step 2: Run** `python -m pytest -q` — Expected: verde (i test esistenti controllano testo/status di queste pagine).
- [ ] **Step 3: Verifica in browser** di ogni pagina con dati (crea 2 sessioni e salva un risultato vinto e uno perso): niente testo illeggibile, tabelle ariose, inserimento risultato in Storia funziona via htmx.
- [ ] **Step 4: Commit** `style: restyle dashboard, history, analysis and parlay pages`

### Task 6: Restyle sorteggio

**Files:**
- Modify: `templates/sorteggio.html`, `templates/fragments/pick_row.html`, `templates/fragments/form_lines.html`

**Interfaces:**
- Consumes: classi di Task 3. Invariati: id `pick-row-*`, `picks-*`, `dice-canvas-*`, `dice-result-*`, `save-btn-*`, `hidden-sched-*`, classe `badge-pron` e `opacity-25` (usate dal JS in `sorteggio.html` per contare i pick rivelati), attributi `hx-*`.

- [ ] **Step 1: Implementa** in stile A: card partita con data/nome/pronostico più leggibili, riga Best Prob/Best Odds e forma con `.muted`, area dado e palette colori allineate.
- [ ] **Step 2: Run** `python -m pytest -q` — Expected: verde.
- [ ] **Step 3: Verifica in browser:** lancia tutti i dadi di una schedella → animazione, pronostico mostrato, compare "Salva Schedella"; salva → arriva in Storia.
- [ ] **Step 4: Commit** `style: restyle draw page`
