import { spawn } from "child_process";
import fs from "fs";
import path from "path";
import { pipelinePython, pipelineRoot } from "./paths";

export type JobState = {
  id: string;
  topicId: string;
  status: "queued" | "running" | "done" | "error";
  startedAt: string;
  finishedAt?: string;
  logTail: string;
  error?: string;
};

const jobs = new Map<string, JobState>();

export function listJobs(): JobState[] {
  return Array.from(jobs.values()).sort((a, b) =>
    a.startedAt < b.startedAt ? 1 : -1
  );
}

export function getJob(id: string): JobState | undefined {
  return jobs.get(id);
}

export function startPipelineJob(topicId: string): JobState {
  const id = `job_${Date.now()}`;
  const root = pipelineRoot();
  const python = pipelinePython();
  const logDir = path.join(root, "out");
  fs.mkdirSync(logDir, { recursive: true });
  const logFile = path.join(logDir, `web_job_${id}.log`);

  const state: JobState = {
    id,
    topicId,
    status: "running",
    startedAt: new Date().toISOString(),
    logTail: "",
  };
  jobs.set(id, state);

  const child = spawn(
    python,
    ["src/run_pipeline.py", "--topic-id", topicId],
    {
      cwd: root,
      env: {
        ...process.env,
        ESPEAK_DATA_PATH: "C:\\espeak-ng-data",
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
      },
      windowsHide: true,
    }
  );

  const stream = fs.createWriteStream(logFile, { flags: "a" });
  const append = (buf: Buffer) => {
    const text = buf.toString("utf8");
    stream.write(text);
    state.logTail = (state.logTail + text).slice(-4000);
  };
  child.stdout?.on("data", append);
  child.stderr?.on("data", append);
  child.on("close", (code) => {
    stream.end();
    state.finishedAt = new Date().toISOString();
    if (code === 0) {
      state.status = "done";
    } else {
      state.status = "error";
      state.error = `exit ${code}`;
    }
  });
  child.on("error", (err) => {
    stream.end();
    state.status = "error";
    state.error = String(err);
    state.finishedAt = new Date().toISOString();
  });

  return state;
}

