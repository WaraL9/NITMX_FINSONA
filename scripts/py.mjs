// Run the backend venv's Python with the given args, from backend/.
// Usage: node scripts/py.mjs -m pytest -q
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "backend");
const candidates = [
  path.join(backend, ".venv", "Scripts", "python.exe"),
  path.join(backend, ".venv", "bin", "python"),
];
const python = candidates.find(existsSync);
if (!python) {
  console.error("backend/.venv not found. Run `npm run setup` first.");
  process.exit(1);
}
const r = spawnSync(python, process.argv.slice(2), { cwd: backend, stdio: "inherit" });
process.exit(r.status ?? 1);
