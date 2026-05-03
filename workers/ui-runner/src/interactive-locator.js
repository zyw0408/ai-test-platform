import fs from "node:fs";
import path from "node:path";
import { chromium, firefox, webkit } from "playwright";

const requestPath = process.argv[2];

if (!requestPath) {
  console.error("Usage: node src/interactive-locator.js <locator-request.json>");
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

function buildSuggestedActions(candidate, nextUrl, navigated) {
  const actions = [];
  actions.push({
    type: "click",
    selector: candidate.selector,
    timeoutMs: 30000,
  });
  actions.push({
    type: "waitForSelector",
    selector: candidate.selector,
    state: "attached",
    timeoutMs: 30000,
  });
  if (navigated && nextUrl) {
    actions.push({
      type: "expectUrl",
      value: nextUrl,
      match: "includes",
      timeoutMs: 30000,
    });
  }
  return actions;
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

async function pickElementWithOverlay(page, timeoutMs) {
  return page.evaluate((maxWaitMs) => {
    return new Promise((resolve) => {
      let hovered = null;

      const highlight = document.createElement("div");
      highlight.style.position = "fixed";
      highlight.style.pointerEvents = "none";
      highlight.style.zIndex = "2147483646";
      highlight.style.border = "2px solid #00bcd4";
      highlight.style.borderRadius = "6px";
      highlight.style.background = "rgba(0,188,212,0.08)";
      highlight.style.display = "none";

      const tag = document.createElement("div");
      tag.style.position = "fixed";
      tag.style.pointerEvents = "none";
      tag.style.zIndex = "2147483647";
      tag.style.padding = "4px 8px";
      tag.style.borderRadius = "6px";
      tag.style.fontSize = "12px";
      tag.style.fontFamily = "monospace";
      tag.style.color = "#fff";
      tag.style.background = "rgba(15,23,42,.92)";
      tag.textContent = "点击选择元素";
      tag.style.display = "none";

      const hint = document.createElement("div");
      hint.style.position = "fixed";
      hint.style.right = "12px";
      hint.style.bottom = "12px";
      hint.style.zIndex = "2147483647";
      hint.style.padding = "8px 12px";
      hint.style.borderRadius = "8px";
      hint.style.fontSize = "12px";
      hint.style.fontFamily = "system-ui, -apple-system, sans-serif";
      hint.style.color = "#fff";
      hint.style.background = "rgba(15,23,42,.92)";
      hint.textContent = "移动鼠标可高亮元素，点击即可选中";

      document.body.appendChild(highlight);
      document.body.appendChild(tag);
      document.body.appendChild(hint);

      const cleanup = () => {
        document.removeEventListener("mousemove", onMouseMove, true);
        document.removeEventListener("click", onClick, true);
        highlight.remove();
        tag.remove();
        hint.remove();
      };

      const toMeta = (element) => {
        const tagName = element?.tagName?.toLowerCase?.() || "";
        const role = element?.getAttribute?.("role") || "";
        const text = (element?.innerText || element?.textContent || "").replace(/\s+/g, " ").trim();
        const ariaLabel = element?.getAttribute?.("aria-label") || "";
        const placeholder = element?.getAttribute?.("placeholder") || "";
        const name = element?.getAttribute?.("name") || "";
        const type = element?.getAttribute?.("type") || "";
        const testId = element?.getAttribute?.("data-testid") || "";
        const elementId = element?.getAttribute?.("id") || "";
        return { tagName, role, text, ariaLabel, placeholder, name, type, testId, elementId };
      };

      const updateOverlay = (element) => {
        if (!element || !(element instanceof Element)) {
          highlight.style.display = "none";
          tag.style.display = "none";
          hovered = null;
          return;
        }
        hovered = element;
        const rect = element.getBoundingClientRect();
        highlight.style.display = "block";
        highlight.style.left = `${Math.max(rect.left - 2, 0)}px`;
        highlight.style.top = `${Math.max(rect.top - 2, 0)}px`;
        highlight.style.width = `${Math.max(rect.width + 4, 0)}px`;
        highlight.style.height = `${Math.max(rect.height + 4, 0)}px`;

        const text = (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
        const label = `${element.tagName.toLowerCase()}${text ? ` | ${text}` : ""}`;
        tag.textContent = label;
        tag.style.display = "block";
        tag.style.left = `${Math.max(rect.left, 4)}px`;
        tag.style.top = `${Math.max(rect.top - 28, 4)}px`;
      };

      const onMouseMove = (event) => {
        const element = document.elementFromPoint(event.clientX, event.clientY);
        updateOverlay(element);
      };

      const onClick = (event) => {
        const element = hovered || document.elementFromPoint(event.clientX, event.clientY);
        const meta = element ? toMeta(element) : null;
        cleanup();
        resolve(meta);
      };

      document.addEventListener("mousemove", onMouseMove, true);
      document.addEventListener("click", onClick, true);

      setTimeout(() => {
        cleanup();
        resolve(null);
      }, Math.max(Number(maxWaitMs) || 30000, 3000));
    });
  }, timeoutMs);
}

async function main() {
  const absolutePath = path.resolve(requestPath);
  const payload = parsePayload(JSON.parse(fs.readFileSync(absolutePath, "utf8")));
  const browserName = String(payload.browser || "chromium");
  const url = String(payload.url || "").trim();
  const timeoutMs = Number(payload.timeoutMs || 60000);
  const waitUntil = String(payload.waitUntil || "load");
  const limit = Number(payload.limit || 36);

  if (!url) {
    throw new Error("url is required");
  }

  const logs = [`interactive locator worker booted (${browserName})`];
  const factory = browserFactories[browserName] || chromium;
  const launchOptions = { headless: false };
  if (browserName === "chromium") {
    launchOptions.args = ["--start-maximized"];
  }
  const browser = await factory.launch(launchOptions);
  const context = await browser.newContext({ viewport: null });
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil, timeout: timeoutMs });
    logs.push(`goto ${url}`);
    logs.push("window is resizable in interactive mode");
    await page.waitForTimeout(400);

    logs.push("等待用户点击元素（已开启鼠标悬停高亮）...");
    const clickedMeta = await pickElementWithOverlay(page, 30000);
    if (!clickedMeta) {
      throw new Error("用户未在30秒内点击任何元素");
    }

    const alternatives = buildSelectorAlternatives(clickedMeta);
    const selector = alternatives[0];
    if (!selector) {
      throw new Error("无法为选中的元素生成选择器");
    }

    const candidate = {
      selector,
      alternatives,
      strategy: inferStrategy(selector),
      description: buildDescription(clickedMeta),
      label: buildLabel(clickedMeta),
      tagName: clickedMeta.tagName || "",
      role: clickedMeta.role || "",
      text: normalizeText(clickedMeta.text, 120),
      name: clickedMeta.name || "",
      placeholder: clickedMeta.placeholder || "",
      testId: clickedMeta.testId || "",
      elementId: clickedMeta.elementId || "",
    };
    logs.push(`成功定位元素: ${candidate.label}`);

    const beforeUrl = page.url();
    try {
      await page.waitForLoadState("domcontentloaded", { timeout: 5000 });
    } catch {
      // ignore wait timeout, SPA may not trigger full load.
    }
    await page.waitForTimeout(500);
    const afterUrl = page.url();
    const nextCandidates = await collectLocatorCandidates(page, limit);
    const suggestedActions = buildSuggestedActions(candidate, afterUrl, beforeUrl !== afterUrl);
    logs.push(`post-click candidates: ${nextCandidates.length}`);

    console.log(
      JSON.stringify({
        url: beforeUrl,
        title: await page.title(),
        browser: browserName,
        logs,
        candidate,
        nextUrl: afterUrl,
        navigated: beforeUrl !== afterUrl,
        nextCandidates,
        suggestedActions,
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
        candidate: null,
        nextUrl: page.url?.() || url,
        navigated: false,
        nextCandidates: [],
        suggestedActions: [],
        summary: `交互式定位失败: ${message}`,
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
      candidate: null,
      nextUrl: "",
      navigated: false,
      nextCandidates: [],
      suggestedActions: [],
      summary: `交互式定位工具启动失败: ${message}`,
    }),
  );
  process.exit(1);
});
