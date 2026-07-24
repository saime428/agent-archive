import { cp, mkdir, rm, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const source = resolve(repository, "frontend/dist");
const staticRoot = resolve(repository, "src/agent/web/static");
const target = resolve(staticRoot, "preview");

if (dirname(target) !== staticRoot || !target.endsWith("preview")) {
  throw new Error(`Refusing unsafe preview target: ${target}`);
}

if (!(await stat(resolve(source, "index.html"))).isFile()) {
  throw new Error("frontend/dist/index.html is missing. Run the build first.");
}

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
await cp(source, target, { recursive: true });
