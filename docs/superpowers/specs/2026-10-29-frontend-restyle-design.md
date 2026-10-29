# Frontend restyle + popup di avanzamento — design

## Perché

L'utente usa l'app web (FastAPI + Jinja2 + Tailwind CDN, `templates/`) da PC. Due problemi concreti:

1. In **Nuova Schedella**, dopo "Avanti" non succede niente di visibile per molti secondi (upload, poi
   `GET /configura/{id}` parsa l'Excel ~9s in locale, di più su Railway). L'utente clicca più volte:
   ogni clic crea una nuova sessione con una copia del BLOB Excel → doppioni in "Schedelle caricate".
2. Il frontend è trasandato: menu in alto "tutto attaccato", tabella risultati brutta, aspetto generale da rifare.

Causa probabile del punto 2: in `templates/base.html` le classi custom (`.nav-link`, `.card`, `.btn-gold`,
`.btn-ghost`, `.badge-*`, `.input-gold`, `.toggle-*`) usano `@apply` dentro un `<style>` normale. Il Tailwind
Play CDN elabora `@apply` solo dentro `<style type="text/tailwindcss">`, quindi quelle classi oggi non hanno
effetto (non verificato in browser — il builder lo confermi prima di tutto).

## Obiettivi

- Popup di avanzamento modale su **"Avanti"** (Nuova Schedella: upload file, "Usa <default>", "Riapri"
  da Schedelle caricate) e su **"Avvia Sorteggio"** (Configura). Blocca i clic ripetuti dal primo clic.
- Accorciare l'attesa di "Avanti": l'Excel va letto una volta sola per aprire Configura (oggi
  `get_excel_preview` legge il file due volte: anteprima con `pd.read_excel` + `read_schedule`).
- Restyle di **tutte** le pagine nella direzione **A "Oro scuro, rifinito"** (scelta dall'utente sul mockup
  `docs/superpowers/specs/2026-10-29-frontend-restyle-mockup.html`, opzione A — riferimento di direzione
  per colori, spazi, menu, tabella e popup, non da copiare al pixel; dove diverge da questo documento vale
  il documento):
  - identità attuale nero/oro mantenuta (palette in `base.html`: bg `#12100a`, surface `#1a160d`,
    border `#2d2410`, accent `#f59e0b`, gold `#fde68a`);
  - menu: voci distanziate, pagina attiva come pillola (sfondo `#2d2410`, testo `#fde68a`),
    "Nuova" come bottone oro a destra al posto della voce normale;
  - KPI in card con etichetta piccola maiuscola spaziata e valore grande;
  - tabelle: header su sfondo leggermente diverso, righe ariose (padding ~10px 12px), separatori sottili,
    numeri allineati a destra con cifre tabulari, esiti come pillole colorate (vinta verde, persa rosso,
    in corso oro);
  - testo secondario più leggibile (oggi `#92400e`/`#78716c` su nero sono poco contrastati).
- Pagine: dashboard, nuova, configura, sorteggio, storia, analisi, parlay + fragment (`pick_row`,
  `result_row`, `form_lines`).

## Non-obiettivi

- Nessun cambio al flusso o alla logica: sorteggio, dado 3D (`static/dice.js`, Three.js), calcoli quote/forma,
  DB restano come sono.
- Niente framework nuovo, niente build step: resta Jinja2 + Tailwind CDN + JS vanilla/htmx.
- Mobile non prioritario (uso da PC): la nav mobile esistente deve continuare a funzionare, non va ridisegnata.
- Niente tema chiaro.

## Anti-obiettivi (fallimento anche se "funziona")

- Popup con avanzamento finto: i passi mostrati come completati devono esserlo davvero.
- Clic ripetuti sullo stesso pulsante che creano ancora doppia sessione o doppio sorteggio.
  *Scelta mia:* basta il blocco lato client (app personale, un utente da PC); nessuna deduplica lato server
  per seconda scheda, F5 o risposta persa.
- Regressioni funzionali: htmx del sorteggio, lancio dado, salvataggio, quote/forma in Configura,
  frecce movimento quote — tutto deve continuare a funzionare. I 62 test pytest restano verdi.

## Popup — comportamento deciso

**"Avanti" / "Usa default" / "Riapri"** — passi reali:
1. "Carico il file" → completato quando la POST risponde.
2. "Leggo le partite dall'Excel" → in corso mentre il browser carica `/configura/{id}`.
3. Il popup sparisce con la navigazione.

Per sapere quando la POST è finita senza aprire subito la pagina lenta, il builder può inviare con `fetch`
e far restituire al server l'URL di destinazione (es. JSON se la richiesta lo chiede, redirect 303 invariato
altrimenti, così i test esistenti e il funzionamento senza JS restano). *Scelta mia, il dettaglio è del builder.*

**"Avvia Sorteggio"** — è una sola POST lunga (lettura Excel, quote TheOddsAPI per partita, forma
football-data, sorteggio, salvataggio): il server non manda avanzamento. *Scelta mia:* il popup mostra
l'elenco delle fasi con uno spinner e il tempo trascorso, senza segnare singole fasi come completate
(niente avanzamento finto). Se la POST torna con errore (pagina 400 di Configura) il popup sparisce da sé
perché la pagina si ricarica.

In entrambi i casi: pulsante disabilitato al primo clic; se la richiesta fallisce lato rete il popup
mostra l'errore e riabilita il pulsante.

## Vincoli

- Tailwind via CDN (`cdn.tailwindcss.com`), htmx 2.0.4 da unpkg, Three.js r134 da cdnjs: restano.
- Autoescape Jinja2 attivo; nel JS il rendering dei dati usa `textContent` (convenzione già nel codice).
- Test: `python -m pytest -q` (oggi 62 verdi). Le route esistenti mantengono status e redirect attuali.
- Lingua UI: italiano.

## Lasciato al builder

- Come sistemare le classi custom (`<style type="text/tailwindcss">` o CSS puro) e come organizzarle.
- Markup preciso di ogni pagina, purché in direzione A e coerente tra pagine.
- Come evitare la doppia lettura dell'Excel in Configura. *Scelta mia sui limiti:* prima misurare dove va
  il tempo (quale delle due letture pesa, se `read_schedule` legge più fogli del necessario); ammessa una
  cache in memoria del risultato per `session_id` (persa al riavvio, va bene); **nessuna modifica allo
  schema DB**. Spostare il parsing nella POST di upload non serve: sposta solo il tempo da un passo all'altro.
- Componente popup (partial Jinja + JS condiviso, o altro).
