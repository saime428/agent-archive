import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const HOST = "127.0.0.1";
const PORT = 4174;
const FALLBACK_WARNING = "Port 4174 is busy; trying 4175.";
const WORKSPACE_PREFIX = "agent-served-workspace-";
const HOME_PREFIX = "agent-served-home-";
const REPOSITORY = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CONTROL_DIR = resolve(
  REPOSITORY,
  process.env.AGENT_SERVED_CONTROL_DIR || "frontend/test-results/served-control",
);
const STOP_FILE = join(CONTROL_DIR, "stop");
const DONE_FILE = join(CONTROL_DIR, "done");

function samePath(left, right) {
  return process.platform === "win32"
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}

async function removeOwnedTemp(path, prefix) {
  if (!path) return;
  const target = resolve(path);
  if (!samePath(dirname(target), resolve(tmpdir())) || !basename(target).startsWith(prefix)) {
    throw new Error(`Refusing unsafe served-workbench cleanup: ${target}`);
  }
  await rm(target, { recursive: true, force: true });
}

async function fileExists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

async function assertPortAvailable() {
  const probe = createServer();
  try {
    await new Promise((resolveListen, reject) => {
      probe.once("error", reject);
      probe.listen({ host: HOST, port: PORT, exclusive: true }, resolveListen);
    });
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "EADDRINUSE") {
      throw new Error(`Port ${PORT} is already in use; refusing to start a fallback server.`);
    }
    throw error;
  } finally {
    if (probe.listening) {
      await new Promise((resolveClose, reject) => {
        probe.close((error) => (error ? reject(error) : resolveClose()));
      });
    }
  }
}

function executablePrefixArgs() {
  const raw = process.env.AGENT_EXE_ARGS_JSON;
  if (!raw) return [];
  let value;
  try {
    value = JSON.parse(raw);
  } catch (error) {
    throw new Error(`AGENT_EXE_ARGS_JSON must be valid JSON: ${error.message}`);
  }
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error("AGENT_EXE_ARGS_JSON must be an array of strings.");
  }
  return value;
}

function startControlWatcher(finish) {
  let checking = false;
  const timer = setInterval(async () => {
    if (checking) return;
    checking = true;
    try {
      if (await fileExists(STOP_FILE)) finish({ kind: "control" });
    } finally {
      checking = false;
    }
  }, 25);
  return timer;
}

async function terminateChild(child, closed) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  const stopped = await Promise.race([closed.then(() => true), delay(2_000).then(() => false)]);
  if (!stopped && child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await closed;
  }
}

async function run() {
  await assertPortAvailable();
  const prefixArgs = executablePrefixArgs();
  const executable = process.env.AGENT_EXE || "agent";
  await mkdir(CONTROL_DIR, { recursive: true });
  await rm(STOP_FILE, { force: true });
  await rm(DONE_FILE, { force: true });

  let workspace;
  let temporaryHome;
  let child;
  let controlWatcher;
  let controlRequested = false;
  let exitCode = 1;
  let finish;
  let onSigint;
  let onSigterm;

  try {
    workspace = await mkdtemp(join(tmpdir(), WORKSPACE_PREFIX));
    temporaryHome = await mkdtemp(join(tmpdir(), HOME_PREFIX));
    child = spawn(
      executable,
      [
        ...prefixArgs,
        "start",
        "--cwd",
        workspace,
        "--host",
        HOST,
        "--port",
        String(PORT),
        "--no-open-browser",
      ],
      {
        cwd: REPOSITORY,
        env: { ...process.env, HOME: temporaryHome, USERPROFILE: temporaryHome },
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      },
    );

    let resolveClosed;
    const closed = new Promise((resolveChildClosed) => {
      resolveClosed = resolveChildClosed;
    });
    const outcome = new Promise((resolveOutcome) => {
      let settled = false;
      finish = (value) => {
        if (settled) return;
        settled = true;
        resolveOutcome(value);
      };
    });

    child.once("error", (error) => finish({ kind: "error", error }));
    child.once("close", (code, signal) => {
      resolveClosed();
      finish({ kind: "exit", code, signal });
    });

    const forward = (stream, destination) => {
      let rolling = "";
      stream.on("data", (chunk) => {
        destination.write(chunk);
        rolling = (rolling + chunk.toString("utf8")).slice(-FALLBACK_WARNING.length * 2);
        if (rolling.includes(FALLBACK_WARNING)) finish({ kind: "fallback" });
      });
    };
    forward(child.stdout, process.stdout);
    forward(child.stderr, process.stderr);

    controlWatcher = startControlWatcher(finish);
    onSigint = () => finish({ kind: "signal", signal: "SIGINT" });
    onSigterm = () => finish({ kind: "signal", signal: "SIGTERM" });
    process.once("SIGINT", onSigint);
    process.once("SIGTERM", onSigterm);

    const result = await outcome;
    controlRequested = result.kind === "control";
    if (result.kind === "exit") {
      exitCode = typeof result.code === "number" ? result.code : 1;
    } else {
      await terminateChild(child, closed);
      if (result.kind === "fallback") {
        process.stderr.write(`Refusing port fallback after detecting: ${FALLBACK_WARNING}\n`);
        exitCode = 1;
      } else if (result.kind === "error") {
        process.stderr.write(`Could not start Agent Workbench: ${result.error.message}\n`);
        exitCode = 1;
      } else if (result.kind === "signal") {
        exitCode = result.signal === "SIGINT" ? 130 : 143;
      } else {
        exitCode = 0;
      }
    }
  } finally {
    if (controlWatcher) clearInterval(controlWatcher);
    if (onSigint) process.removeListener("SIGINT", onSigint);
    if (onSigterm) process.removeListener("SIGTERM", onSigterm);
    await removeOwnedTemp(workspace, WORKSPACE_PREFIX);
    await removeOwnedTemp(temporaryHome, HOME_PREFIX);
    if (controlRequested) await writeFile(DONE_FILE, "done\n", "utf8");
  }
  return exitCode;
}

try {
  process.exitCode = await run();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
