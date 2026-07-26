import fs from "fs";
import path from "path";

export function pipelineRoot(): string {
  return (
    process.env.PIPELINE_ROOT ||
    path.resolve(process.cwd(), "..", "..")
  );
}

export function pipelinePython(): string {
  return (
    process.env.PIPELINE_PYTHON ||
    path.join(pipelineRoot(), ".venv312", "Scripts", "python.exe")
  );
}

export function readTextIfExists(p: string | null | undefined): string | null {
  if (!p) return null;
  try {
    if (!fs.existsSync(p)) return null;
    return fs.readFileSync(p, "utf8");
  } catch {
    return null;
  }
}

export function resolvePipelinePaths(stem: string) {
  const root = pipelineRoot();
  return {
    scriptPath: path.join(root, "scripts", `${stem}.txt`),
    audioPath: path.join(root, "audio", `${stem}.mp3`),
    videoPath: path.join(root, "out", `${stem}.mp4`),
    seoPath: path.join(root, "seo", `${stem}.seo.json`),
    metaPath: path.join(root, "scripts", `${stem}.meta.json`),
  };
}

