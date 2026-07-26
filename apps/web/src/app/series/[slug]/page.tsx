import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AppHeader } from "@/components/AppHeader";
import { GenerateButton } from "@/components/GenerateButton";
import { isAuthenticated } from "@/lib/auth";
import { prisma } from "@/lib/db";

export default async function SeriesDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  if (!(await isAuthenticated())) redirect("/login");
  const { slug } = await params;
  const series = await prisma.series.findUnique({
    where: { slug },
    include: { episodes: { orderBy: { updatedAt: "desc" } } },
  });
  if (!series) notFound();

  return (
    <main className="mx-auto max-w-6xl px-5 py-8 pb-16">
      <AppHeader active="/series" />
      <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="card p-6">
          <h2 className="font-display text-2xl font-semibold">{series.title}</h2>
          <p className="mt-1 text-sm text-muted">
            {series.niche} · {series.language} · {series.postsPerWeek} posts / week
          </p>
          <div className="mt-5 grid grid-cols-[120px_1fr] gap-4 border border-line bg-wash p-4">
            <div
              className="relative aspect-[9/14]"
              style={{
                background: "linear-gradient(165deg, #5c4a38, #2a2118)",
              }}
            >
              <span className="absolute bottom-2 left-2 right-2 font-display text-[0.7rem] tracking-[0.12em] text-[#f2ebe1]/HISTORY</span>
            </div>
            <div>
              <h3 className="font-display text-xl font-semibold">Quiet power. Loud hooks.</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{series.description}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <span className="chip chip-good">QC strict</span>
                <span className="chip">45s target</span>
                <span className="chip chip-good">Cloud autopilot</span>
              </div>
            </div>
          </div>

          <h3 className="font-display mt-8 text-lg font-semibold">Episodes</h3>
          <div className="mt-2 divide-y divide-line">
            {series.episodes.map((ep) => (
              <div key={ep.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div>
                  <h4 className="font-semibold">{ep.title}</h4>
                  <p className="text-sm text-muted">
                    {ep.status} · {ep.stem}
                  </p>
                </div>
                <Link href={`/queue?episode=${ep.id}`} className="btn">
                  Open
                </Link>
              </div>
            ))}
            {series.episodes.length === 0 && (
              <p className="py-4 text-muted">No episodes yet.</p>
            )}
          </div>
        </section>

        <aside className="card p-6">
          <h2 className="font-display text-xl font-semibold">Generate</h2>
          <p className="mb-4 text-sm text-muted">
            Spawns local pipeline (<code>run_pipeline.py</code>). Takes several minutes.
          </p>
          <GenerateButton seriesId={series.id} />
          <Link href="/queue" className="btn mt-4 w-full">
            Local review queue (optional)
          </Link>
        </aside>
      </div>
    </main>
  );
}

