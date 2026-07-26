import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { startPipelineJob, listJobs, getJob } from "@/lib/jobs";
import { prisma } from "@/lib/db";
import { resolvePipelinePaths, readTextIfExists } from "@/lib/paths";

export async function GET(req: Request) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const url = new URL(req.url);
  const id = url.searchParams.get("id");
  if (id) {
    return NextResponse.json({ job: getJob(id) || null });
  }
  return NextResponse.json({ jobs: listJobs() });
}

export async function POST(req: Request) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const body = await req.json().catch(() => ({}));
  const topicId = String(body.topicId || "ulysses-grant-nobody");
  const seriesId = String(body.seriesId || "");

  let series = seriesId
    ? await prisma.series.findUnique({ where: { id: seriesId } })
    : await prisma.series.findFirst();
  if (!series) {
    return NextResponse.json({ error: "No series found" }, { status: 400 });
  }

  const paths = resolvePipelinePaths(topicId);
  const episode = await prisma.episode.upsert({
    where: {
      seriesId_stem: { seriesId: series.id, stem: topicId },
    },
    create: {
      seriesId: series.id,
      stem: topicId,
      title: topicId,
      status: "GENERATING",
      scriptPath: paths.scriptPath,
      audioPath: paths.audioPath,
      videoPath: paths.videoPath,
      seoPath: paths.seoPath,
    },
    update: { status: "GENERATING" },
  });

  const job = startPipelineJob(topicId);

  // Best-effort: when job finishes, refresh episode from disk (poller-lite via setTimeout)
  const poll = setInterval(async () => {
    const j = getJob(job.id);
    if (!j || j.status === "running" || j.status === "queued") return;
    clearInterval(poll);
    const scriptText = readTextIfExists(paths.scriptPath);
    const seoJson = readTextIfExists(paths.seoPath);
    let title = episode.title;
    if (seoJson) {
      try {
        title = JSON.parse(seoJson).title || title;
      } catch {
        /* ignore */
      }
    }
    await prisma.episode.update({
      where: { id: episode.id },
      data: {
        status: j.status === "done" ? "IN_REVIEW" : "DRAFT",
        scriptText,
        seoJson,
        title,
        videoPath: paths.videoPath,
        scriptPath: paths.scriptPath,
        seoPath: paths.seoPath,
        audioPath: paths.audioPath,
      },
    });
  }, 5000);

  return NextResponse.json({ job, episode }, { status: 202 });
}

