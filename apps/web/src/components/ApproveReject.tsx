"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function ApproveReject({ episodeId }: { episodeId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function act(action: "approve" | "reject") {
    setBusy(true);
    setMsg(null);
    const note =
      action === "reject"
        ? window.prompt("Rejection note (optional):") || ""
        : undefined;
    const res = await fetch(`/api/episodes/${episodeId}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    setBusy(false);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setMsg(data.error || "Failed");
      return;
    }
    setMsg(action === "approve" ? "Approved — ready for manual YouTube upload." : "Rejected.");
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <button
          type="button"
          className="btn btn-sage flex-1"
          disabled={busy}
          onClick={() => act("approve")}
        >
          Approve
        </button>
        <button
          type="button"
          className="btn flex-1 text-copper-deep"
          disabled={busy}
          onClick={() => act("reject")}
        >
          Reject
        </button>
      </div>
      {msg && <p className="text-sm text-muted">{msg}</p>}
    </div>
  );
}

