import "dotenv/config";
import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";
import fs from "fs";
import path from "path";

const prisma = new PrismaClient();

function rootFromEnv() {
  return (
    process.env.PIPELINE_ROOT ||
    path.resolve(__dirname, "..", "..", "..", "..")
  );
}

async function main() {
  const root = rootFromEnv();
  const password = process.env.AUTH_PASSWORD || "atelier";
  const hash = await bcrypt.hash(password, 10);

  await prisma.episode.deleteMany();
  await prisma.series.deleteMany();
  await prisma.user.deleteMany();
  await prisma.org.deleteMany();

  const org = await prisma.org.create({
    data: { name: "Agency Internal" },
  });

  await prisma.user.create({
    data: {
      email: "agency@atelier.local",
      name: "Atelier Operator",
      passwordHash: hash,
      orgId: org.id,
    },
  });

  const series = await prisma.series.create({
    data: {
      orgId: org.id,
      slug: "american-history-vault",
      title: "American History Vault",
      niche: "American history",
      language: "en",
      description:
        "Quiet power. Loud hooks. Archive imagery, cinematic grade, word-level captions. Every episode needs human approval.",
      postsPerWeek: 5,
    },
  });

  const stem = "ulysses-grant-nobody";
  const scriptPath = path.join(root, "scripts", `${stem}.txt`);
  const videoPath = path.join(root, "out", `${stem}.mp4`);
  const seoPath = path.join(root, "seo", `${stem}.seo.json`);
  const scriptText = fs.existsSync(scriptPath)
    ? fs.readFileSync(scriptPath, "utf8")
    : null;
  let title = "The Nobody Who Saved America: Ulysses S. Grant";
  let seoJson: string | null = null;
  if (fs.existsSync(seoPath)) {
    seoJson = fs.readFileSync(seoPath, "utf8");
    try {
      title = JSON.parse(seoJson).title || title;
    } catch {
      /* ignore */
    }
  }

  await prisma.episode.create({
    data: {
      seriesId: series.id,
      stem,
      title,
      topic:
        "Ulysses S. Grant - failed shopkeeper turned Civil War general who forced Lee's surrender",
      status: fs.existsSync(videoPath) ? "IN_REVIEW" : "DRAFT",
      scriptPath,
      audioPath: path.join(root, "audio", `${stem}.mp3`),
      videoPath: fs.existsSync(videoPath) ? videoPath : null,
      seoPath: fs.existsSync(seoPath) ? seoPath : null,
      scriptText,
      seoJson,
    },
  });

  console.log("Seeded org + American History Vault + Grant episode");
  console.log(`Login password: ${password}`);
  console.log(`PIPELINE_ROOT: ${root}`);
  console.log(`Video exists: ${fs.existsSync(videoPath)}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

