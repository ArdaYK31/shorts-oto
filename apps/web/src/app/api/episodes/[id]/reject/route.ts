import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> }
) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await ctx.params;
  const body = await req.json().catch(() => ({}));
  const episode = await prisma.episode.update({
    where: { id },
    data: {
      status: "REJECTED",
      rejectionNote: String(body.note || ""),
    },
  });
  return NextResponse.json({ episode });
}

