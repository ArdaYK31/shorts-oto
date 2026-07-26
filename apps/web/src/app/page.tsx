import Link from "next/link";
import { redirect } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

export default async function HomePage() {
  if (await isAuthenticated()) redirect("/status");

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
      <p className="text-sm font-semibold uppercase tracking-[0.18em] text-copper">
        Agency Series Autopilot
      </p>
      <h1 className="font-display mt-4 max-w-3xl text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
        Atelier
      </h1>
      <p className="mt-5 max-w-xl text-lg text-muted">
        Faceless history Shorts for a US audience — ChronoShorts AI stills, Kokoro voice,
        full cloud autopilot (public, no Approve wait). Status panel tracks schedule, jobs,
        and the $30/mo image budget.
      </p>
      <div className="mt-10 flex flex-wrap gap-3">
        <Link href="/login" className="btn btn-primary px-6 py-3">
          Enter workspace
        </Link>
        <Link href="/status" className="btn px-6 py-3">
          Status panel
        </Link>
      </div>
      <ul className="mt-14 grid gap-4 text-sm text-muted md:grid-cols-3">
        <li className="card p-4">
          <strong className="text-ink">3× daily cloud</strong>
          <p className="mt-1">00:00 / 08:00 / 16:00 Istanbul via GitHub Actions.</p>
        </li>
        <li className="card p-4">
          <strong className="text-ink">fal.ai Flux budget</strong>
          <p className="mt-1">~$0.006/img target · $30/mo cap · Pollinations fallback.</p>
        </li>
        <li className="card p-4">
          <strong className="text-ink">Live status</strong>
          <p className="mt-1">Jobs, platforms, budget meter on /status.</p>
        </li>
      </ul>
    </main>
  );
}
