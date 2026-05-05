# BRD Specialist — Web Frontend (Next.js)

Production frontend for the orchestrator. Built with Next.js 14 (App Router),
React 18, Tailwind CSS, Radix primitives, and a shadcn/ui-style component
library.

## Architecture

The app is a **static export** (`output: "export"`). After `next build` it
produces a fully static bundle under `web/out/` which FastAPI serves from
`/static` via the existing `StaticFiles` mount in `core/orchestrator.py`.

```
┌───────────────────────┐        ┌─────────────────────────────┐
│  web/ (Next.js app)   │ build  │  web/out/                   │
│  app, components, lib │ ─────▶ │  index.html + _next/static  │
└───────────────────────┘        └─────────────────────────────┘
                                           │
                                           ▼  mounted at /static
                                 ┌─────────────────────────────┐
                                 │   FastAPI (orchestrator)    │
                                 │   /static/*  →  web/out/*   │
                                 │   /            → index.html │
                                 │   /conversations/* (API)    │
                                 └─────────────────────────────┘
```

The orchestrator falls back to the legacy `frontend/` directory when
`web/out/` does not exist, so existing dev workflows keep working until the
first build.

## Scripts

```bash
cd web

# First-time install
npm install

# Local dev (hot reload, talks to FastAPI at NEXT_PUBLIC_API_BASE)
npm run dev

# Production build (emits static bundle to web/out/)
npm run build

# Type-check only
npm run typecheck
```

## Local development

1. Start the orchestrator and agents:

   ```bash
   python run_system.py
   ```

2. In another terminal, run the Next dev server:

   ```bash
   cd web
   cp .env.example .env.local   # first time only
   npm install                  # first time only
   npm run dev
   ```

3. Open http://localhost:3000 — it proxies API calls to
   `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`).

## Production build + serve

```bash
cd web
npm install
npm run build          # → writes web/out/
cd ..
python run_system.py   # FastAPI auto-picks up web/out/ at /static
```

Open http://localhost:8000 — the orchestrator serves `web/out/index.html` at
`/` and the assets from `/static/_next/...`.

## Key features

- **Real-time streaming** — SSE token stream from `/messages/stream`
- **Agent activity timeline** — visualises orchestrator → specialist routing
- **BRD preview pane** — renders the generated document with copy/export
- **Conversation management** — search, select, delete (CRUD in sidebar)
- **Server log stream** — tailing `/logs/stream` with automatic reconnect
- **Safety review & evidence confirmation** — inline approval cards
- **Responsive** — single-pane on mobile, split layout on desktop

## Tech stack

| Concern           | Choice                                 |
|-------------------|----------------------------------------|
| Framework         | Next.js 14 (App Router, static export) |
| Language          | TypeScript                             |
| Styling           | Tailwind CSS + CSS variables           |
| Components        | Radix primitives + shadcn-style wrappers |
| Markdown          | `marked` + `DOMPurify`                 |
| Icons             | `lucide-react`                         |
| Notifications     | `sonner`                               |
