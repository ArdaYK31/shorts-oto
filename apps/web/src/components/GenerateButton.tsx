"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function GenerateButton({
  seriesId,
  defaultTopicId = "ulysses-grant-nobody",
}: {
  seriesId: string;
  defaultTopicId?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setInfo(null);
    const res = await fetch("/api/pipeline/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seriesId, topicId: defaultTopicId }),
    });
    const data = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok) {
      setInfo(data.error || "Failed to start job");
      return;
    }
    setInfo(`Job ${data.job?.id} started for topic ${defaultTopicId}`);
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-2">
      <button type="button" className="btn btn-primary" disabled={busy} onClick={run}>
        {busy ? "Starting…" : "Generate next episode"}
      </button>
      {info && <p className="text-sm text-muted">{info}</p>}
    </div>
  );
}

