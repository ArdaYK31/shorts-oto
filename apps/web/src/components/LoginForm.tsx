"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function LoginForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      setError("Wrong password");
      return;
    }
    router.push("/series");
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="card mx-auto max-w-md p-8">
      <h1 className="font-display text-3xl font-semibold">Atelier</h1>
      <p className="mt-2 text-muted">Agency gate — Series Autopilot</p>
      <label className="mt-6 block text-sm font-semibold text-muted">
        Password
        <input
          type="password"
          className="mt-2 w-full border border-line bg-wash px-3 py-2 text-ink outline-none focus:border-copper"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
      </label>
      {error && <p className="mt-2 text-sm text-copper-deep">{error}</p>}
      <button type="submit" className="btn btn-primary mt-6 w-full">
        Enter
      </button>
      <p className="mt-4 text-xs text-muted">
        Default password documented in README (<code>atelier</code>).
      </p>
    </form>
  );
}

