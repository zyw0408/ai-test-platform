import fs from "node:fs";
import path from "node:path";
import { chromium, firefox, webkit } from "playwright";

const requestPath = process.argv[2];

if (!requestPath) {
  console.error("Usage: node src/locator.js <locator-request.json>");
  process.exit(1);
}

const browserFactories = {
  chromium,
  firefox,
  webkit,
};

function parsePayload(rawValue) {
  if (!rawValue || typeof rawValue !== "object" || Array.isArray(rawValue)) {
    return {};
  }
  return rawValue;
}

function normalizeText(value, maxLength = 72) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function escapeSelectorValue(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"');
}

function pushSelector(items, selector) {
  const next = String(selector || "").trim();
  if (!next || items.includes(next)) return;
  items.push(next);
}

function buildSelectorAlternatives(meta) {
  const selectors = [];
  const tagName = String(meta.tagName || "").toLowerCase();
  const text = normalizeText(meta.text, 48);
  if (meta.testId) {
    pushSelector(selectors, `[data-testid="${escapeSelectorValue(meta.testId)}"]`);
  }
  if (meta.elementId) {
    pushSelector(selectors, `[id="${escapeSelectorValue(meta.elementId)}"]`);
  }
  if (meta.name && ["input", "textarea", "select"].includes(tagName)) {
    pushSelector(selectors, `${tagName}[name="${escapeSelectorValue(meta.name)}"]`);
  }
  if (meta.ariaLabel) {
    pushSelector(selectors, `[aria-label="${escapeSelectorValue(meta.ariaLabel)}"]`);
  }
  if (meta.placeholder && ["input", "textarea"].includes(tagName)) {
    pushSelector(selectors, `${tagName}[placeholder="${escapeSelectorValue(meta.placeholder)}"]`);
  }
  if (text) {
    if (["button", "a", "label"].includes(tagName)) {
      pushSelector(selectors, `${tagName}:has-text("${escapeSelectorValue(text)}")`);
    }
    pushSelector(selectors, `text="${escapeSelectorValue(text)}"`);
  }
  if (tagName) {
    pushSelector(selectors, tagName);
  }
  return selectors;
}

function inferStrategy(selector) {
  if (selector.startsWith("[data-testid=")) return "data-testid";
  if (selector.startsWith("[id=")) return "id";
  if (selector.includes("[name=")) return "name";
  if (selector.startsWith("[aria-label=")) return "aria-label";
  if (selector.includes(":has-text(")) return "has-text";
  if (selector.startsWith("text=")) return "text";
  return "tag";
}

function buildDescription(meta) {
  const parts = [];
  if (meta.tagName) parts.push(meta.tagName);
  if (meta.role) parts.push(`role=${meta.role}`);
  if (meta.text) parts.push(`text=${normalizeText(meta.text, 36)}`);
  if (meta.placeholder) parts.push(`placeholder=${normalizeText(meta.placeholder, 24)}`);
  return parts.join(" | ");
}

function buildLabel(meta) {
  const pieces = [meta.tagName, normalizeText(meta.text, 28), normalizeText(meta.ariaLabel, 20)]
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  return pieces.join(" / ") || "可交互元素";
}

async function collectLocatorCandidates(page, limit) {
  const bufferLimit = Math.max(limit * 6, 120);
  const rawElements = await page.locator("body *").evaluateAll((elements, maxItems) => {
    function isVisible(element) {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        style.opacity !== "0"
      );
    }

    return elements
      .map((node) => {
        const element = node;
        const tagName = element.tagName.toLowerCase();
        const role = element.getAttribute("role") || "";
        const interactive =
          element.matches(
            'button, a[href], input, textarea, select, [role="button"], [role="link"], [role="textbox"], [role="tab"], [role="checkbox"], [role="radio"], [role="combobox"], [data-testid], [onclick]',
          ) || element.tabIndex >= 0;
        if (!interactive || !isVisible(element)) {
          return null;
        }
        return {
          tagName,
          role,
          text: (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim(),
          ariaLabel: element.getAttribute("aria-label") || "",
          placeholder: element.getAttribute("placeholder") || "",
          name: element.getAttribute("name") || "",
          type: element.getAttribute("type") || "",
          testId: element.getAttribute("data-testid") || "",
          elementId: element.getAttribute("id") || "",
        };
      })
      .filter(Boolean)
      .slice(0, maxItems);
  }, bufferLimit);

  const seenSelectors = new Set();
  const results = [];
  for (const meta of rawElements) {
    const alternatives = buildSelectorAlternatives(meta);
    const selector = alternatives[0];
    if (!selector || seenSelectors.has(selector)) {
      continue;
    }
    seenSelectors.add(selector);
    results.push({
      selector,
      alternatives,
      strategy: inferStrategy(selector),
      description: buildDescription(meta),
      label: buildLabel(meta),
      tagName: meta.tagName || "",
      role: meta.role || "",
      text: normalizeText(meta.text, 120),
      name: meta.name || "",
      placeholder: meta.placeholder || "",
      testId: meta.testId || "",
      elementId: meta.elementId || "",
    });
    if (results.length >= limit) {
      break;
    }
  }
  return results;
}

async function main() {
  const absolutePath = path.resolve(requestPath);
  const payload = parsePayload(JSON.parse(fs.readFileSync(absolutePath, "utf8")));
  const browserName = String(payload.browser || "chromium");
  const url = String(payload.url || "").trim();
  const headless = payload.headless !== false;
  const timeoutMs = Number(payload.timeoutMs || 15000);
  const waitUntil = String(payload.waitUntil || "load");
  const limit = Number(payload.limit || 40);

  if (!url) {
    throw new Error("url is required");
  }

  const logs = [`locator worker booted (${browserName})`];
  const factory = browserFactories[browserName] || chromium;
  const browser = await factory.launch({ headless });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil, timeout: timeoutMs });
    logs.push(`goto ${url}`);
    await page.waitForTimeout(400);
    const candidates = await collectLocatorCandidates(page, limit);
    logs.push(`collected ${candidates.length} candidates`);

    console.log(
      JSON.stringify({
        url: page.url(),
        title: await page.title(),
        browser: browserName,
        logs,
        candidates,
      }),
    );
    await browser.close();
    process.exit(0);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    logs.push(`error: ${message}`);
    console.log(
      JSON.stringify({
        url,
        title: "",
        browser: browserName,
        logs,
        candidates: [],
        summary: `定位工具执行失败: ${message}`,
      }),
    );
    await browser.close().catch(() => undefined);
    process.exit(1);
  }
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.log(
    JSON.stringify({
      url: "",
      title: "",
      browser: "chromium",
      logs: [`fatal: ${message}`],
      candidates: [],
      summary: `定位工具启动失败: ${message}`,
    }),
  );
  process.exit(1);
});
