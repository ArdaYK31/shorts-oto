# Atelier status panel — deploy

## Goal
Public HTTPS status panel for ChronoShorts autopilot:
- Schedule 00:00 / 08:00 / 16:00 Europe/Istanbul
- Recent jobs + YT/IG/TT links
- Image budget meter ($30/mo fal.ai)
- Platform connection flags (no secrets shown)

## Fast path (no Vercel login): GitHub Pages
Static panel lives in `docs/index.html` and reads
`https://raw.githubusercontent.com/ArdaYK31/shorts-oto/main/logs/latest.json`.

1. Repo → Settings → Pages → Source: **GitHub Actions**
2. Push triggers `.github/workflows/pages.yml`
3. Live URL (after first green run):
   `https://ardayk31.github.io/shorts-oto/`

## Full Next.js app: Vercel

### A) Vercel CLI (preferred)

```powershell
cd "C:\Users\Ömür KIRBIYIK\Desktop\yt otomatizasyon\apps\web"
npx vercel login
npx vercel --yes --prod
```

If you have a token:

```powershell
$env:VERCEL_TOKEN = "YOUR_TOKEN"
npx vercel --yes --prod --token $env:VERCEL_TOKEN
```

Root Directory in Vercel project settings must be: `apps/web`

### B) GitHub → Vercel UI
1. https://vercel.com/new
2. Import `ArdaYK31/shorts-oto`
3. Root Directory: `apps/web`
4. Framework: Next.js
5. Environment variables (Production):

| Name | Value |
|------|--------|
| `AUTH_PASSWORD` | `atelier` (or change) |
| `AUTH_COOKIE_SECRET` | long random string |
| `DATABASE_URL` | `file:./dev.db` |
| `STATUS_LOGS_URL` | `https://raw.githubusercontent.com/ArdaYK31/shorts-oto/main/logs/latest.json` |

6. Deploy → copy `*.vercel.app` URL

### C) After deploy
- Open `https://YOUR-PROJECT.vercel.app/status`
- Login password = `AUTH_PASSWORD` (default `atelier`)
- Status reads `logs/latest.json` from GitHub after each Actions run commits it

## Local panel
```powershell
cd apps\web
npm install
npm run db:setup
npm run dev
```
→ http://localhost:3000/status

## Custom domain
Optional later in Vercel → Project → Domains.
