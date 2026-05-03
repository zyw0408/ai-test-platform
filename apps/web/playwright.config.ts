import { defineConfig, devices } from "@playwright/test";

const webPort = 3101;
const backendPort = 18000;
const baseURL = `http://127.0.0.1:${webPort}`;
const backendURL = `http://127.0.0.1:${backendPort}`;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: `..\\..\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: "..\\..\\services\\ai-service",
      url: `${backendURL}/health`,
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        AI_SERVICE_STORAGE_DIR: ".e2e/data",
        AI_SERVICE_ARTIFACTS_DIR: ".e2e/artifacts",
        AI_SERVICE_DB_PATH: ".e2e/data/platform.db",
        AI_SERVICE_DATABASE_URL: "",
        AI_SERVICE_AUTH_SECRET: "e2e-secret",
        AI_SERVICE_REDIS_ENABLED: "false",
        AI_SERVICE_DEFAULT_ADMIN_USERNAME: "admin",
        AI_SERVICE_DEFAULT_ADMIN_PASSWORD: "123456",
      },
    },
    {
      command: `npm run dev -- --hostname 127.0.0.1 --port ${webPort}`,
      cwd: ".",
      url: baseURL,
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        PLATFORM_API_URL: backendURL,
        NEXT_PUBLIC_PLATFORM_API_URL: backendURL,
      },
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
