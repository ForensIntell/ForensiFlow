# ForensiFlow Web

ForensiFlow web UI is a Vite + React + TypeScript frontend that reads real
data from the local ForensiFlow HTTP adapter.

## Run

```bash
cd forensiflow-web
npm install
npm run dev
```

By default the app talks to `http://127.0.0.1:8791/api` through the Vite
proxy. To point the frontend at another backend, create `.env.local`:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8791
# compatibility alias
VITE_FORENSIFLOW_API_BASE=http://127.0.0.1:8791
```

## Backend contract

The frontend currently consumes real `/api/*` endpoints for:

- health and device status
- dashboard metrics
- app list and workspace state
- plan creation and task execution
- evidence, audit sessions, and report download

Capabilities not supported by the backend are hidden, disabled, or marked as
not yet available. Placeholder data is intentionally removed.
