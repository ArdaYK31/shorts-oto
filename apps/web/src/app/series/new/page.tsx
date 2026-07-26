"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppHeader } from "@/components/AppHeader";

export default function NewSeriesPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [niche, setNiche] = useState("American history");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const res = await fetch("/api/series", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, niche, description }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.error || "Failed");
      return;
    }
    router.push(`/series/${data.series.slug}`);
  }

  return (
    <main className="mx-auto max-w-3xl px-5 py-8">
      <AppHeader active="/series" />
      <form onSubmit={onSubmit} className="card p-6">
        <h2 className="font-display text-2xl font-semibold">Create series</h2>
        <p className="mb-6 text-sm text-muted">Content language locked to English.</p>
        <label className="mb-4 block text-sm font-semibold">
          Title
          <input
            className="mt-2 w-full border border-line bg-wash px-3 py-2"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </label>
        <label className="mb-4 block text-sm font-semibold">
          Niche
          <input
            className="mt-2 w-full border border-line bg-wash px-3 py-2"
            value={niche}
            onChange={(e) => setNiche(e.target.value)}
          />
        </label>
        <label className="mb-4 block text-sm font-semibold">
          Description
          <textarea
            className="mt-2 w-full border border-line bg-wash px-3 py-2"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        {error && <p className="mb-3 text-sm text-copper-deep">{error}</p>}
        <button type="submit" className="btn btn-primary">
          Create
        </button>
      </form>
    </main>
  );
}

