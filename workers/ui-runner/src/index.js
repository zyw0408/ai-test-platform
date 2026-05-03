import fs from "node:fs";
import path from "node:path";
import { chromium, firefox, webkit } from "playwright";

const payloadPath = process.argv[2];

if (!payloadPath) {
  console.error("Usage: node src/index.js <run-payload.json>");
  process.exit(1);
}

const browserFactories = {
  chromium,
  firefox,
  webkit,
};

function sanitizeFileName(value) {
  return String(value || "capture")
    .trim()
    .replace(/[^a-zA-Z0-9-_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48) || "capture";
}

function resolveUrl(target, baseUrl) {
  if (!target) return baseUrl || "about:blank";
  try {
    return new URL(target, baseUrl || undefined).toString();
  } catch {
    return String(target);
  }
}

function pushArtifact(artifacts, type, label, filePath) {
  artifacts.push({
    type,
    label,
    path: path.resolve(filePath),
  });
}

function parsePayload(rawValue) {
  if (!rawValue || typeof rawValue !== "object" || Array.isArray(rawValue)) {
    return {};
  }
  return rawValue;
}

async function runAction(page, action, state) {
  const rawType = String(action?.type || action?.action || "").trim();
  const type = rawType || "noop";
  const timeout = Number(action?.timeoutMs || state.timeoutMs || 30000);
  const selector = typeof action?.selector === "string" ? action.selector : "";
  const locator = selector ? page.locator(selector) : null;
  const name = typeof action?.name === "string" && action.name.trim() ? action.name.trim() : type;

  switch (type) {
    case "goto": {
      const url = resolveUrl(action?.url, state.startUrl);
      await page.goto(url, { waitUntil: action?.waitUntil || "load", timeout });
      state.logs.push(`goto ${url}`);
      return;
    }
    case "click": {
      if (!locator) throw new Error("click action requires selector");
      await locator.click({ timeout });
      state.logs.push(`click ${selector}`);
      return;
    }
    case "fill": {
      if (!locator) throw new Error("fill action requires selector");
      await locator.fill(String(action?.value ?? ""), { timeout });
      state.logs.push(`fill ${selector}`);
      return;
    }
    case "press": {
      const key = String(action?.key || "").trim();
      if (!key) throw new Error("press action requires key");
      if (locator) {
        await locator.press(key, { timeout });
        state.logs.push(`press ${key} on ${selector}`);
      } else {
        await page.keyboard.press(key);
        state.logs.push(`press ${key}`);
      }
      return;
    }
    case "waitForSelector": {
      if (!locator) throw new Error("waitForSelector action requires selector");
      await locator.waitFor({ state: action?.state || "visible", timeout });
      state.logs.push(`waitForSelector ${selector}`);
      return;
    }
    case "waitForTimeout": {
      const waitMs = Number(action?.ms || action?.timeoutMs || 500);
      await page.waitForTimeout(waitMs);
      state.logs.push(`waitForTimeout ${waitMs}ms`);
      return;
    }
    case "expectText": {
      if (!locator) throw new Error("expectText action requires selector");
      await locator.waitFor({ state: "visible", timeout });
      const text = await locator.textContent({ timeout });
      const expected = String(action?.text ?? "");
      if (!String(text || "").includes(expected)) {
        throw new Error(`expectText failed for ${selector}: expected to include "${expected}", got "${text || ""}"`);
      }
      state.logs.push(`expectText ${selector} includes "${expected}"`);
      return;
    }
    case "expectVisible": {
      if (!locator) throw new Error("expectVisible action requires selector");
      await locator.waitFor({ state: "visible", timeout });
      state.logs.push(`expectVisible ${selector}`);
      return;
    }
    case "expectUrl": {
      const currentUrl = page.url();
      const expected = String(action?.value || action?.url || "").trim();
      if (!expected) throw new Error("expectUrl action requires value");
      const mode = String(action?.match || "includes").trim();
      const matched = mode === "exact" ? currentUrl === expected : currentUrl.includes(expected);
      if (!matched) {
        throw new Error(`expectUrl failed: expected ${mode} "${expected}", got "${currentUrl}"`);
      }
      state.logs.push(`expectUrl ${mode} "${expected}"`);
      return;
    }
    case "screenshot": {
      const fileName = `${state.runId}-${sanitizeFileName(name)}.png`;
      const screenshotPath = path.join(state.outputDir, fileName);
      await page.screenshot({
        path: screenshotPath,
        fullPage: Boolean(action?.fullPage),
      });
      pushArtifact(state.artifacts, "screenshot", `Playwright screenshot: ${name}`, screenshotPath);
      state.logs.push(`screenshot ${fileName}`);
      return;
    }
    case "setContent": {
      const html = String(action?.html || "");
      await page.setContent(html, { timeout, waitUntil: "load" });
      state.logs.push(`setContent ${name}`);
      return;
    }
    case "noop": {
      state.logs.push("noop");
      return;
    }
    default:
      throw new Error(`Unsupported Playwright action: ${type}`);
  }
}

async function runActionWithResult(page, action, state, index) {
  const startedAt = Date.now();
  const actionType = String(action?.type || action?.action || "noop");
  const actionName = String(action?.name || actionType || `step-${index + 1}`);
  const actionSelector = String(action?.selector || "");
  const beforeUrl = page.url();
  try {
    await runAction(page, action, state);
    const durationMs = Date.now() - startedAt;
    const afterUrl = page.url();
    const result = {
      step: index + 1,
      type: actionType,
      name: actionName,
      selector: actionSelector,
      status: "passed",
      durationMs,
      beforeUrl,
      afterUrl,
    };

    if (state.screenshotEachStep) {
      const stepShot = path.join(state.outputDir, `${state.runId}-step-${String(index + 1).padStart(2, "0")}.png`);
      await page.screenshot({ path: stepShot, fullPage: true });
      pushArtifact(state.artifacts, "screenshot", `Playwright step ${index + 1} screenshot`, stepShot);
      result.screenshotPath = path.resolve(stepShot);
    }
    return result;
  } catch (error) {
    const durationMs = Date.now() - startedAt;
    const message = error instanceof Error ? error.message : String(error);
    return {
      step: index + 1,
      type: actionType,
      name: actionName,
      selector: actionSelector,
      status: "failed",
      durationMs,
      beforeUrl,
      afterUrl: page.url(),
      error: message,
    };
  }
}

async function main() {
  const absolutePath = path.resolve(payloadPath);
  const payload = parsePayload(JSON.parse(fs.readFileSync(absolutePath, "utf8")));
  const outputDir = path.resolve(payload.outputDir ?? "test-results");
  fs.mkdirSync(outputDir, { recursive: true });

  const runId = String(payload.runId || `ui-${Date.now()}`);
  const startUrl = String(payload.startUrl || "about:blank");
  const browserName = String(payload.browser || "chromium");
  const headless = payload.headless !== false;
  const timeoutMs = Number(payload.timeoutMs || 30000);
  const viewport = parsePayload(payload.viewport);
  const recordTrace = payload.recordTrace !== false;
  const screenshotOnCompletion = payload.screenshotOnCompletion !== false;
  const screenshotEachStep = payload.screenshotEachStep === true;
  const collectConsoleErrors = payload.collectConsoleErrors !== false;
  const collectFailedRequests = payload.collectFailedRequests !== false;
  const actions = Array.isArray(payload.actions) ? payload.actions : [];
  const reportPath = path.join(outputDir, `${runId}-report.json`);
  const tracePath = path.join(outputDir, `${runId}-trace.zip`);

  const state = {
    runId,
    outputDir,
    startUrl,
    timeoutMs,
    screenshotEachStep,
    logs: [`playwright worker booted (${browserName})`],
    artifacts: [],
    actionResults: [],
    consoleErrors: [],
    failedRequests: [],
  };

  let browser;
  let context;
  let page;

  try {
    const factory = browserFactories[browserName] || chromium;
    browser = await factory.launch({ headless });
    context = await browser.newContext({
      viewport: {
        width: Number(viewport.width || 1440),
        height: Number(viewport.height || 900),
      },
    });
    page = await context.newPage();

    if (collectConsoleErrors) {
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          state.consoleErrors.push({
            type: msg.type(),
            text: msg.text(),
            location: msg.location(),
          });
        }
      });
      page.on("pageerror", (error) => {
        state.consoleErrors.push({
          type: "pageerror",
          text: error?.message || String(error),
        });
      });
    }

    if (collectFailedRequests) {
      page.on("requestfailed", (req) => {
        state.failedRequests.push({
          url: req.url(),
          method: req.method(),
          resourceType: req.resourceType(),
          failure: req.failure(),
        });
      });
      page.on("response", (response) => {
        if (response.status() >= 400) {
          state.failedRequests.push({
            url: response.url(),
            method: response.request().method(),
            resourceType: response.request().resourceType(),
            status: response.status(),
            statusText: response.statusText(),
          });
        }
      });
    }

    if (recordTrace) {
      await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
      state.logs.push("trace recording started");
    }

    const firstActionType = String(actions[0]?.type || actions[0]?.action || "").trim();
    if (startUrl && firstActionType !== "goto") {
      await page.goto(startUrl, { waitUntil: "load", timeout: timeoutMs });
      state.logs.push(`goto ${startUrl}`);
    }

    let allPassed = true;
    for (let i = 0; i < actions.length; i += 1) {
      const action = actions[i];
      const actionResult = await runActionWithResult(page, action, state, i);
      state.actionResults.push(actionResult);
      if (actionResult.status !== "passed") {
        allPassed = false;
        state.logs.push(`step ${i + 1} failed: ${String(actionResult.error || "unknown error")}`);
        break;
      }
    }

    if (screenshotOnCompletion) {
      const finalShotPath = path.join(outputDir, `${runId}-final.png`);
      await page.screenshot({ path: finalShotPath, fullPage: true });
      pushArtifact(state.artifacts, "screenshot", "Playwright final screenshot", finalShotPath);
      state.logs.push(`screenshot ${path.basename(finalShotPath)}`);
    }

    if (recordTrace) {
      await context.tracing.stop({ path: tracePath });
      pushArtifact(state.artifacts, "trace", "Playwright trace", tracePath);
      state.logs.push("trace saved");
    }

    const status = allPassed ? "passed" : "failed";
    const summary = allPassed
      ? `Playwright UI 用例执行完成，${state.actionResults.length}/${actions.length} 步通过。`
      : `Playwright UI 用例执行失败，${state.actionResults.filter((x) => x.status === "passed").length}/${actions.length} 步通过。`;

    const report = {
      runId,
      runner: "ui",
      status,
      summary,
      startUrl,
      currentUrl: page.url(),
      logs: state.logs,
      artifacts: state.artifacts,
      caseTitle: payload.caseTitle || "",
      objective: payload.objective || "",
      assertionHints: Array.isArray(payload.assertionHints) ? payload.assertionHints : [],
      steps: Array.isArray(payload.steps) ? payload.steps : [],
      actionResults: state.actionResults,
      consoleErrors: state.consoleErrors,
      failedRequests: state.failedRequests,
      metrics: {
        totalActions: actions.length,
        passedActions: state.actionResults.filter((x) => x.status === "passed").length,
        failedActions: state.actionResults.filter((x) => x.status !== "passed").length,
      },
    };
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
    pushArtifact(report.artifacts, "json", "Playwright JSON report", reportPath);
    console.log(JSON.stringify(report));
    await browser.close();
    process.exit(status === "passed" ? 0 : 1);
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    state.logs.push(`error: ${errorMessage}`);

    try {
      if (page) {
        const failShotPath = path.join(outputDir, `${runId}-failure.png`);
        await page.screenshot({ path: failShotPath, fullPage: true });
        pushArtifact(state.artifacts, "screenshot", "Playwright failure screenshot", failShotPath);
        state.logs.push(`screenshot ${path.basename(failShotPath)}`);
      }
    } catch {
      state.logs.push("failure screenshot capture skipped");
    }

    try {
      if (recordTrace && context) {
        await context.tracing.stop({ path: tracePath });
        pushArtifact(state.artifacts, "trace", "Playwright trace", tracePath);
        state.logs.push("trace saved");
      }
    } catch {
      state.logs.push("trace save skipped");
    }

    const report = {
      runId,
      runner: "ui",
      status: "failed",
      summary: "Playwright UI 用例执行失败。",
      startUrl,
      currentUrl: page?.url?.() || startUrl,
      logs: state.logs,
      artifacts: state.artifacts,
      error: errorMessage,
      caseTitle: payload.caseTitle || "",
      objective: payload.objective || "",
      assertionHints: Array.isArray(payload.assertionHints) ? payload.assertionHints : [],
      steps: Array.isArray(payload.steps) ? payload.steps : [],
      actionResults: state.actionResults,
      consoleErrors: state.consoleErrors,
      failedRequests: state.failedRequests,
      metrics: {
        totalActions: actions.length,
        passedActions: state.actionResults.filter((x) => x.status === "passed").length,
        failedActions: state.actionResults.filter((x) => x.status !== "passed").length,
      },
    };
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
    pushArtifact(report.artifacts, "json", "Playwright JSON report", reportPath);
    console.log(JSON.stringify(report));

    if (browser) {
      await browser.close().catch(() => undefined);
    }
    process.exit(1);
  }
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.log(
    JSON.stringify({
      runId: "unknown",
      runner: "ui",
      status: "failed",
      summary: "Playwright worker 启动失败。",
      logs: [`fatal: ${message}`],
      artifacts: [],
    }),
  );
  process.exit(1);
});
