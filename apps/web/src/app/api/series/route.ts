import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { prisma } from "@/lib/db";

function slugify(text: string) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60) || "series";
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const series = await prisma.series.findMany({
    include: { _count: { select: { episodes: true } } },
    orderBy: { createdAt: "desc" },
  });
  return NextResponse.json({ series });
}

export async function POST(req: Request) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const body = await req.json().catch(() => ({}));
  const title = String(body.title || "").trim();
  if (!title) {
    return NextResponse.json({ error: "title required" }, { status: 400 });
  }
  const org = await prisma.org.findFirst();
  if (!org) {
    return NextResponse.json({ error: "No org — run seed" }, { status: 500 });
  }
  let slug = slugify(title);
  const exists = await prisma.series.findUnique({ where: { slug } });
  if (exists) slug = `${slug}-${Date.now().toString(36)}`;

  const series = await prisma.series.create({
    data: {
      orgId: org.id,
      title,
      slug,
      niche: String(body.niche || "American history"),
      description: String(body.description || ""),
      language: "en",
    },
  });
  return NextResponse.json({ series }, { status: 201 });
}

