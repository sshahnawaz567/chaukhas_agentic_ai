# Chaukas web frontend

One static file (`index.html`), no build step. It calls the FastAPI backend over HTTPS.

- Backend URL: defaults to the Render deployment; override with `?api=https://...` or the ⚙ API button (kept in localStorage).
- On `localhost` it talks to `http://localhost:8000`.
- Vercel: Root Directory `web`, Framework Preset `Other`, no build command, no output directory.
- Local: `uvicorn chaukas.main:app` and `python -m http.server 8080 --directory web`.
