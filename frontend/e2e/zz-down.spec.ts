import { execSync, spawn } from "node:child_process";
import path from "node:path";
import { expect, test } from "@playwright/test";

const backend = path.resolve("..", "backend");
const python = path.join(backend, ".venv", "Scripts", "python.exe");

test("stopping the API shows the record-service message", async ({ page }) => {
  const pid = listeningPid(8000);
  expect(pid, "an API should be listening on port 8000 before this test").not.toBeNull();
  execSync(`taskkill /F /PID ${pid}`);
  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("alert")).toContainText("The record service is not running", { timeout: 15000 });
    await expect(page.getByRole("alert")).toContainText(".\\scripts\\dev.ps1");
  } finally {
    const child = spawn(python, ["-m", "uvicorn", "app.main:app", "--port", "8000"], {
      cwd: backend,
      detached: true,
      stdio: "ignore",
      env: {
        ...process.env,
        RPC_URL: process.env.RPC_URL || "http://127.0.0.1:8545",
        DEPLOYMENT_PATH: process.env.DEPLOYMENT_PATH || path.join(backend, "chain", "deployment.json"),
        ORACLE_PRIVATE_KEY: process.env.ORACLE_PRIVATE_KEY || "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
      },
    });
    child.unref();
  }
});

function listeningPid(port: number): number | null {
  const output = execSync("netstat -ano -p tcp", { encoding: "utf8" });
  const match = output.match(new RegExp(`(?:127\\.0\\.0\\.1|0\\.0\\.0\\.0):${port}\\s+\\S+\\s+LISTENING\\s+(\\d+)`));
  return match ? Number(match[1]) : null;
}
