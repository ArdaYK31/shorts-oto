import fs from "fs";
import path from "path";
import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { pipelineRoot } from "@/lib/paths";
import { Readable } from "stream";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ name: string }> }
) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { name } = await ctx.params;
  if (!/^[\w.-]+\.mp4$/i.test(name)) {
    return NextResponse.json({ error: "Invalid name" }, { status: 400 });
  }
  const filePath = path.join(pipelineRoot(), "out", name);
  if (!fs.existsSync(filePath)) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const stat = fs.statSync(filePath);
  const nodeStream = fs.createReadStream(filePath);
  const webStream = Readable.toWeb(nodeStream) as unknown as ReadableStream;
  return new NextResponse(webStream, {
    headers: {
      "Content-Type": "video/mp4",
      "Content-Length": String(stat.size),
      "Accept-Ranges": "bytes",
      "Cache-Control": "private, max-age=60",
    },
  });
}

