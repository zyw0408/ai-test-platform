"use client";

import { type CSSProperties, useEffect, useMemo, useState } from "react";
import { Crosshair, Loader2, Plus, Sparkles, Trash2, Wand2 } from "lucide-react";

type UiActionType =
  | "goto"
  | "click"
  | "fill"
  | "press"
  | "waitForSelector"
  | "waitForTimeout"
  | "expectText"
  | "expectVisible"
  | "expectUrl"
  | "screenshot"
  | "setContent";

type UiBrowserName = "chromium" | "firefox" | "webkit";

type UiAction = Record<string, unknown> & {
  type: UiActionType;
};

type UiCasePayload = {
  startUrl: string;
  browser: UiBrowserName;
  headless: boolean;
  timeoutMs: number;
  viewport: {
    width: number;
    height: number;
  };
  recordTrace: boolean;
  screenshotOnCompletion: boolean;
  actions: UiAction[];
};

type ParseResult = {
  data: Record<string, unknown> | null;
  error: string;
};

type LocatorCandidate = {
  selector: string;
  strategy: string;
  description: string;
  label: string;
  tagName: string;
  role: string;
  text: string;
  placeholder: string;
  testId: string;
  alternatives: string[];
};

type LocatorInspectResponse = {
  url: string;
  title: string;
  browser: UiBrowserName;
  logs: string[];
  candidates: LocatorCandidate[];
};

const actionTypeOptions: Array<{ value: UiActionType; label: string }> = [
  { value: "goto", label: "打开页面" },
  { value: "click", label: "点击元素" },
  { value: "fill", label: "输入文本" },
  { value: "press", label: "键盘按键" },
  { value: "waitForSelector", label: "等待元素" },
  { value: "waitForTimeout", label: "等待时间" },
  { value: "expectText", label: "断言文本" },
  { value: "expectVisible", label: "断言可见" },
  { value: "expectUrl", label: "断言地址" },
  { value: "screenshot", label: "截图" },
  { value: "setContent", label: "注入 HTML" },
];

const actionTemplateMap: Record<UiActionType, UiAction> = {
  goto: { type: "goto", url: "" },
  click: { type: "click", selector: "" },
  fill: { type: "fill", selector: "", value: "" },
  press: { type: "press", selector: "", key: "Enter" },
  waitForSelector: { type: "waitForSelector", selector: "", state: "visible" },
  waitForTimeout: { type: "waitForTimeout", ms: 800 },
  expectText: { type: "expectText", selector: "", text: "" },
  expectVisible: { type: "expectVisible", selector: "" },
  expectUrl: { type: "expectUrl", value: "", match: "includes" },
  screenshot: { type: "screenshot", name: "capture", fullPage: true },
  setContent: { type: "setContent", html: "<div>hello</div>" },
};

function parseJsonText(value: string): ParseResult {
  const trimmed = value.trim();
  if (!trimmed) {
    return { data: null, error: "" };
  }
  try {
    const parsed = JSON.parse(trimmed);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { data: null, error: "payload 必须是 JSON 对象" };
    }
    return { data: parsed as Record<string, unknown>, error: "" };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : "payload JSON 解析失败",
    };
  }
}

function toPositiveNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function toBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function toStringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function sanitizeAction(raw: unknown): UiAction {
  const source = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const rawType = toStringValue(source.type || source.action, "click") as UiActionType;
  const type = actionTemplateMap[rawType] ? rawType : "click";
  return {
    ...actionTemplateMap[type],
    ...source,
    type,
  };
}

function createDefaultUiPayload(): UiCasePayload {
  return {
    startUrl: "",
    browser: "chromium",
    headless: true,
    timeoutMs: 30000,
    viewport: {
      width: 1440,
      height: 900,
    },
    recordTrace: true,
    screenshotOnCompletion: true,
    actions: [],
  };
}

function sanitizePayload(raw: Record<string, unknown> | null): UiCasePayload {
  const fallback = createDefaultUiPayload();
  const viewportSource =
    raw?.viewport && typeof raw.viewport === "object" && !Array.isArray(raw.viewport)
      ? (raw.viewport as Record<string, unknown>)
      : {};
  return {
    startUrl: toStringValue(raw?.startUrl),
    browser: (["chromium", "firefox", "webkit"].includes(toStringValue(raw?.browser))
      ? raw?.browser
      : fallback.browser) as UiBrowserName,
    headless: toBoolean(raw?.headless, fallback.headless),
    timeoutMs: toPositiveNumber(raw?.timeoutMs, fallback.timeoutMs),
    viewport: {
      width: toPositiveNumber(viewportSource.width, fallback.viewport.width),
      height: toPositiveNumber(viewportSource.height, fallback.viewport.height),
    },
    recordTrace: toBoolean(raw?.recordTrace, fallback.recordTrace),
    screenshotOnCompletion: toBoolean(
      raw?.screenshotOnCompletion,
      fallback.screenshotOnCompletion,
    ),
    actions: Array.isArray(raw?.actions) ? raw.actions.map((item) => sanitizeAction(item)) : [],
  };
}

function stringifyPayload(payload: UiCasePayload): string {
  return JSON.stringify(payload, null, 2);
}

function clonePayload(payload: UiCasePayload): UiCasePayload {
  return JSON.parse(JSON.stringify(payload)) as UiCasePayload;
}

function buildActionSummary(action: UiAction): string {
  const type = action.type;
  if (type === "goto") return toStringValue(action.url) || "等待填写地址";
  if (type === "click" || type === "fill" || type === "expectText" || type === "expectVisible") {
    return toStringValue(action.selector) || "等待选择器";
  }
  if (type === "press") return `${toStringValue(action.selector) || "页面"} / ${toStringValue(action.key) || "Enter"}`;
  if (type === "waitForSelector") {
    return `${toStringValue(action.selector) || "等待选择器"} / ${toStringValue(action.state) || "visible"}`;
  }
  if (type === "waitForTimeout") return `${toPositiveNumber(action.ms, 800)}ms`;
  if (type === "expectUrl") return toStringValue(action.value) || "等待填写 URL";
  if (type === "screenshot") return toStringValue(action.name) || "capture";
  if (type === "setContent") return "设置页面内容";
  return "";
}

export function UiCaseBuilder({
  value,
  onChange,
}: {
  value: string;
  onChange: (nextValue: string) => void;
}) {
  const parseResult = useMemo(() => parseJsonText(value), [value]);
  const payload = useMemo(() => sanitizePayload(parseResult.data), [parseResult.data]);
  const [selectedActionIndex, setSelectedActionIndex] = useState(0);
  const [showRawJson, setShowRawJson] = useState(false);
  const [inspectUrl, setInspectUrl] = useState("");
  const [isInspecting, setIsInspecting] = useState(false);
  const [locatorError, setLocatorError] = useState("");
  const [locatorData, setLocatorData] = useState<LocatorInspectResponse | null>(null);

  useEffect(() => {
    const trimmed = value.trim();
    if (trimmed === "" || trimmed === "{}") {
      onChange(stringifyPayload(createDefaultUiPayload()));
    }
  }, [onChange, value]);

  useEffect(() => {
    if (!inspectUrl.trim() && payload.startUrl.trim()) {
      setInspectUrl(payload.startUrl);
    }
  }, [inspectUrl, payload.startUrl]);

  useEffect(() => {
    if (payload.actions.length === 0) {
      setSelectedActionIndex(0);
      return;
    }
    setSelectedActionIndex((prev) => Math.min(prev, payload.actions.length - 1));
  }, [payload.actions.length]);

  const patchPayload = (updater: (draft: UiCasePayload) => void) => {
    const draft = clonePayload(payload);
    updater(draft);
    onChange(stringifyPayload(draft));
  };

  const updateAction = (index: number, patch: Partial<UiAction>) => {
    patchPayload((draft) => {
      draft.actions[index] = {
        ...draft.actions[index],
        ...patch,
      };
    });
  };

  const replaceActionType = (index: number, type: UiActionType) => {
    patchPayload((draft) => {
      draft.actions[index] = {
        ...actionTemplateMap[type],
      };
    });
  };

  const addAction = (type: UiActionType) => {
    patchPayload((draft) => {
      draft.actions.push({ ...actionTemplateMap[type] });
    });
    setSelectedActionIndex(payload.actions.length);
  };

  const removeAction = (index: number) => {
    patchPayload((draft) => {
      draft.actions.splice(index, 1);
    });
  };

  const moveAction = (index: number, direction: -1 | 1) => {
    patchPayload((draft) => {
      const targetIndex = index + direction;
      if (targetIndex < 0 || targetIndex >= draft.actions.length) return;
      const [item] = draft.actions.splice(index, 1);
      draft.actions.splice(targetIndex, 0, item);
    });
    setSelectedActionIndex((prev) => Math.max(0, prev + direction));
  };

  const runLocatorInspect = async () => {
    const targetUrl = inspectUrl.trim() || payload.startUrl.trim();
    if (!targetUrl) {
      setLocatorError("请先填写入口地址，再使用元素定位助手。");
      return;
    }
    setIsInspecting(true);
    setLocatorError("");
    try {
      const response = await fetch("/api/ui-locator/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: targetUrl,
          browser: payload.browser,
          headless: payload.headless,
          limit: 36,
          waitUntil: "load",
          timeoutMs: Math.min(payload.timeoutMs, 20000),
        }),
        cache: "no-store",
      });
      const data = (await response.json()) as LocatorInspectResponse & {
        message?: string;
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(data.message || data.detail || "元素定位失败");
      }
      setLocatorData(data);
    } catch (error) {
      setLocatorError(error instanceof Error ? error.message : "元素定位失败");
    } finally {
      setIsInspecting(false);
    }
  };

  const runInteractiveLocator = async () => {
    const targetUrl = inspectUrl.trim() || payload.startUrl.trim();
    if (!targetUrl) {
      setLocatorError("请先填写入口地址，再使用交互式元素定位。");
      return;
    }
    setIsInspecting(true);
    setLocatorError("");
    try {
      const response = await fetch("/api/ui-locator/interactive-inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: targetUrl,
          browser: payload.browser,
          headless: false,  // 交互式定位必须使用非无头模式
          limit: 1,
          waitUntil: "load",
          timeoutMs: Math.min(payload.timeoutMs * 2, 60000),
        }),
        cache: "no-store",
      });
      const data = (await response.json()) as {
        candidate: {
          selector: string;
          alternatives: string[];
          strategy: string;
          description: string;
          label: string;
        } | null;
        message?: string;
        detail?: string;
        summary?: string;
      };
      if (!response.ok) {
        throw new Error(data.message || data.detail || data.summary || "交互式元素定位失败");
      }
      if (data.candidate) {
        applySelector(data.candidate.selector);
        setLocatorError(`成功定位元素: ${data.candidate.label}`);
      } else {
        setLocatorError("未选择任何元素");
      }
    } catch (error) {
      setLocatorError(error instanceof Error ? error.message : "交互式元素定位失败");
    } finally {
      setIsInspecting(false);
    }
  };

  const applySelector = (selector: string) => {
    if (payload.actions.length === 0) {
      patchPayload((draft) => {
        draft.actions.push({ ...actionTemplateMap.click, selector });
      });
      setSelectedActionIndex(0);
      return;
    }
    const safeIndex = Math.min(selectedActionIndex, payload.actions.length - 1);
    updateAction(safeIndex, { selector });
  };

  return (
    <div style={{ display: "grid", gap: 16, gridColumn: "1 / span 2" }}>
      <section style={panelStyle}>
        <div style={sectionHeadStyle}>
          <div>
            <div style={kickerStyle}>Playwright Builder</div>
            <strong style={{ fontSize: "1rem" }}>可视化 UI 用例配置</strong>
          </div>
          <button type="button" style={ghostBtnStyle} onClick={() => setShowRawJson((prev) => !prev)}>
            <Sparkles size={14} />
            {showRawJson ? "隐藏 JSON" : "查看 JSON"}
          </button>
        </div>

        {parseResult.error ? (
          <div style={warningStyle}>
            当前 payload JSON 解析失败：{parseResult.error}
            <button
              type="button"
              style={linkBtnStyle}
              onClick={() => onChange(stringifyPayload(createDefaultUiPayload()))}
            >
              恢复默认 UI 配置
            </button>
          </div>
        ) : null}

        <div style={configGridStyle}>
          <label style={labelStyle}>
            入口地址
            <input
              value={payload.startUrl}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.startUrl = event.target.value;
                })
              }
              style={inputStyle}
              placeholder="https://example.com/login"
            />
          </label>
          <label style={labelStyle}>
            浏览器
            <select
              value={payload.browser}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.browser = event.target.value as UiBrowserName;
                })
              }
              style={inputStyle}
            >
              <option value="chromium">Chromium</option>
              <option value="firefox">Firefox</option>
              <option value="webkit">WebKit</option>
            </select>
          </label>
          <label style={labelStyle}>
            超时（ms）
            <input
              type="number"
              min={1000}
              step={500}
              value={payload.timeoutMs}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.timeoutMs = toPositiveNumber(event.target.value, draft.timeoutMs);
                })
              }
              style={inputStyle}
            />
          </label>
          <label style={labelStyle}>
            视口宽度
            <input
              type="number"
              min={320}
              step={10}
              value={payload.viewport.width}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.viewport.width = toPositiveNumber(event.target.value, draft.viewport.width);
                })
              }
              style={inputStyle}
            />
          </label>
          <label style={labelStyle}>
            视口高度
            <input
              type="number"
              min={320}
              step={10}
              value={payload.viewport.height}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.viewport.height = toPositiveNumber(event.target.value, draft.viewport.height);
                })
              }
              style={inputStyle}
            />
          </label>
          <label style={{ ...checkLabelStyle, gridColumn: "1 / span 2" }}>
            <input
              type="checkbox"
              checked={payload.headless}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.headless = event.target.checked;
                })
              }
            />
            无头执行（适合服务器或批量执行）
          </label>
          <label style={checkLabelStyle}>
            <input
              type="checkbox"
              checked={payload.recordTrace}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.recordTrace = event.target.checked;
                })
              }
            />
            保存 Trace
          </label>
          <label style={checkLabelStyle}>
            <input
              type="checkbox"
              checked={payload.screenshotOnCompletion}
              onChange={(event) =>
                patchPayload((draft) => {
                  draft.screenshotOnCompletion = event.target.checked;
                })
              }
            />
            结束后截图
          </label>
        </div>
      </section>

      <section style={builderGridStyle}>
        <div style={panelStyle}>
          <div style={sectionHeadStyle}>
            <div>
              <div style={kickerStyle}>Actions</div>
              <strong style={{ fontSize: "1rem" }}>步骤编排</strong>
            </div>
            <button type="button" style={primaryBtnStyle} onClick={() => addAction("click")}>
              <Plus size={14} />
              新增步骤
            </button>
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            {payload.actions.length > 0 ? (
              payload.actions.map((action, index) => {
                const isActive = index === selectedActionIndex;
                return (
                  <article
                    key={`${action.type}-${index}`}
                    style={{
                      ...actionCardStyle,
                      ...(isActive ? activeActionCardStyle : null),
                    }}
                  >
                    <div style={actionHeadStyle}>
                      <button
                        type="button"
                        style={actionTitleBtnStyle}
                        onClick={() => setSelectedActionIndex(index)}
                      >
                        步骤 {index + 1}
                        <span style={tinyBadgeStyle}>{buildActionSummary(action)}</span>
                      </button>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <button
                          type="button"
                          style={miniBtnStyle}
                          onClick={() => moveAction(index, -1)}
                          disabled={index === 0}
                        >
                          上移
                        </button>
                        <button
                          type="button"
                          style={miniBtnStyle}
                          onClick={() => moveAction(index, 1)}
                          disabled={index === payload.actions.length - 1}
                        >
                          下移
                        </button>
                        <button type="button" style={dangerBtnStyle} onClick={() => removeAction(index)}>
                          <Trash2 size={14} />
                          删除
                        </button>
                      </div>
                    </div>

                    <div style={actionGridStyle}>
                      <label style={labelStyle}>
                        动作类型
                        <select
                          value={action.type}
                          onChange={(event) => replaceActionType(index, event.target.value as UiActionType)}
                          style={inputStyle}
                        >
                          {actionTypeOptions.map((item) => (
                            <option key={item.value} value={item.value}>
                              {item.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      {(action.type === "click" ||
                        action.type === "fill" ||
                        action.type === "press" ||
                        action.type === "waitForSelector" ||
                        action.type === "expectText" ||
                        action.type === "expectVisible") && (
                        <label style={labelStyle}>
                          Selector
                          <input
                            value={toStringValue(action.selector)}
                            onChange={(event) => updateAction(index, { selector: event.target.value })}
                            style={inputStyle}
                            placeholder='如：button:has-text("登录")'
                          />
                        </label>
                      )}

                      {action.type === "goto" ? (
                        <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
                          跳转地址
                          <input
                            value={toStringValue(action.url)}
                            onChange={(event) => updateAction(index, { url: event.target.value })}
                            style={inputStyle}
                            placeholder="留空则使用入口地址"
                          />
                        </label>
                      ) : null}

                      {action.type === "fill" ? (
                        <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
                          输入值
                          <input
                            value={toStringValue(action.value)}
                            onChange={(event) => updateAction(index, { value: event.target.value })}
                            style={inputStyle}
                            placeholder="demo"
                          />
                        </label>
                      ) : null}

                      {action.type === "press" ? (
                        <label style={labelStyle}>
                          按键
                          <input
                            value={toStringValue(action.key, "Enter")}
                            onChange={(event) => updateAction(index, { key: event.target.value })}
                            style={inputStyle}
                            placeholder="Enter"
                          />
                        </label>
                      ) : null}

                      {action.type === "waitForSelector" ? (
                        <label style={labelStyle}>
                          等待状态
                          <select
                            value={toStringValue(action.state, "visible")}
                            onChange={(event) => updateAction(index, { state: event.target.value })}
                            style={inputStyle}
                          >
                            <option value="visible">visible</option>
                            <option value="attached">attached</option>
                            <option value="hidden">hidden</option>
                            <option value="detached">detached</option>
                          </select>
                        </label>
                      ) : null}

                      {action.type === "waitForTimeout" ? (
                        <label style={labelStyle}>
                          等待毫秒
                          <input
                            type="number"
                            min={100}
                            step={100}
                            value={toPositiveNumber(action.ms, 800)}
                            onChange={(event) => updateAction(index, { ms: toPositiveNumber(event.target.value, 800) })}
                            style={inputStyle}
                          />
                        </label>
                      ) : null}

                      {action.type === "expectText" ? (
                        <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
                          期望文本
                          <input
                            value={toStringValue(action.text)}
                            onChange={(event) => updateAction(index, { text: event.target.value })}
                            style={inputStyle}
                            placeholder="登录成功"
                          />
                        </label>
                      ) : null}

                      {action.type === "expectUrl" ? (
                        <>
                          <label style={labelStyle}>
                            URL 关键字
                            <input
                              value={toStringValue(action.value)}
                              onChange={(event) => updateAction(index, { value: event.target.value })}
                              style={inputStyle}
                              placeholder="/dashboard"
                            />
                          </label>
                          <label style={labelStyle}>
                            匹配方式
                            <select
                              value={toStringValue(action.match, "includes")}
                              onChange={(event) => updateAction(index, { match: event.target.value })}
                              style={inputStyle}
                            >
                              <option value="includes">includes</option>
                              <option value="exact">exact</option>
                            </select>
                          </label>
                        </>
                      ) : null}

                      {action.type === "screenshot" ? (
                        <>
                          <label style={labelStyle}>
                            截图名
                            <input
                              value={toStringValue(action.name, "capture")}
                              onChange={(event) => updateAction(index, { name: event.target.value })}
                              style={inputStyle}
                              placeholder="dashboard"
                            />
                          </label>
                          <label style={checkLabelStyle}>
                            <input
                              type="checkbox"
                              checked={toBoolean(action.fullPage, true)}
                              onChange={(event) => updateAction(index, { fullPage: event.target.checked })}
                            />
                            全页截图
                          </label>
                        </>
                      ) : null}

                      {action.type === "setContent" ? (
                        <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
                          HTML 内容
                          <textarea
                            value={toStringValue(action.html)}
                            onChange={(event) => updateAction(index, { html: event.target.value })}
                            style={{ ...areaStyle, minHeight: 120 }}
                            placeholder="<div>hello</div>"
                          />
                        </label>
                      ) : null}

                      {action.type !== "waitForTimeout" &&
                      action.type !== "screenshot" &&
                      action.type !== "setContent" ? (
                        <label style={labelStyle}>
                          timeoutMs
                          <input
                            type="number"
                            min={100}
                            step={100}
                            value={toPositiveNumber(action.timeoutMs, payload.timeoutMs)}
                            onChange={(event) =>
                              updateAction(index, {
                                timeoutMs: toPositiveNumber(event.target.value, payload.timeoutMs),
                              })
                            }
                            style={inputStyle}
                          />
                        </label>
                      ) : null}
                    </div>
                  </article>
                );
              })
            ) : (
              <div style={emptyStateStyle}>
                还没有步骤。先新增一个动作，或者用右侧定位助手抓到元素后自动插入一个 `click` 步骤。
              </div>
            )}
          </div>
        </div>

        <div style={panelStyle}>
          <div style={sectionHeadStyle}>
            <div>
              <div style={kickerStyle}>Locator</div>
              <strong style={{ fontSize: "1rem" }}>元素定位助手</strong>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" style={primaryBtnStyle} onClick={() => void runLocatorInspect()} disabled={isInspecting}>
                {isInspecting ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                抓取页面元素
              </button>
              <button type="button" style={secondaryBtnStyle} onClick={() => void runInteractiveLocator()} disabled={isInspecting}>
                {isInspecting ? <Loader2 size={14} className="animate-spin" /> : <Crosshair size={14} />}
                鼠标选择元素
              </button>
            </div>
          </div>

          <label style={labelStyle}>
            页面地址
            <input
              value={inspectUrl}
              onChange={(event) => setInspectUrl(event.target.value)}
              style={inputStyle}
              placeholder="https://example.com/login"
            />
          </label>

          <div style={tipStyle}>
            当前选中的步骤会作为 selector 填充目标。没有选中步骤时，定位助手会自动新建一个 `click` 步骤。
          </div>

          {locatorError ? <div style={warningStyle}>{locatorError}</div> : null}

          {locatorData ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={locatorSummaryStyle}>
                <div>
                  <strong>{locatorData.title || "未获取到页面标题"}</strong>
                  <div style={mutedTextStyle}>{locatorData.url}</div>
                </div>
                <span style={tinyBadgeStyle}>{locatorData.candidates.length} 个候选元素</span>
              </div>
              {locatorData.candidates.map((candidate) => (
                <article key={`${candidate.selector}-${candidate.strategy}`} style={locatorCardStyle}>
                  <div style={{ display: "grid", gap: 6 }}>
                    <strong>{candidate.label || candidate.selector}</strong>
                    <div style={mutedTextStyle}>{candidate.description || candidate.strategy}</div>
                    <code style={codeStyle}>{candidate.selector}</code>
                    {candidate.alternatives.length > 1 ? (
                      <div style={mutedTextStyle}>
                        备选：{candidate.alternatives.slice(1, 3).join("  |  ")}
                      </div>
                    ) : null}
                  </div>
                  <button type="button" style={miniPrimaryBtnStyle} onClick={() => applySelector(candidate.selector)}>
                    <Crosshair size={14} />
                    用到当前步骤
                  </button>
                </article>
              ))}
              {locatorData.logs.length > 0 ? (
                <div style={tipStyle}>执行日志：{locatorData.logs.join(" / ")}</div>
              ) : null}
            </div>
          ) : (
            <div style={emptyStateStyle}>填好页面地址后点“抓取页面元素”，就能拿到 selector 候选列表。</div>
          )}
        </div>
      </section>

      {showRawJson ? (
        <label style={labelStyle}>
          原始 Payload JSON
          <textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            style={{ ...areaStyle, minHeight: 220, fontFamily: "var(--mono)" }}
          />
        </label>
      ) : null}
    </div>
  );
}

const panelStyle: CSSProperties = {
  display: "grid",
  gap: 14,
  padding: 20,
  borderRadius: 24,
  border: "1px solid var(--line)",
  background: "var(--panel)",
  backdropFilter: "blur(14px)",
  boxShadow: "var(--shadow-md)",
};

const sectionHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  alignItems: "center",
  flexWrap: "wrap",
};

const kickerStyle: CSSProperties = {
  fontSize: ".72rem",
  letterSpacing: ".12em",
  textTransform: "uppercase",
  color: "var(--ink-soft)",
  marginBottom: 4,
};

const configGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 12,
};

const builderGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.35fr) minmax(320px, .95fr)",
  gap: 16,
};

const labelStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  fontSize: ".9rem",
  color: "var(--ink-soft)",
};

const inputStyle: CSSProperties = {
  height: 42,
  borderRadius: 14,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.75)",
  padding: "0 16px",
  fontSize: ".92rem",
  color: "var(--ink)",
  transition: "all 0.3s ease",
};

const areaStyle: CSSProperties = {
  minHeight: 84,
  borderRadius: 14,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.75)",
  padding: "12px 16px",
  fontSize: ".92rem",
  color: "var(--ink)",
  resize: "vertical",
  transition: "all 0.3s ease",
};

const primaryBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  height: 42,
  padding: "0 16px",
  border: "none",
  borderRadius: 14,
  background: "var(--primary)",
  color: "white",
  cursor: "pointer",
  fontWeight: 600,
  transition: "all 0.3s ease",
};

const secondaryBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  height: 42,
  padding: "0 16px",
  borderRadius: 14,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.75)",
  color: "var(--ink)",
  cursor: "pointer",
  fontWeight: 600,
  transition: "all 0.3s ease",
};

const ghostBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  height: 42,
  padding: "0 16px",
  borderRadius: 14,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.75)",
  color: "var(--ink)",
  cursor: "pointer",
  transition: "all 0.3s ease",
};

const warningStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10,
  alignItems: "center",
  borderRadius: 12,
  padding: "10px 12px",
  background: "rgba(245,158,11,.12)",
  color: "#92400e",
  fontSize: ".9rem",
};

const linkBtnStyle: CSSProperties = {
  border: "none",
  background: "transparent",
  color: "#92400e",
  cursor: "pointer",
  textDecoration: "underline",
  padding: 0,
};

const actionCardStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  padding: 16,
  borderRadius: 18,
  borderWidth: 1,
  borderStyle: "solid",
  borderColor: "var(--line)",
  background: "rgba(255, 255, 255, 0.85)",
  transition: "all 0.3s ease",
};

const activeActionCardStyle: CSSProperties = {
  borderColor: "var(--primary)",
  boxShadow: "0 0 0 3px var(--primary-alpha-20)",
  background: "rgba(255, 255, 255, 0.95)",
  transform: "translateY(-1px)",
};

const actionHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 10,
  alignItems: "center",
  flexWrap: "wrap",
};

const actionTitleBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  border: "none",
  background: "transparent",
  cursor: "pointer",
  padding: 0,
  fontWeight: 700,
  color: "var(--ink)",
};

const actionGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 12,
};

const tinyBadgeStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  minHeight: 24,
  padding: "0 8px",
  borderRadius: 999,
  background: "rgba(14,165,233,.1)",
  color: "#0369a1",
  fontSize: ".76rem",
  fontWeight: 600,
};

const miniBtnStyle: CSSProperties = {
  height: 36,
  padding: "0 12px",
  borderRadius: 12,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.75)",
  color: "var(--ink)",
  cursor: "pointer",
  transition: "all 0.3s ease",
};

const dangerBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  height: 36,
  padding: "0 12px",
  borderRadius: 12,
  border: "1px solid rgba(239,68,68,.25)",
  background: "rgba(254,226,226,.75)",
  color: "#b91c1c",
  cursor: "pointer",
  transition: "all 0.3s ease",
};

const miniPrimaryBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  height: 36,
  padding: "0 12px",
  border: "none",
  borderRadius: 12,
  background: "var(--primary)",
  color: "white",
  cursor: "pointer",
  transition: "all 0.3s ease",
};

const emptyStateStyle: CSSProperties = {
  padding: "18px 20px",
  borderRadius: 18,
  background: "rgba(226,232,240,.55)",
  color: "var(--ink-soft)",
  lineHeight: 1.7,
  border: "1px dashed var(--line)",
};

const tipStyle: CSSProperties = {
  padding: "12px 16px",
  borderRadius: 14,
  background: "var(--primary-alpha-10)",
  color: "var(--primary-hover)",
  fontSize: ".88rem",
  lineHeight: 1.7,
  border: "1px solid var(--primary-alpha-20)",
};

const locatorSummaryStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  alignItems: "center",
  padding: "14px 16px",
  borderRadius: 18,
  background: "rgba(226,232,240,.5)",
  border: "1px solid var(--line)",
};

const locatorCardStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  alignItems: "flex-start",
  padding: 16,
  borderRadius: 18,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.85)",
  transition: "all 0.3s ease",
};

const mutedTextStyle: CSSProperties = {
  color: "var(--ink-soft)",
  fontSize: ".86rem",
  lineHeight: 1.6,
};

const codeStyle: CSSProperties = {
  display: "block",
  padding: "8px 10px",
  borderRadius: 10,
  background: "rgba(15,23,42,.95)",
  color: "#e2e8f0",
  fontFamily: "var(--mono)",
  fontSize: ".82rem",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
};

const checkLabelStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  minHeight: 38,
  padding: "0 12px",
  borderRadius: 10,
  border: "1px solid rgba(148,163,184,.22)",
  background: "white",
  color: "var(--ink)",
  fontSize: ".9rem",
};
