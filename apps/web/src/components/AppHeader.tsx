import Link from "next/link";

const links = [
  { href: "/series", label: "Series" },
  { href: "/queue", label: "Queue" },
  { href: "/settings", label: "Settings" },
];

export function AppHeader({ active }: { active?: string }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div>
        <Link href="/" className="font-display text-3xl font-semibold tracking-tight text-ink md:text-4xl">
          Atelier
        </Link>
        <p className="mt-2 text-[0.95rem] text-muted">
          Series Autopilot — review before the world sees it.
        </p>
      </div>
      <nav className="flex flex-wrap items-center gap-1">
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={`px-3 py-2 text-sm font-semibold ${
              active === l.href
                ? "bg-paper text-ink shadow-[0_1px_0_var(--line)]"
                : "text-muted"
            }`}
          >
            {l.label}
          </Link>
        ))}
        <Link href="/series/new" className="btn btn-primary ml-2">
          New series
        </Link>
      </nav>
    </header>
  );
}

