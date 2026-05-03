## Grove UI (Vite + React)

This is an operator-facing dashboard for the edge device. It reads from the edge API:

- `GET /status`
- `POST /admin/forward/run-once`

### Run locally

```bash
cd src/ui
npm install
VITE_EDGE_API_BASE=http://127.0.0.1:8080 npm run dev
```

Then open `http://127.0.0.1:5173`.

### Config

- **`VITE_EDGE_API_BASE`**: optional base URL for the edge service API.
  - If the UI is served from the same origin as the edge API (reverse-proxied), this can be empty.
  - Example: `VITE_EDGE_API_BASE=http://orchard-monitor:8080`

