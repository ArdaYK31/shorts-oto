# YouTube History Shorts + Atelier Series Autopilot

Sıfır nakit maliyetli yerel pipeline + **Atelier** dashboard + **bulut schedule** (GitHub Actions):
Amerikan tarihi Shorts üret → TTS (`auto`: ElevenLabs secret varsa / yoksa Kokoro) → Whisper karaoke + beat-sync → FFmpeg →  
**YouTube Shorts + Instagram Reels + TikTok** (public). PC kapalıyken de çalışır.

> Kurulum: **`CLOUD_SETUP.txt`** (Türkçe, adım adım). Yerel Task Scheduler ikincildir.


## Dil politikası

- **Video içeriği her zaman İngilizce:** narration, captions, titles, description, tags, SEO JSON.
- **İzleyici:** Amerikan (US attention). Konular yalnız ABD tarihi değil — dünya tarihi, biyografi, did-you-know shock fact’ler de havuzda.
- Senaryolar: `scenarios/history_hooks.json` (öncelikli).
- Dashboard UI: Daylight **Atelier**. Prototype: `prototypes/c-atelier.html`.

## Gereksinimler

- Python **3.12** (`.venv312`)
- FFmpeg + ffprobe (PATH)
- Node **20+** (dashboard)
- `ESPEAK_DATA_PATH=C:\espeak-ng-data` (Kokoro / phonemizer)
- İnternet (PD görseller + model indirmeleri; ElevenLabs yalnızca `ELEVENLABS_API_KEY` secret ile)

## Pipeline çalıştır

```powershell
cd "C:\Users\Ömür KIRBIYIK\Desktop\yt otomatizasyon"
$env:ESPEAK_DATA_PATH = "C:\espeak-ng-data"
.\.venv312\Scripts\Activate.ps1
python src\run_pipeline.py --topic-id ulysses-grant-nobody
```

Çıktılar:
- `out\<id>.mp4` — video (CRF~17, Ken Burns no-shake, BGM duck, hook caption)
- `captions\<id>.beats.json` — beat-sync haritası
- `seo\<id>.seo.json` — İngilizce SEO pack
- `out\<id>.UPLOAD.txt` — manuel yükleme notları

## Dashboard (Atelier)

```powershell
cd apps\web
npm install
npm run db:setup
npm run dev
```

Aç: **http://127.0.0.1:3000**

| | |
|--|--|
| Varsayılan şifre | `atelier` (`.env` → `AUTH_PASSWORD`) |
| Seed | Org + American History Vault + Grant episode |
| Ekranlar | Landing, Series, Series detail, Approval queue, Settings |

Pipeline tetikleme: Queue/Series içinden `Generate` → `python src/run_pipeline.py` spawn (arka plan job).

## Kalite yığını

| Parça | Araç |
|-------|------|
| TTS | `auto`: ElevenLabs multilingual_v2 if `ELEVENLABS_API_KEY`; else Kokoro **`am_adam`** @ 1.05 |
| Narration post | FFmpeg: compress → mild lowshelf → presence ~3.2kHz → de-ess → loudnorm |
| Captions | Centered 1-word white+outline (ChronoShorts) via faster-whisper |
| Beat-sync | Whisper/script beats → scene süreleri |
| Assemble | Ken Burns + grade + CRF 17 + loudnorm |
| BGM | `bgm/soft_cinematic_pad.mp3` (layered pad + slow pulse) + sidechain duck (~0.15) |
| Cleanup | `cleanup_temps`: `*.tmp.mp4` / `_partial` / work-dir MP4 silinir; yalnız `out/{stem}.mp4` kalır |
| Media | **`ai_local`** ChronoShorts painterly stills (SD-Turbo / Pollinations) → Wikimedia fallback |
| Style | `STYLE_GUIDE_CHRONOSHORTS.md` + `prompts/image_style.txt` |
| DB | SQLite + Prisma (`apps/web`) |

## Autopilot (onay yok)

Cloud schedule **tam otomatik**: render → SEO → **hemen public** upload (YouTube + IG + TikTok).
`schedule.require_approval: false` — Approve butonu / review queue **beklenmez**.
Atelier Approve kuyruğu yalnızca yerel/manuel deneyler içindir. OAuth only — asla şifre yok.

## Klasör yapısı

```
yt otomatizasyon/
  src/                 # Python pipeline
  topics/ scripts/ audio/ media/ captions/ out/ bgm/ seo/
  prototypes/          # UI referans (c-atelier.html kilitlendi)
  apps/web/            # Next.js Atelier dashboard
```

## UI notu

Atelier teması kilitli. `prototypes/` referans olarak kalır; ayrı A/B rebuild yok.

