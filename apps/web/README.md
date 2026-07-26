# Atelier · Series Autopilot (web)

Daylight Atelier dashboard for the local YouTube Shorts pipeline.

## Setup

```powershell
cd apps\web
npm install
npm run db:setup
npm run dev
```

- URL: http://127.0.0.1:3000
- Password: `atelier` (override with `AUTH_PASSWORD` in `.env`)

## Scripts

| Script | Meaning |
|--------|---------|
| `npm run dev` | Next.js dev server |
| `npm run db:setup` | prisma generate + db push + seed |
| `npm run build` | production build |

## Notes

- Content language: English only
- YouTube OAuth: Settings stub (Phase 3)
- Pipeline spawn: `POST /api/pipeline/run`

