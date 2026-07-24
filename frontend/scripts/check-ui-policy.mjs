import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src/", import.meta.url));
const allowedExtensions = new Set([".ts", ".tsx"]);
const violations = [];

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await walk(path));
    else if (allowedExtensions.has(extname(entry.name)) && !entry.name.includes(".test.")) files.push(path);
  }
  return files;
}

for (const path of await walk(root)) {
  const source = await readFile(path, "utf8");
  const name = relative(root, path);
  if (/<svg\b/i.test(source)) violations.push(`${name}: 禁止手写 SVG`);
  if (/import\s*\*\s*as\s+\w+\s+from\s+["']lucide-react["']/.test(source)) {
    violations.push(`${name}: 禁止动态导入 Lucide 全量图标表`);
  }
  for (const match of source.matchAll(/from\s+["']([^"']+)["']/g)) {
    const dependency = match[1];
    if (/(icon|heroicon|phosphor|fontawesome)/i.test(dependency) && dependency !== "lucide-react") {
      violations.push(`${name}: 禁止第二图标源 ${dependency}`);
    }
  }
  if (/\p{Extended_Pictographic}|[✓✔✕✖⚠⚙⏎➜➝➞]/u.test(source)) {
    violations.push(`${name}: 产品源码包含 emoji 或 Unicode 图形符号`);
  }
}

if (violations.length) {
  console.error(violations.join("\n"));
  process.exitCode = 1;
} else {
  console.log("UI policy check passed: Lucide-only icons and no product emoji.");
}
