# frontend

React 19 + Vite single-page app. Source map in [src/README.md](src/README.md).

## Dev setup

```bash
npm install

# .env: VITE_API_URL=http://localhost:8000   (backend must be running: make dev)

npm run dev     # Vite dev server
npm run lint    # ESLint
```

## Deploy (Firebase Hosting)

```bash
# 1. Update .env with your production backend URL
VITE_API_URL=https://your-cloud-run-url.a.run.app

# 2. Build
npm run build

# 3. Deploy
firebase deploy --only hosting:book-rec --project tuanqpham0921
```
