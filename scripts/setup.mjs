// One-time setup: backend venv + deps, frontend deps, seed the demo DB.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const run = (cmd, args, cwd) => {
  console.log(`\n> ${cmd} ${args.join(" ")}  (${path.relative(root, cwd) || "."})`);
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit", shell: process.platform === "win32" });
  if (r.status !== 0) process.exit(r.status ?? 1);
};

const backend = path.join(root, "backend");
if (!existsSync(path.join(backend, ".venv"))) {
  run(process.platform === "win32" ? "python" : "python3", ["-m", "venv", ".venv"], backend);
}
run("node", ["scripts/py.mjs", "-m", "pip", "install", "-q", "-r", "requirements.txt"], root);
run("npm", ["install"], root);
run("npm", ["install"], path.join(root, "frontend"));
run("node", ["scripts/py.mjs", "-m", "app.seed"], root);
console.log("\nSetup complete. Start with: npm run dev");
