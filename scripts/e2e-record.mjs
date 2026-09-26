// E16-04 backup recording: headed, slowed-down demo run; the video lands in e2e/results/.
import { spawnSync } from "node:child_process";

const r = spawnSync("npx", ["playwright", "test", "-c", "e2e", "--headed", "demo.spec.ts"], {
  stdio: "inherit",
  shell: process.platform === "win32",
  env: { ...process.env, E2E_SLOW: "1" },
});
process.exit(r.status ?? 1);
