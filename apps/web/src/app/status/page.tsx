"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppHeader } from "@/components/AppHeader";

type Platforms = {
  youtube?: boolean;
  instagram?: boolean;
  tiktok?: boolean;
  fal?: boolean;
};

type Job = {
  topic_id?: string | null;
  title?: string | null;
  status?: string;
  ts?: string;
  updated_at?: string;
  links?: { youtube?: string | null; instagram?: string | null; tiktok?: string | null };
  platforms?: Record<string, string | null>;
  error?: string;
};

type Status = {
  autopilot?: boolean;
  require_approval?: boolean;
  privacy?: string;
  timezone?: string;
  schedule_times?: string[];
  next_runs?: string[];
  platforms_connected?: Platforms;
  budget?: {
    month?: string | null;
    spent_usd?: number;
    cap_usd?: number;
    images_generated?: number;
    cost_per_image_usd?: number;
    provider?: string;
  };
  latest_job?: Job | null;
  recent_jobs?: Job[];
  actions_url?: string;
  source?: string;
  updated_at?: string;
};

function fmtWhen(iso?: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("tr-TR", { timeZone: "Europe/Istanbul" });
  } catch {
    return iso;
  }
}

function statusTone(s?: string) {
  const v = (s || "").toLowerCase();
  if (v === "uploaded" || v === "rendered") return "chip-good";
  if (v === "failed") return "text-[var(--copper-deep)]";
  if (v === "rendering" || v === "queued") return "text-[var(--copper)]";
  return "";
}

export default function StatusPage() {
  const [data, setData] = useState<Status | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as Status;
        if (alive) {
          setData(json);
          setErr(null);
        }
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : "load failed");
      }
    };
    load();
    const id = setInterval(load, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const spent = Number(data?.budget?.spent_usd || 0);
  const cap = Number(data?.budget?.cap_usd || 30);
  const pct = Math.min(100, Math.round((spent / Math.max(cap, 0.01)) * 100));
  const plats = data?.platforms_connected || {};
  const jobs = data?.recent_jobs || [];

  return (
    <main className="mx-auto max-w-5xl px-5 py-8 pb-16">
      <AppHeader active="/status" />

      <section className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-copper">
            Control panel
          </p>
          <h1 className="font-display mt-1 text-3xl font-semibold tracking-tight md:text-4xl">
            Autopilot status
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted">
            Schedule 00:00 / 08:00 / 16:00 Europe/Istanbul · public YouTube · no approval gate.
            Image budget tracked vs $30/mo (fal.ai Flux).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip chip-good">Autopilot ON</span>
          <span className="chip">{data?.privacy || "public"}</span>
          <span className="chip">src: {data?.source || "…"}</span>
        </div>
      </section>

      {err && (
        <p className="mb-4 border border-line bg-paper px-4 py-3 text-sm text-copper-deep">
          Status load error: {err}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card p-5">
          <h2 className="font-display text-xl font-semibold">Schedule</h2>
          <p className="mt-1 text-sm text-muted">
            {data?.timezone || "Europe/Istanbul"} ·{" "}
            {(data?.schedule_times || ["00:00", "08:00", "16:00"]).join(" · ")}
          </p>
          <ul className="mt-4 space-y-2 text-sm">
            {(data?.next_runs || []).length === 0 && (
              <li className="text-muted">Next runs appear after first job snapshot.</li>
            )}
            {(data?.next_runs || []).map((r) => (
              <li key={r} className="flex justify-between gap-3 border-b border-line py-2">
                <span className="text-muted">Next</span>
                <span className="font-semibold">{fmtWhen(r)}</span>
              </li>
            ))}
          </ul>
          <a
            href={data?.actions_url || "https://github.com/ArdaYK31/shorts-oto/actions"}
            className="btn mt-4 inline-flex"
            target="_blank"
            rel="noreferrer"
          >
            GitHub Actions runs
          </a>
        </section>

        <section className="card p-5">
          <h2 className="font-display text-xl font-semibold">Image budget</h2>
          <p className="mt-1 text-sm text-muted">
            {data?.budget?.provider || "fal_flux_schnell"} ·{" "}
            {data?.budget?.month || "this month"} · ~
            ${Number(data?.budget?.cost_per_image_usd || 0.006).toFixed(3)}/img
          </p>
          <div className="mt-4">
            <div className="mb-2 flex justify-between text-sm">
              <span className="font-semibold">
                ${spent.toFixed(2)} / ${cap.toFixed(0)}
              </span>
              <span className="text-muted">
                {data?.budget?.images_generated || 0} images · {pct}%
              </span>
            </div>
            <div className="h-3 w-full overflow-hidden border border-line bg-wash">
              <div
                className="h-full bg-sage transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
          <p className="mt-3 text-xs text-muted">
            Target ≤ $0.03/image. Flux Schnell ≈ $0.003–0.006/MP → ~$6–10/mo at ~1000 images.
            Over cap → free Pollinations fallback.
          </p>
        </section>

        <section className="card p-5 md:col-span-2">
          <h2 className="font-display text-xl font-semibold">Platform connections</h2>
          <p className="mt-1 text-sm text-muted">
            Presence only — secrets never shown. Cloud reads GitHub Secrets / env.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(
              [
                ["youtube", "YouTube token"],
                ["instagram", "Instagram (Meta)"],
                ["tiktok", "TikTok"],
                ["fal", "fal.ai FAL_KEY"],
              ] as const
            ).map(([key, label]) => {
              const ok = Boolean(plats[key]);
              return (
                <div key={key} className="border border-line px-3 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{label}</span>
                    <span className={`chip ${ok ? "chip-good" : ""}`}>
                      {ok ? "present" : "missing"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card p-5 md:col-span-2">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <h2 className="font-display text-xl font-semibold">Recent jobs</h2>
            <p className="text-xs text-muted">
              Updated {fmtWhen(data?.updated_at)} · from logs/latest.json
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-muted">
                  <th className="py-2 pr-3 font-medium">When</th>
                  <th className="py-2 pr-3 font-medium">Topic</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 font-medium">Links</th>
                </tr>
              </thead>
              <tbody>
                {jobs.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-6 text-muted">
                      No jobs yet. After a scheduled run, Actions commits{" "}
                      <code>logs/latest.json</code> for this panel.
                    </td>
                  </tr>
                )}
                {jobs.slice(0, 15).map((j, i) => (
                  <tr key={`${j.ts || i}-${j.topic_id}`} className="border-b border-line/70">
                    <td className="py-2.5 pr-3 whitespace-nowrap text-muted">
                      {fmtWhen(j.updated_at || j.ts)}
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="font-semibold">{j.title || j.topic_id || "—"}</div>
                      <div className="text-xs text-muted">{j.topic_id}</div>
                    </td>
                    <td className={`py-2.5 pr-3 font-semibold ${statusTone(j.status)}`}>
                      {j.status || "—"}
                      {j.error ? (
                        <div className="mt-1 max-w-xs truncate text-xs font-normal text-muted">
                          {j.error}
                        </div>
                      ) : null}
                    </td>
                    <td className="py-2.5">
                      <div className="flex flex-wrap gap-2">
                        {j.links?.youtube && (
                          <a
                            className="underline"
                            href={j.links.youtube}
                            target="_blank"
                            rel="noreferrer"
                          >
                            YT
                          </a>
                        )}
                        {j.platforms?.youtube && !j.links?.youtube && (
                          <a
                            className="underline"
                            href={`https://youtu.be/${j.platforms.youtube}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            YT
                          </a>
                        )}
                        {j.links?.instagram || j.platforms?.instagram ? (
                          <span className="text-muted">IG</span>
                        ) : null}
                        {j.links?.tiktok || j.platforms?.tiktok ? (
                          <span className="text-muted">TT</span>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <p className="mt-8 text-sm text-muted">
        Local: <code>npm run dev</code> in <code>apps/web</code> →{" "}
        <Link href="/status" className="underline">
          /status
        </Link>
        . Cloud panel reads committed logs or Actions.
      </p>
    </main>
  );
}
