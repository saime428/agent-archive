import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { access, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

const TEST_FILE = fileURLToPath(import.meta.url);
const FRONTEND_ROOT = resolve(dirname(TEST_FILE), "..");
const REPOSITORY = resolve(FRONTEND_ROOT, "..");
const WRAPPER = resolve(dirname(TEST_FILE), "start-served-workbench.mjs");
const FAKE_FLAG = "--fake-agent";
const WRAPPER_PREFIXES = ["agent-served-workspace-", "agent-served-home-"];

function argumentValue(args, name) {
  const index = args.indexOf(name);
  if (index < 0 || index + 1 >= args.length) throw new Error(`Missing ${name}.`);
  return args[index + 1];
}

async function listen(server, port) {
  await new Promise((resolveListen, reject) => {
    server.once("error", reject);
    server.listen({ host: "127.0.0.1", port, exclusive: true }, resolveListen);
  });
}

async function closeServer(server) {
  if (!server.listening) return;
  await new Promise((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
}

async function runFakeAgent() {
  const mode = process.env.FAKE_AGENT_MODE || "hold";
  const args = process.argv.slice(process.argv.indexOf(FAKE_FLAG) + 1);
  const requestedPort = Number(argumentValue(args, "--port"));
  const workspace = argumentValue(args, "--cwd");
  const home = process.env.HOME || "";
  const userProfile = process.env.USERPROFILE || "";
  const stateFile = process.env.FAKE_STATE_FILE;
  if (!stateFile) throw new Error("FAKE_STATE_FILE is required.");

  await writeFile(
    stateFile,
    JSON.stringify({
      pid: process.pid,
      workspace,
      home,
      userProfile,
      sentinelVisible: existsSync(join(home, "sentinel.txt")),
    }),
    "utf8",
  );

  if (mode === "exit") process.exit(7);

  const server = createServer((socket) => socket.end());
  await listen(server, mode === "fallback" ? requestedPort + 1 : requestedPort);
  if (mode === "fallback") {
    process.stderr.write("Port 4174 is bu");
    await delay(15);
    process.stderr.write("sy; trying 4175.\n");
  } else {
    process.stdout.write("Fake Agent Workbench ready.\n");
  }
  await new Promise(() => {});
}

async function waitFor(predicate, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await delay(25);
  }
  throw new Error(`Condition was not met within ${timeoutMs} ms.`);
}

async function fileExists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

async function readJsonWhenReady(path) {
  await waitFor(() => fileExists(path));
  return JSON.parse(await readFile(path, "utf8"));
}

async function makeScratch() {
  const root = await mkdtemp(join(tmpdir(), "agent-served-wrapper-test-"));
  const parentHome = join(root, "parent-home");
  await mkdir(parentHome);
  await writeFile(join(parentHome, "sentinel.txt"), "must stay hidden", "utf8");
  return {
    root,
    parentHome,
    controlDir: join(root, "control"),
    stateFile: join(root, "fake-state.json"),
  };
}

async function removeScratch(root) {
  const resolved = resolve(root);
  if (dirname(resolved) !== resolve(tmpdir()) || !basename(resolved).startsWith("agent-served-wrapper-test-")) {
    throw new Error(`Refusing unsafe test cleanup: ${resolved}`);
  }
  await rm(resolved, { recursive: true, force: true });
}

function startWrapper(scratch, mode) {
  const startedAt = Date.now();
  const child = spawn(process.execPath, [WRAPPER], {
    cwd: REPOSITORY,
    env: {
      ...process.env,
      AGENT_EXE: process.execPath,
      AGENT_EXE_ARGS_JSON: JSON.stringify([TEST_FILE, FAKE_FLAG]),
      AGENT_SERVED_CONTROL_DIR: scratch.controlDir,
      FAKE_AGENT_MODE: mode,
      FAKE_STATE_FILE: scratch.stateFile,
      HOME: scratch.parentHome,
      USERPROFILE: scratch.parentHome,
      TEMP: scratch.root,
      TMP: scratch.root,
      TMPDIR: scratch.root,
    },
    shell: false,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  const result = new Promise((resolveResult) => {
    child.once("close", (code, signal) => {
      resolveResult({ code, signal, stdout, stderr, elapsedMs: Date.now() - startedAt });
    });
  });
  return { child, result };
}

async function stopWrapper(run) {
  if (run.child.exitCode === null && run.child.signalCode === null) run.child.kill("SIGKILL");
  await run.result;
}

async function assertNoWrapperTemps(root) {
  const names = await readdir(root);
  assert.deepEqual(
    names.filter((name) => WRAPPER_PREFIXES.some((prefix) => name.startsWith(prefix))),
    [],
  );
}

async function portIsFree(port) {
  const server = createServer();
  try {
    await listen(server, port);
    return true;
  } catch {
    return false;
  } finally {
    await closeServer(server);
  }
}

async function assertPortsFree() {
  assert.equal(await portIsFree(4174), true, "port 4174 is still occupied");
  assert.equal(await portIsFree(4175), true, "port 4175 is still occupied");
}

if (process.argv.includes(FAKE_FLAG)) {
  await runFakeAgent();
} else {
  test("fails fast when port 4174 is occupied", async () => {
    const scratch = await makeScratch();
    const blocker = createServer();
    let run;
    try {
      await listen(blocker, 4174);
      run = startWrapper(scratch, "hold");
      const result = await run.result;
      assert.equal(result.code, 1, result.stderr);
      assert.match(result.stderr, /4174.*already in use/i);
      assert.ok(result.elapsedMs < 2_000, `occupied-port failure took ${result.elapsedMs} ms`);
      assert.equal(await fileExists(scratch.stateFile), false, "fake agent should not start");
      await assertNoWrapperTemps(scratch.root);
    } finally {
      if (run) await stopWrapper(run);
      await closeServer(blocker);
      await assertPortsFree();
      await removeScratch(scratch.root);
    }
  });

  test("detects a fallback warning split across stderr chunks", async () => {
    const scratch = await makeScratch();
    const run = startWrapper(scratch, "fallback");
    try {
      const result = await run.result;
      assert.equal(result.code, 1, result.stderr);
      assert.match(result.stderr, /Port 4174 is busy; trying 4175\./);
      assert.match(result.stderr, /refusing port fallback/i);
      await assertNoWrapperTemps(scratch.root);
      await assertPortsFree();
    } finally {
      await stopWrapper(run);
      await removeScratch(scratch.root);
    }
  });

  test("propagates a non-zero agent exit code", async () => {
    const scratch = await makeScratch();
    const run = startWrapper(scratch, "exit");
    try {
      const result = await run.result;
      assert.equal(result.code, 7, result.stderr);
      await assertNoWrapperTemps(scratch.root);
      await assertPortsFree();
    } finally {
      await stopWrapper(run);
      await removeScratch(scratch.root);
    }
  });

  test("isolates home and cleans the child through the served stop request", async () => {
    const scratch = await makeScratch();
    const run = startWrapper(scratch, "hold");
    try {
      const state = await readJsonWhenReady(scratch.stateFile);
      assert.equal(state.home, state.userProfile);
      assert.notEqual(resolve(state.home), resolve(scratch.parentHome));
      assert.equal(state.sentinelVisible, false);
      assert.equal(await fileExists(state.workspace), true);
      assert.equal(await fileExists(state.home), true);

      await waitFor(() => fileExists(scratch.controlDir));
      await writeFile(join(scratch.controlDir, "stop"), "stop", "utf8");
      await waitFor(() => fileExists(join(scratch.controlDir, "done")));
      const result = await run.result;

      assert.equal(result.code, 0, result.stderr);
      assert.equal(await fileExists(state.workspace), false);
      assert.equal(await fileExists(state.home), false);
      assert.throws(() => process.kill(state.pid, 0));
      await assertNoWrapperTemps(scratch.root);
      await assertPortsFree();
    } finally {
      await stopWrapper(run);
      await removeScratch(scratch.root);
    }
  });

  test(
    "forwards SIGTERM and cleans the child on POSIX",
    { skip: process.platform === "win32" },
    async () => {
      const scratch = await makeScratch();
      const run = startWrapper(scratch, "hold");
      try {
        const state = await readJsonWhenReady(scratch.stateFile);
        assert.equal(run.child.kill("SIGTERM"), true);
        const result = await run.result;

        assert.equal(result.code, 143, result.stderr);
        assert.equal(await fileExists(state.workspace), false);
        assert.equal(await fileExists(state.home), false);
        assert.throws(() => process.kill(state.pid, 0));
        await assertPortsFree();
      } finally {
        await stopWrapper(run);
        await removeScratch(scratch.root);
      }
    },
  );
}
