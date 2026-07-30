# ChronoShorts Style Guide (`@ChronoShorts00`)

Reference analysis (2026-07-26): channel Shorts grid + **2** downloaded Shorts  
(`iUg9XKcumzE` — Mao; `fkFWq4wNSfA` — Augustus). No infinite browser playback.

## 1. Visual style

| Axis | ChronoShorts look |
|------|-------------------|
| Source | **AI illustration** (not archival stock photos) |
| Art | Semi-realistic **painterly** digital art / cinematic concept art — soft brush texture, not anime, not pure photoreal |
| Grade | Muted earthy base + selective warm accents; dramatic daylight or lantern chiaroscuro |
| Characters | Period costume, heroic/central framing, recognizable when famous |
| Text on image | **None baked into the render** — captions are a separate overlay layer |
| Pacing | ~35–50s Shorts; scene stills ~3s with subtle Ken Burns zoom/pan |
| Transitions | Soft crossfade / cut on narration beats — no flashy wipes |
| Thumbnails | Vertical 9:16 still of the hero scene + bold center title word energy (YouTube auto-thumb often mid-frame) |

**Pipeline match:** prefer generated stills via `media.provider: ai_local` (or free Pollinations fallback). Wikimedia/LOC is authenticity fallback only — it does **not** match ChronoShorts.

## 2. Caption / typography

- **Font:** Heavy bold sans-serif (Arial Black / Impact-like weight)
- **Case:** ALL CAPS, usually **1 word** (sometimes 2 short words)
- **Color:** White fill + **thick black outline** (no soft glow)
- **Placement:** Dead **center** of the 9:16 frame (not bottom karaoke bar)
- **Motion:** Word-synced to narration; no decorative stickers/emojis on the video canvas
- Hook cold-open sentence overlay is optional; ChronoShorts often jumps straight into center words

## 3. Voice

| Trait | Observed | Mapping |
|-------|----------|---------|
| Gender | Male | `am_*` / ElevenLabs male premades |
| Accent | US English | `lang: en-us` |
| Pitch | Young conversational storyteller (Zack D–like, not deep Adam doc) | **ElevenLabs Will** `bIHbv24MWmeRgasZH58o`; Kokoro fallback **`am_michael`** |
| Pacing | Punchy TikTok/Shorts storytelling | `speed: 1.14` (EL style ~0.62) |
| Emotion | Curious, urgent asides — not radio-doc gravel | Soft compressor + presence shelf |
| Loudness | Very steady (LRA ≈ 1 LU on samples) | `loudnorm` in TTS post |

**Post-EQ (ChronoShorts-tuned):** compressor → mild lowshelf → presence ~3.2 kHz → de-ess → loudnorm −16 LUFS.

A/B alternatives: EL Chris / Josh; Kokoro `am_onyx`; deeper drama: `am_fenrir` @ 1.0.

## 4. Hook / title SEO patterns (topics stay user-expanded)

Titles (from channel sample):

- `The X Who Y` — *The Peasant Who Ruled a Billion People*
- `From A to B` / colon payoff — *Firewood Seller to Lee's Conqueror: Ulysses Grant*
- Irony paradox — *America's Greatest Hero Turned Its Greatest Traitor*
- Shock death/detail — *History's Most Feared Warlord Was Killed by a Nosebleed*
- Did-you-know question energy in description/narration even when title is declarative

Narration cold open (observed):

> “Did you know [NAME] …?” → name/date → sticky facts → twist closer

Audience: **US-attention English**; topics = US history **and** world figures / empires / did-you-know (do not shrink the topics pool).

Hashtags in descriptions: `#history #Shorts #didyouknow #historyfacts` + topic tags.

## 5. Media providers & cost

| `media.provider` | Cost | Style match | Notes |
|------------------|------|-------------|-------|
| **`ai_local`** (default) | **$0** | Best | Diffusers SD-Turbo on local GPU (GTX 1650 Ti ok with slicing). Slow/CPU if no CUDA. |
| `ai_api` | **$0** (Pollinations) or paid | High | Default backend `pollinations` (no key). Optional OpenAI/Replicate keys later. |
| `wikimedia` | **$0** | Low | PD photos — keep as fallback only |

Cascade when `ai_local` cannot load torch/diffusers: Pollinations (if `allow_free_api_fallback: true`) → Wikimedia.

## 6. Files

- `prompts/image_style.txt` — locked style prefix
- `config.yaml` — TTS / captions / media.provider
- `src/generate_images.py` — AI still generation
- `src/fetch_media.py` — provider switch
