import fs from "fs";
import path from "path";
import { NextResponse } from "next/server";
import { pipelineRoot } from "@/lib/paths";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const DEFAULT_RAW =
  process.env.STATUS_LOGS_URL ||
  "https://raw.githubusercontent.com/ArdaYK31/shorts-oto/main/logs/latest.json";

type StatusPayload = Record<string, unknown>;

function readLocalLatest(): StatusPayload | null {
  // Disk-only live logs — not the bundled public snapshot (that can go stale on Vercel).
  const candidates = [
    path.join(pipelineRoot(), "logs", "latest.json"),
    path.join(process.cwd(), "..", "..", "logs", "latest.json"),
  ];
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) {
        return JSON.parse(fs.readFileSync(p, "utf8")) as StatusPayload;
      }
    } catch {
      /* continue */
    }
  }
  return null;
}

async function fetchRemoteLatest(): Promise<StatusPayload | null> {
  try {
    const res = await fetch(DEFAULT_RAW, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    return (await res.json()) as StatusPayload;
  } catch {
    return null;
  }
}

function emptyStatus(): StatusPayload {
  return {
    autopilot: true,
    require_approval: false,
    privacy: "public",
    timezone: "Europe/Istanbul",
    schedule_times: ["00:00", "08:00", "16:00"],
    next_runs: [],
    platforms_connected: {
      youtube: false,
      instagram: false,
      tiktok: false,
      fal: false,
    },
    budget: {
      month: null,
      spent_usd: 0,
      cap_usd: 30,
      images_generated: 0,
      cost_per_image_usd: 0.006,
      provider: "fal_flux_schnell",
    },
    latest_job: null,
    recent_jobs: [],
    actions_url: "https://github.com/ArdaYK31/shorts-oto/actions",
    source: "empty",
    updated_at: new Date().toISOString(),
  };
}

function readBundledFallback(): StatusPayload | null {
  // Stale snapshot shipped with the app — only after live sources fail.
  try {
    const p = path.join(process.cwd(), "public", "status-latest.json");
    if (fs.existsSync(p)) {
      return JSON.parse(fs.readFileSync(p, "utf8")) as StatusPayload;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export async function GET() {
  // Local/dev: prefer live pipeline logs on disk.
  // Vercel: prefer GitHub-committed logs/latest.json (Actions updates it).
  // Never let a bundled public snapshot block the live remote feed.
  const onVercel = Boolean(process.env.VERCEL);
  if (!onVercel) {
    const local = readLocalLatest();
    if (local) {
      return NextResponse.json({ ...local, source: "local" });
    }
  }
  const remote = await fetchRemoteLatest();
  if (remote) {
    return NextResponse.json({ ...remote, source: "github_raw" });
  }
  if (onVercel) {
    const bundled = readBundledFallback();
    if (bundled) {
      return NextResponse.json({ ...bundled, source: "bundled" });
    }
  } else {
    const local = readLocalLatest();
    if (local) {
      return NextResponse.json({ ...local, source: "local" });
    }
  }
  return NextResponse.json(emptyStatus());
}
