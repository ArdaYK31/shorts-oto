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
  const candidates = [
    path.join(pipelineRoot(), "logs", "latest.json"),
    path.join(process.cwd(), "..", "..", "logs", "latest.json"),
    path.join(process.cwd(), "public", "status-latest.json"),
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

export async function GET() {
  const local = readLocalLatest();
  if (local) {
    return NextResponse.json({ ...local, source: "local" });
  }
  const remote = await fetchRemoteLatest();
  if (remote) {
    return NextResponse.json({ ...remote, source: "github_raw" });
  }
  return NextResponse.json(emptyStatus());
}
