from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html lang="it">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Schedella Draw</title>
      <style>
        body { margin: 0; background: #12100a; color: #fde68a;
               font-family: system-ui, sans-serif;
               display: flex; align-items: center; justify-content: center;
               min-height: 100vh; text-align: center; }
        h1 { font-size: 2.5rem; color: #f59e0b; margin-bottom: 0.5rem; }
        p  { color: #92400e; font-size: 1.1rem; }
      </style>
    </head>
    <body>
      <div>
        <h1>⚽ Schedella Draw</h1>
        <p>GUI in costruzione — presto disponibile.</p>
      </div>
    </body>
    </html>
    """
