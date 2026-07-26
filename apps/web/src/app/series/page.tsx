import Link from "next/link";
import { redirect } from "next/navigation";
import { AppHeader } from "@/components/AppHeader";
import { isAuthenticated } from "@/lib/auth";
import { prisma } from "@/lib/db";

export default async function SeriesListPage() {
  if (!(await isAuthenticated())) redirect("/login");
  const series = await prisma.series.findMany({
    include: { _count: { select: { episodes: true } } },
    orderBy: { createdAt: "desc" },
  });

  return (
    <main className="mx-auto max-w-6xl px-5 py-8 pb-16">
      <AppHeader active="/series" />
      <section className="card p-6">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-2xl font-semibold">Series</h2>
            <p className="text-sm text-muted">English content · American history MVP</p>
          </div>
          <Link href="/series/new" className="btn btn-primary">
            Create series
          </Link>
        </div>
        <div className="grid gap-4">
          {series.map((s) => (
            <Link
              key={s.id}
              href={`/series/${s.slug}`}
              className="block border border-line bg-wash/40 p-5 transition hover:bg-wash"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-display text-xl font-semibold">{s.title}</h3>
                  <p className="mt-1 text-sm text-muted">{s.description || s.niche}</p>
                </div>
                <div className="flex gap-2">
                  <span className="chip chip-good">{s.language}</span>
                  <span className="chip">{s._count.episodes} eps</span>
                  <span className="chip">{s.postsPerWeek}/wk</span>
                </div>
              </div>
            </Link>
          ))}
          {series.length === 0 && (
            <p className="text-muted">No series yet. Create one or run the seed.</p>
          )}
        </div>
      </section>
    </main>
  );
}

