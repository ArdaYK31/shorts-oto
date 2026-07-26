import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const episodes = await prisma.episode.findMany({
    where: { status: { in: ["IN_REVIEW", "GENERATING", "DRAFT"] } },
    include: { series: true },
    orderBy: { updatedAt: "desc" },
  });
  return NextResponse.json({ episodes });
}

