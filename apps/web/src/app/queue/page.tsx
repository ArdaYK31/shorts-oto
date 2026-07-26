import { redirect } from "next/navigation";
import { AppHeader } from "@/components/AppHeader";
import { ApproveReject } from "@/components/ApproveReject";
import { isAuthenticated } from "@/lib/auth";
import { prisma } from "@/lib/db";
import fs from "fs";

export default async function QueuePage({
  searchParams,
}: {
  searchParams: Promise<{ episode?: string }>;
}) {
  if (!(await isAuthenticated())) redirect("/login");
  const sp = await searchParams;

  const episodes = await prisma.episode.findMany({
    where: { status: { in: ["IN_REVIEW", "GENERATING", "DRAFT"] } },
    include: { series: true },
    orderBy: { updatedAt: "desc" },
  });

  const selected =
    episodes.find((e) => e.id === sp.episode) ||
    episodes.find((e) => e.status === "IN_REVIEW") ||
    episodes[0] ||
    null;

  let seo: Record<string, unknown> | null = null;
  if (selected?.seoJson) {
    try {
      seo = JSON.parse(selected.seoJson);
    } catch {
      seo = null;
    }
  }

  const videoExists = !!(selected?.videoPath && fs.existsSync(selected.videoPath));
  const videoSrc = selected ? `/api/media/${selected.stem}.mp4` : null;

  return (
    <main className="mx-auto max-w-6xl px-5 py-8 pb-16">
      <AppHeader active="/queue" />
      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="card p-6">
          <h2 className="font-display text-2xl font-semibold">Approval queue</h2>
          <p className="mb-5 text-sm text-muted">
            Human review required. Upload stays manual (Phase 3 YouTube OAuth stubbed).
          </p>
          <div className="divide-y divide-line">
            {episodes.map((ep) => (
              <a
                key={ep.id}
                href={`/queue?episode=${ep.id}`}
                className={`block py-4 ${selected?.id === ep.id ? "bg-wash/50 -mx-2 px-2" : ""}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold">{ep.title}</h3>
                    <p className="text-sm text-muted">
                      {ep.series.title} · {ep.status}
                    </p>
                  </div>
                  <span className={`chip ${ep.status === "IN_REVIEW" ? "chip-good" : ""}`}>
                    {ep.status}
                  </span>
                </div>
              </a>
            ))}
            {episodes.length === 0 && (
              <p className="py-6 text-muted">Queue empty. Generate an episode from a series.</p>
            )}
          </div>
        </section>

        <aside className="card p-6">
          {selected ? (
            <>
              <h2 className="font-display text-xl font-semibold">Now reviewing</h2>
              <p className="mb-4 text-sm text-muted">{selected.title}</p>
              <div className="mx-auto mb-4 flex max-w-[220px] justify-center">
                {videoExists && videoSrc ? (
                  <video
                    className="aspect-[9/16] w-full border border-line bg-ink object-cover shadow-xl"
                    src={videoSrc}
                    controls
                    playsInline
                  />
                ) : (
                  <div
                    className="relative aspect-[9/16] w-full border border-line shadow-xl"
                    style={{ background: "linear-gradient(180deg, #6a543f, #2c2218)" }}
                  >
                    <p className="absolute inset-x-[10%] bottom-[26%] text-center font-display text-lg font-bold leading-tight text-white drop-shadow">
                      {(seo?.hook as string) || "Video pending"}
                    </p>
                  </div>
                )}
              </div>
              <blockquote className="mb-4 border-l-[3px] border-copper pl-3 font-display text-[1.05rem] italic leading-snug">
                {selected.scriptText?.split(/(?<=[.!?])\s+/)[0] || "No script yet."}
              </blockquote>
              <div className="mb-4 max-h-40 overflow-auto border border-line bg-wash/50 p-3 text-xs leading-relaxed text-muted">
                <pre className="whitespace-pre-wrap font-sans">
                  {selected.scriptText || "(script missing)"}
                </pre>
              </div>
              {seo && (
                <div className="mb-4 text-sm text-muted">
                  <p>
                    <strong className="text-ink">SEO title:</strong> {String(seo.title || "")}
                  </p>
                  <p className="mt-1">
                    <strong className="text-ink">Tags:</strong>{" "}
                    {Array.isArray(seo.tags) ? seo.tags.slice(0, 6).join(", ") : "—"}
                  </p>
                </div>
              )}
              <ApproveReject episodeId={selected.id} />
            </>
          ) : (
            <p className="text-muted">Select an episode to review.</p>
          )}
        </aside>
      </div>
    </main>
  );
}

