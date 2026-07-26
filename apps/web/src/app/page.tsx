import Link from "next/link";
import { redirect } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

export default async function HomePage() {
  if (await isAuthenticated()) redirect("/series");

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
      <p className="text-sm font-semibold uppercase tracking-[0.18em] text-copper">
        Agency Series Autopilot
      </p>
      <h1 className="font-display mt-4 max-w-3xl text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
        Atelier
      </h1>
      <p className="mt-5 max-w-xl text-lg text-muted">
        Faceless American history Shorts — English content, local Kokoro + Whisper.
        Cloud schedule is full autopilot (public, no Approve wait). Zero paid video APIs.
      </p>
      <div className="mt-10 flex flex-wrap gap-3">
        <Link href="/login" className="btn btn-primary px-6 py-3">
          Enter workspace
        </Link>
        <Link href="/series" className="btn px-6 py-3">
          Series list
        </Link>
      </div>
      <ul className="mt-14 grid gap-4 text-sm text-muted md:grid-cols-3">
        <li className="card p-4">
          <strong className="text-ink">Beat-synced scenes</strong>
          <p className="mt-1">Whisper beats drive Ken Burns cuts.</p>
        </li>
        <li className="card p-4">
          <strong className="text-ink">Optional queue</strong>
          <p className="mt-1">Local preview only — cloud never waits.</p>
        </li>
        <li className="card p-4">
          <strong className="text-ink">3× daily cloud</strong>
          <p className="mt-1">YT + IG + TT public via GitHub Actions.</p>
        </li>
      </ul>
    </main>
  );
}

