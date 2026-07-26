import { redirect } from "next/navigation";
import { AppHeader } from "@/components/AppHeader";
import { isAuthenticated } from "@/lib/auth";
import fs from "fs";
import path from "path";

function credStatus(): {
  youtube: "connected" | "missing";
  instagram: "env-ready" | "needs-setup";
  tiktok: "env-ready" | "needs-setup";
} {
  // Local dashboard: detect YouTube files; IG/TT are cloud env secrets only.
  const root = path.resolve(process.cwd(), "..", "..");
  const credDir = path.join(root, "credentials");
  const yt =
    fs.existsSync(path.join(credDir, "client_secret.json")) &&
    fs.existsSync(path.join(credDir, "youtube_token.json"))
      ? "connected"
      : "missing";
  return {
    youtube: yt,
    instagram: "needs-setup",
    tiktok: "needs-setup",
  };
}

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
        ok ? "bg-sage/20 text-ink" : "bg-line text-muted"
      }`}
    >
      {label}
    </span>
  );
}

export default async function SettingsPage() {
  if (!(await isAuthenticated())) redirect("/login");
  const status = credStatus();

  return (
    <main className="mx-auto max-w-3xl px-5 py-8 pb-16">
      <AppHeader active="/settings" />
      <section className="card p-6">
        <h2 className="font-display text-2xl font-semibold">Settings</h2>
        <p className="mb-6 text-sm text-muted">
          Cloud schedule is <strong>full autopilot</strong>: 3×/day public posts
          (00:00 / 08:00 / 16:00 Europe/Istanbul) with{" "}
          <strong>no Approve wait</strong>. This dashboard queue is optional for
          manual local runs only. See <code>CLOUD_SETUP.txt</code>.
        </p>

        <div className="mb-6 border border-line p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">YouTube Shorts</h3>
            <Badge
              ok={status.youtube === "connected"}
              label={status.youtube === "connected" ? "Token on disk" : "Not connected"}
            />
          </div>
          <p className="mt-1 text-sm text-muted">
            OAuth via <code>credentials/</code>. Cloud uses GitHub Secrets{" "}
            <code>YOUTUBE_TOKEN_JSON</code> + <code>YOUTUBE_CLIENT_SECRET_JSON</code>.
            Privacy: <strong>public</strong>.
          </p>
          <button type="button" className="btn mt-3 opacity-60" disabled>
            Connect YouTube (use youtube_auth.py)
          </button>
        </div>

        <div className="mb-6 border border-line p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">Instagram Reels</h3>
            <Badge ok={false} label="Needs Meta app" />
          </div>
          <p className="mt-1 text-sm text-muted">
            Official Graph API Content Publishing. Set{" "}
            <code>META_ACCESS_TOKEN</code> + <code>IG_USER_ID</code> in GitHub
            Secrets. Without them, schedule skips IG and still posts YouTube.
            Caption = SEO title + description + hashtags.
          </p>
          <button type="button" className="btn mt-3 opacity-60" disabled>
            Connect Instagram (cloud secrets)
          </button>
        </div>

        <div className="mb-6 border border-line p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">TikTok</h3>
            <Badge ok={false} label="Needs TikTok app" />
          </div>
          <p className="mt-1 text-sm text-muted">
            Official Content Posting API. Set <code>TIKTOK_ACCESS_TOKEN</code>.
            Default privacy <code>PUBLIC_TO_EVERYONE</code>. App audit may be
            required for Direct Post; inbox draft fallback exists.
          </p>
          <button type="button" className="btn mt-3 opacity-60" disabled>
            Connect TikTok (cloud secrets)
          </button>
        </div>

        <div className="mb-6 border border-line p-4">
          <h3 className="font-semibold">Voice</h3>
          <p className="mt-1 text-sm text-muted">
            Production TTS: Kokoro <code>am_fenrir</code> (cloud Docker + local
            .venv312). ESPEAK via apt / <code>C:\espeak-ng-data</code>.
          </p>
        </div>

        <div className="border border-line p-4">
          <h3 className="font-semibold">Content language</h3>
          <p className="mt-1 text-sm text-muted">
            Locked to English for scripts, captions, titles, and SEO. UI theme:
            Daylight Atelier.
          </p>
        </div>
      </section>
    </main>
  );
}
