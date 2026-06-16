# Yara Frontend

Minimal React + TypeScript + Vite UI for the Phase 1 MVP loop.

## Run Locally

Start the backend first:

```bash
cd backend
fastapi dev app/main.py
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL, usually `http://localhost:5173`.

The dev server proxies `/api` to `http://localhost:8000`, so no backend CORS change is needed for local development.

## Build

```bash
cd frontend
npm run build
```

To point the frontend at a different API base URL, set `VITE_API_BASE_URL`.
