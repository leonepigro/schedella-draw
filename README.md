# schedella-draw

Tool per la gestione della schedella settimanale: estrae pronostici da quote reali, calcola EV, suggerisce combinazioni parlay e storicizza i risultati.

## Funzionalità

- Importa Excel con le partite della settimana
- Recupera quote in tempo reale da [TheOddsAPI](https://the-odds-api.com/)
- Calcola probabilità implicite, Best EV e Best Prob per ogni pronostico
- Sorteggio casuale pesato sulle probabilità
- Calcolo combinazioni parlay con filtro min/max moltiplicatore, ordinate per EV
- Filtro partite per giorno/ora o colonna COS
- Storico schedelle con ROI e analisi win rate *(GUI in sviluppo)*

## Installazione

```bash
pip install -r requirements.txt
```

## Uso CLI

```bash
python -m src.schedella \
  --file "Schedella.xlsx" \
  --use-odds \
  --theodds-key <API_KEY> \
  --players 1 \
  --per-player 3 \
  --allow-4th \
  --parlay-target 10 \
  --parlay-max 30 \
  --interactive
```

### Parametri

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `--file`, `-f` | *obbligatorio* | File Excel con le partite |
| `--players` | `1` | Numero di giocatori |
| `--per-player` | `3` | Partite per giocatore |
| `--allow-4th` | off | Estrae una 4a partita opzionale |
| `--use-odds` | off | Usa quote per calcolare le probabilità |
| `--theodds-key` | — | API key per TheOddsAPI |
| `--column` | — | Nome colonna COS per partite obbligatorie |
| `--filter-day` | — | Filtra per giorno (es. `domenica`) |
| `--filter-time` | — | Filtra per ora (es. `20:45`) |
| `--parlay-target` | — | Moltiplicatore minimo per parlay |
| `--parlay-max` | — | Moltiplicatore massimo per parlay |
| `--interactive`, `-i` | off | Modalità interattiva: scegli i pronostici manualmente |
| `--only-mandatory` | off | Mostra solo le partite con COS marcate |
| `--seed` | — | Seed per la riproducibilità |
| `--debug-odds` | off | Stampa le risposte API TheOddsAPI |
| `--out` | — | Salva output in JSON |
| `--dump` | off | Stampa il foglio Excel grezzo ed esce |

### Esempi

```bash
# Partite domenica 20:45 con parlay tra 10x e 30x
python -m src.schedella --file Schedella.xlsx \
  --use-odds --theodds-key KEY \
  --filter-day domenica --filter-time 20:45 \
  --parlay-target 10 --parlay-max 30

# 3 giocatori con colonna COS obbligatoria
python -m src.schedella --file Schedella.xlsx \
  --players 3 --column Cos --allow-4th --interactive
```

## Formato Excel

Il file Excel deve avere:
- **Riga 2** come intestazione (header=1)
- Colonna con nome partita (es. `Partita` o `Home`)
- Colonna data/ora (es. `Giorno/Ora`)
- Colonna COS opzionale (marcata con `X` per partite obbligatorie)
- Colonne quote opzionali con suffissi `_1`, `_X`, `_2`, `_under`, `_over`, `_gol`, `_no_gol`

## GUI (in sviluppo)

Interfaccia web con:
- Import Excel drag-and-drop
- Sorteggio con dado 3D animato (Three.js)
- Storico schedelle e inserimento risultati
- Analisi ROI e win rate nel tempo
- Deploy su Railway

## Licenza

MIT
