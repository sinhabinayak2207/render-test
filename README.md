# Tender Agent — Backend (FastAPI)

CS Direkt tender-acquisition pipeline + chat agent.
TenderKart fetch → extract (regex + gpt-4o-mini) → RULES qualifier → Claude narrative → Supabase,
plus a gpt-5-mini chat agent and a WeasyPrint PDF report (reportlab fallback).

## Run locally
```bash
cp .env.example .env          # fill in your keys
pip install -r requirements.txt -r requirements-pipeline.txt
uvicorn app.main:app --port 9000 --reload
```

## Deploy to Render (Docker)
1. Push this folder to a GitHub repo.
2. Render → **New → Blueprint** (uses `render.yaml`) — or **New → Web Service → Docker**.
3. Set the secret env vars (see `.env.example`) in the Render dashboard.
4. The `Dockerfile` installs WeasyPrint's native libs (Pango/Cairo/GDK-Pixbuf),
   so the PDF report renders correctly — no GTK hassle like on Windows.

## Frontend wiring
Point the Next.js dashboard's `BACKEND_API_URL` at the Render service URL
(e.g. `https://tender-agent-backend.onrender.com`). The frontend can run on
localhost while the backend runs on Render — Supabase (shared) carries the
realtime progress, report links, and chat events.
