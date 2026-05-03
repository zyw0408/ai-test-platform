"use client";

import Link from "next/link";
import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Project, SourceSpec, TestCase, TestRun } from "@ai-test-platform/shared-schema";
import {
  Activity,
  CirclePlay,
  ClipboardList,
  Compass,
  Edit3,
  Layers,
  Loader2,
  Plus,
  Play,
  RefreshCcw,
  Save,
  X,
  Trash2,
} from "lucide-react";
import { UiCaseBuilder } from "./ui-case-builder";
import { computeVirtualWindow } from "../lib/virtual-list";

interface TestCaseListResponse {
  items: TestCase[];
  total: number;
  page: number;
  pageSize: number;
}

type Notice = { kind: "success" | "error"; text: string } | null;
type UiEditorMode = "create" | "update";

function readErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const data = payload as { message?: unknown; detail?: unknown };
  if (typeof data.message === "string" && data.message.trim()) return data.message;
  if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
  return fallback;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw new Error(readErrorMessage(payload, "请求失败"));
  }
  return payload as T;
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "未开始";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getActionCount(testCase: TestCase): number {
  if (testCase.kind === "api") {
    const apiSteps = testCase.payload?.apiSteps;
    return Array.isArray(apiSteps) ? apiSteps.length : 0;
  }
  const actions = testCase.payload?.actions;
  return Array.isArray(actions) ? actions.length : 0;
}

type TestMode = "ui-automation" | "api-automation" | "ui-locator";

function parsePayloadObject(text: string): Record<string, unknown> {
  const raw = text.trim() || "{}";
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("UI payload 必须是 JSON 对象");
  }
  return parsed as Record<string, unknown>;
}

export function AutoTestWorkbench({
  initialCases,
  initialRuns,
  projects,
  initialMode = "ui-automation",
}: {
  initialCases: TestCase[];
  initialRuns: TestRun[];
  projects: Project[];
  initialMode?: TestMode;
}) {
  const [testMode, setTestMode] = useState<TestMode>(initialMode);
  const [uiCases, setUiCases] = useState<TestCase[]>(initialCases);
  const [runs, setRuns] = useState<TestRun[]>(initialRuns);
  const [apiCases, setApiCases] = useState<TestCase[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("all");
  const [notice, setNotice] = useState<Notice>(null);
  const [runningCaseId, setRunningCaseId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingApiCases, setIsLoadingApiCases] = useState(false);
  const [isSequential, setIsSequential] = useState(true);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [isBulkDeletingRuns, setIsBulkDeletingRuns] = useState(false);
  const [caseScrollTop, setCaseScrollTop] = useState(0);
  const [runScrollTop, setRunScrollTop] = useState(0);
  const runEventSourcesRef = useRef<Map<string, EventSource>>(new Map());
  const [isCaseEditorOpen, setIsCaseEditorOpen] = useState(false);
  const [uiEditorMode, setUiEditorMode] = useState<UiEditorMode>("create");
  const [uiEditorCaseId, setUiEditorCaseId] = useState("");
  const [uiEditorTitle, setUiEditorTitle] = useState("");
  const [uiEditorObjective, setUiEditorObjective] = useState("");
  const [uiEditorProjectId, setUiEditorProjectId] = useState(initialCases[0]?.projectId ?? projects[0]?.id ?? "");
  const [uiEditorSpecId, setUiEditorSpecId] = useState("");
  const [uiEditorPayloadText, setUiEditorPayloadText] = useState("{}");
  const [uiSaveTargetCaseId, setUiSaveTargetCaseId] = useState("");
  const [isSavingUiCase, setIsSavingUiCase] = useState(false);
  const [deletingCaseId, setDeletingCaseId] = useState<string | null>(null);
  const [uiEditorSpecs, setUiEditorSpecs] = useState<SourceSpec[]>([]);
  const [isLoadingUiSpecs, setIsLoadingUiSpecs] = useState(false);

  // UI Locator State
  const [locatorPayload, setLocatorPayload] = useState("{}");

  const projectNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects) {
      map.set(project.id, project.name);
    }
    return map;
  }, [projects]);

  const filteredCases = useMemo(() => {
    if (selectedProjectId === "all") return uiCases;
    return uiCases.filter((item) => item.projectId === selectedProjectId);
  }, [uiCases, selectedProjectId]);

  const filteredApiCases = useMemo(() => {
    if (selectedProjectId === "all") return apiCases;
    return apiCases.filter((item) => item.projectId === selectedProjectId);
  }, [apiCases, selectedProjectId]);

  const caseMap = useMemo(() => {
    const map = new Map<string, TestCase>();
    for (const item of uiCases) {
      map.set(item.id, item);
    }
    for (const item of apiCases) {
      map.set(item.id, item);
    }
    return map;
  }, [uiCases, apiCases]);

  const activeRunIds = useMemo(
    () => runs.filter((item) => item.status === "queued" || item.status === "running").map((item) => item.id),
    [runs],
  );
  const visibleRuns = useMemo(
    () => runs.filter((r) => r.runnerType === (testMode === "ui-automation" ? "ui" : "api")),
    [runs, testMode],
  );
  const activeCases = useMemo(
    () => (testMode === "ui-automation" ? filteredCases : filteredApiCases),
    [filteredApiCases, filteredCases, testMode],
  );
  const caseWindow = useMemo(
    () => computeVirtualWindow(activeCases.length, caseScrollTop, 132, 560, 4),
    [activeCases.length, caseScrollTop],
  );
  const runWindow = useMemo(
    () => computeVirtualWindow(visibleRuns.length, runScrollTop, 98, 560, 4),
    [runScrollTop, visibleRuns.length],
  );
  const isProjectContextLocked = selectedProjectId !== "all";
  const currentProjectName = isProjectContextLocked ? (projectNameMap.get(selectedProjectId) ?? selectedProjectId) : "";

  const refreshRuns = useCallback(async (targetIds?: string[]) => {
    const ids = (targetIds ?? activeRunIds).filter(Boolean);
    if (ids.length === 0) return;
    setIsRefreshing(true);
    try {
      const latestRuns = await Promise.all(
        ids.map((id) => requestJson<TestRun>(`/api/runs/${encodeURIComponent(id)}`)),
      );
      const latestMap = new Map(latestRuns.map((item) => [item.id, item]));
      setRuns((prev) => prev.map((item) => latestMap.get(item.id) ?? item));
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "刷新运行状态失败" });
    } finally {
      setIsRefreshing(false);
    }
  }, [activeRunIds]);

  useEffect(() => {
    const sourceMap = runEventSourcesRef.current;
    const activeSet = new Set(activeRunIds);

    for (const [runId, source] of Array.from(sourceMap.entries())) {
      if (!activeSet.has(runId)) {
        source.close();
        sourceMap.delete(runId);
      }
    }

    for (const runId of activeRunIds) {
      if (sourceMap.has(runId)) continue;
      const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
      const onStatus = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data) as TestRun;
          setRuns((prev) => prev.map((item) => (item.id === runId ? { ...item, ...data } : item)));
          const status = String((data as { status?: unknown }).status || "").toLowerCase();
          if (status === "passed" || status === "failed" || status === "cancelled") {
            source.close();
            sourceMap.delete(runId);
          }
        } catch {
          // ignore malformed event chunk
        }
      };
      source.addEventListener("status", onStatus as EventListener);
      source.onerror = () => {
        source.close();
        sourceMap.delete(runId);
      };
      sourceMap.set(runId, source);
    }
  }, [activeRunIds]);

  useEffect(() => {
    const sourceMap = runEventSourcesRef.current;
    return () => {
      for (const source of sourceMap.values()) {
        source.close();
      }
      sourceMap.clear();
    };
  }, []);

  useEffect(() => {
    if (!isCaseEditorOpen) return;
    if (uiEditorMode !== "create") return;
    if (selectedProjectId === "all") return;
    setUiEditorProjectId(selectedProjectId);
  }, [isCaseEditorOpen, selectedProjectId, uiEditorMode]);

  useEffect(() => {
    if (!isCaseEditorOpen) return;
    if (!uiEditorProjectId) {
      setUiEditorSpecs([]);
      setUiEditorSpecId("");
      return;
    }
    let cancelled = false;
    const loadSpecs = async () => {
      setIsLoadingUiSpecs(true);
      try {
        const rows = await requestJson<SourceSpec[]>(
          `/api/specs?projectId=${encodeURIComponent(uiEditorProjectId)}`,
        );
        if (cancelled) return;
        const list = Array.isArray(rows) ? rows : [];
        setUiEditorSpecs(list);
        if (list.length === 0) {
          setUiEditorSpecId("");
          return;
        }
        const hasCurrent = list.some((item) => item.id === uiEditorSpecId);
        if (!hasCurrent) {
          setUiEditorSpecId(list[0]?.id || "");
        }
      } catch {
        if (cancelled) return;
        setUiEditorSpecs([]);
      } finally {
        if (!cancelled) {
          setIsLoadingUiSpecs(false);
        }
      }
    };
    void loadSpecs();
    return () => {
      cancelled = true;
    };
  }, [isCaseEditorOpen, uiEditorProjectId, uiEditorSpecId]);

  const loadApiCases = useCallback(async () => {
    setIsLoadingApiCases(true);
    try {
      const resp = await requestJson<TestCaseListResponse>(
        `/api/cases/search?kind=api&page=1&pageSize=40&sortBy=updatedAt&sortOrder=desc`
      );
      setApiCases(resp.items || []);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载 API 用例失败" });
    } finally {
      setIsLoadingApiCases(false);
    }
  }, []);

  useEffect(() => {
    if (testMode === "api-automation" && apiCases.length === 0) {
      void loadApiCases();
    }
  }, [apiCases.length, loadApiCases, testMode]);

  const loadUiCases = async () => {
    try {
      const resp = await requestJson<TestCaseListResponse>(
        `/api/cases/search?kind=ui&page=1&pageSize=40&sortBy=updatedAt&sortOrder=desc`
      );
      setUiCases(resp.items || []);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载 UI 用例失败" });
    }
  };

  const openUiCreateEditor = () => {
    const defaultProjectId = selectedProjectId !== "all" ? selectedProjectId : projects[0]?.id ?? "";
    setUiEditorMode("create");
    setUiEditorCaseId("");
    setUiEditorTitle("UI 自动化用例");
    setUiEditorObjective("覆盖核心交互流程");
    setUiEditorProjectId(defaultProjectId);
    setUiEditorSpecId("");
    setUiEditorPayloadText("{}");
    setUiSaveTargetCaseId("");
    setIsCaseEditorOpen(true);
  };

  const openLocatorPayloadSaveEditor = () => {
    const defaultProjectId = selectedProjectId !== "all" ? selectedProjectId : projects[0]?.id ?? "";
    setUiEditorMode("create");
    setUiEditorCaseId("");
    setUiEditorTitle("UI 自动化用例");
    setUiEditorObjective("从元素定位编排生成");
    setUiEditorProjectId(defaultProjectId);
    setUiEditorSpecId("");
    setUiEditorPayloadText(locatorPayload?.trim() ? locatorPayload : "{}");
    setUiSaveTargetCaseId("");
    setIsCaseEditorOpen(true);
  };

  const openUiEditEditor = (testCase: TestCase) => {
    setUiEditorMode("update");
    setUiEditorCaseId(testCase.id);
    setUiEditorTitle(testCase.title || "UI 自动化用例");
    setUiEditorObjective(testCase.objective || "覆盖核心交互流程");
    setUiEditorProjectId(testCase.projectId || projects[0]?.id || "");
    setUiEditorSpecId(testCase.specId || "");
    setUiEditorPayloadText(JSON.stringify(testCase.payload || {}, null, 2));
    setUiSaveTargetCaseId(testCase.id);
    setIsCaseEditorOpen(true);
  };

  const deleteCase = async (caseId: string) => {
    if (!caseId) return;
    if (!window.confirm("确认删除这条 UI 自动化用例吗？删除后不可恢复。")) return;
    setDeletingCaseId(caseId);
    try {
      await requestJson(`/api/cases/${encodeURIComponent(caseId)}`, { method: "DELETE" });
      await loadUiCases();
      setNotice({ kind: "success", text: "UI 用例已删除" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "删除 UI 用例失败" });
    } finally {
      setDeletingCaseId(null);
    }
  };

  const submitUiCase = async () => {
    setIsSavingUiCase(true);
    try {
      const title = uiEditorTitle.trim();
      if (!title) {
        throw new Error("用例标题不能为空");
      }
      if (!uiEditorProjectId) {
        throw new Error("请先选择项目");
      }
      const payloadObject = parsePayloadObject(uiEditorPayloadText);
      const targetCaseId = uiSaveTargetCaseId || uiEditorCaseId;
      const existing = targetCaseId ? uiCases.find((item) => item.id === targetCaseId) : null;
      const targetSpecId = uiEditorSpecId || existing?.specId || "";
      const body = {
        projectId: uiEditorProjectId,
        specId: targetSpecId,
        kind: "ui",
        title,
        objective: uiEditorObjective.trim() || "覆盖核心交互流程",
        steps: existing?.steps || [],
        assertionHints: existing?.assertionHints || [],
        payload: payloadObject,
      };

      if ((uiEditorMode === "update" || !!uiSaveTargetCaseId) && targetCaseId) {
        await requestJson(`/api/cases/${encodeURIComponent(targetCaseId)}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        setNotice({ kind: "success", text: "UI 用例已更新" });
      } else {
        await requestJson("/api/cases", {
          method: "POST",
          body: JSON.stringify(body),
        });
        setNotice({ kind: "success", text: "UI 用例已创建" });
      }
      await loadUiCases();
      setIsCaseEditorOpen(false);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "保存 UI 用例失败" });
    } finally {
      setIsSavingUiCase(false);
    }
  };

  const loadRecentRuns = async () => {
    try {
      const resp = await requestJson<TestRun[]>(`/api/runs?limit=40`);
      setRuns(resp || []);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载运行流水线失败" });
    }
  };

  useEffect(() => {
    const handler = () => {
      void loadUiCases();
      void loadApiCases();
      void loadRecentRuns();
    };
    window.addEventListener("platform-data-refresh", handler as EventListener);
    return () => window.removeEventListener("platform-data-refresh", handler as EventListener);
  }, [loadApiCases]);

  const runCase = async (testCase: TestCase) => {
    setRunningCaseId(testCase.id);
    setNotice(null);
    try {
      const run = await requestJson<TestRun>("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          caseId: testCase.id,
          projectId: testCase.projectId,
          runnerType: testCase.kind,
          sequential: testCase.kind === 'api' ? isSequential : false,
        }),
      });
      setRuns((prev) => [run, ...prev].slice(0, 50));
      setNotice({ kind: "success", text: `正在启动执行：${testCase.title}` });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "启动任务失败" });
    } finally {
      setRunningCaseId(null);
    }
  };

  const deleteRun = async (runId: string) => {
    if (!runId) return;
    if (!window.confirm("确认删除这条流水线记录吗？删除后不可恢复。")) return;
    setDeletingRunId(runId);
    try {
      await requestJson(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
      setRuns((prev) => prev.filter((item) => item.id !== runId));
      setNotice({ kind: "success", text: "流水线记录已删除" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "删除运行记录失败" });
    } finally {
      setDeletingRunId(null);
    }
  };

  const bulkDeleteVisibleRuns = async () => {
    if (visibleRuns.length === 0) {
      setNotice({ kind: "error", text: "当前没有可删除的流水线记录" });
      return;
    }
    const targetIds = visibleRuns.map((item) => item.id);
    if (
      !window.confirm(
        `确认批量删除当前可见的 ${targetIds.length} 条流水线记录吗？删除后不可恢复。`,
      )
    ) {
      return;
    }
    setIsBulkDeletingRuns(true);
    try {
      const result = await requestJson<{ deleted: number; failedIds: string[] }>(
        "/api/runs/batch-delete",
        {
          method: "POST",
          body: JSON.stringify({ ids: targetIds }),
        },
      );
      const failedIds = Array.isArray(result?.failedIds) ? result.failedIds : [];
      const successIds = targetIds.filter((id) => !failedIds.includes(id));
      const failedCount = failedIds.length;
      setRuns((prev) => prev.filter((item) => !successIds.includes(item.id)));
      if (failedCount === 0) {
        setNotice({ kind: "success", text: `已批量删除 ${successIds.length} 条记录` });
      } else {
        setNotice({
          kind: "error",
          text: `已删除 ${successIds.length} 条，失败 ${failedCount} 条（可重试）`,
        });
      }
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "批量删除失败" });
    } finally {
      setIsBulkDeletingRuns(false);
    }
  };

  return (
    <div style={workbenchContainerStyle}>
      <nav style={navBarStyle}>
        <div style={tabGroupStyle}>
          <button style={testMode === "ui-automation" ? activeTabStyle : tabButtonStyle} onClick={() => setTestMode("ui-automation")}><Layers size={18} />UI 自动化测试</button>
          <button style={testMode === "api-automation" ? activeTabStyle : tabButtonStyle} onClick={() => setTestMode("api-automation")}><Activity size={18} />API 自动化测试</button>
          <button style={testMode === "ui-locator" ? activeTabStyle : tabButtonStyle} onClick={() => setTestMode("ui-locator")}><Compass size={18} />UI 元素定位</button>
        </div>

        {testMode !== "ui-locator" && (
          <div style={filterActionRowStyle}>
            {testMode === "api-automation" && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '.88rem', color: 'var(--ink-soft)', cursor: 'pointer', marginRight: 12 }}>
                <input type="checkbox" checked={isSequential} onChange={(e) => setIsSequential(e.target.checked)} /> 顺序执行模式
              </label>
            )}
            <select value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)} style={fieldStyle}>
              <option value="all">所有项目</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
        )}
      </nav>

      {notice && <div style={{ padding: "0 24px 12px 24px" }}><div style={{ ...noticeStyle, ...(notice.kind === "success" ? noticeSuccessStyle : noticeErrorStyle) }}>{notice.text}</div></div>}

      <div style={workspaceMainStyle}>
        {(testMode === "ui-automation" || testMode === "api-automation") && (
          <div style={uiAutomationGridStyle}>
            <div className="glassboard" style={panelStyle}>
              <div style={panelHeadStyle}>
                <div>
                  <div style={kickerStyle}>{testMode === "ui-automation" ? "UI Testing" : "API Testing"}</div>
                  <h2 style={panelTitleStyle}>{testMode === "ui-automation" ? "UI 自动化用例库" : "接口自动化测试库"}</h2>
                </div>
                {testMode === "ui-automation" ? (
                  <button type="button" style={primaryBtnStyle} onClick={openUiCreateEditor}>
                    <Plus size={16} />
                    新建用例
                  </button>
                ) : null}
              </div>
              <div
                style={{ overflowY: "auto", minHeight: 0, maxHeight: 560, paddingRight: 4 }}
                onScroll={(event) => setCaseScrollTop(event.currentTarget.scrollTop)}
              >
                {isLoadingApiCases && <div style={emptyStateStyle}>正在加载 API 用例...</div>}
                {activeCases.length > 0 ? (
                  <div style={{ height: caseWindow.totalHeight, position: "relative" }}>
                    <div style={{ transform: `translateY(${caseWindow.offsetTop}px)` }}>
                      {activeCases.slice(caseWindow.start, caseWindow.end).map((testCase) => (
                        <div key={testCase.id} style={{ height: 132, paddingBottom: 12, boxSizing: "border-box" }}>
                          <article style={caseCardStyle}>
                            <div style={{ display: "grid", gap: 6 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <strong style={{ fontSize: "1rem" }}>{testCase.title}</strong>
                                <span style={lightBadgeStyle}>{projectNameMap.get(testCase.projectId) || testCase.projectId}</span>
                              </div>
                              <div style={metaTextStyle}>{testCase.objective}</div>
                              <div style={metaTextStyle}>{testCase.kind === 'api' ? `接口数：${getActionCount(testCase)}` : `动作数：${getActionCount(testCase)}`}</div>
                            </div>
                            <button type="button" style={primaryBtnStyle} onClick={() => void runCase(testCase)} disabled={runningCaseId === testCase.id}>
                              {runningCaseId === testCase.id ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} 运行
                            </button>
                            {testMode === "ui-automation" ? (
                              <div style={{ display: "flex", gap: 6 }}>
                                <button
                                  type="button"
                                  style={miniBtnStyle}
                                  onClick={() => openUiEditEditor(testCase)}
                                >
                                  <Edit3 size={14} />
                                  编辑
                                </button>
                                <button
                                  type="button"
                                  style={{ ...miniBtnStyle, color: "#b91c1c", background: "rgba(254,242,242,.9)" }}
                                  onClick={() => void deleteCase(testCase.id)}
                                  disabled={deletingCaseId === testCase.id}
                                >
                                  {deletingCaseId === testCase.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                                  删除
                                </button>
                              </div>
                            ) : null}
                          </article>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  !isLoadingApiCases && <div style={emptyStateStyle}>暂无相关用例。</div>
                )}
              </div>
            </div>

            <div className="glassboard" style={panelStyle}>
              <div style={panelHeadStyle}>
                <div><div style={kickerStyle}>History</div><h2 style={panelTitleStyle}>运行流水线</h2></div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    style={{ ...secondaryBtnStyle, width: "auto", padding: "0 10px", color: "#b91c1c" }}
                    onClick={() => void bulkDeleteVisibleRuns()}
                    disabled={isBulkDeletingRuns || visibleRuns.length === 0}
                    title="删除当前页签下可见的所有记录"
                  >
                    {isBulkDeletingRuns ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    批量删除
                  </button>
                  <button style={secondaryBtnStyle} onClick={() => void refreshRuns()} disabled={isRefreshing}>
                    <RefreshCcw size={14} className={isRefreshing ? "animate-spin" : ""} />
                  </button>
                </div>
              </div>
              <div
                style={{ overflowY: "auto", minHeight: 0, maxHeight: 560, paddingRight: 4 }}
                onScroll={(event) => setRunScrollTop(event.currentTarget.scrollTop)}
              >
                {visibleRuns.length > 0 ? (
                  <div style={{ height: runWindow.totalHeight, position: "relative" }}>
                    <div style={{ transform: `translateY(${runWindow.offsetTop}px)` }}>
                      {visibleRuns.slice(runWindow.start, runWindow.end).map((run) => (
                        <div key={run.id} style={{ height: 98, paddingBottom: 10, boxSizing: "border-box" }}>
                          <article style={runCardStyle}>
                            <div style={{ display: "grid", gap: 4 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <strong style={{ fontSize: ".92rem" }}>{caseMap.get(run.caseId)?.title ?? "批量任务"}</strong>
                                <span style={{ ...badgeStyle, ...(run.status === "passed" ? badgePassedStyle : run.status === "failed" ? badgeFailedStyle : badgeQueuedStyle) }}>
                                  {run.status === "passed" ? "通过" : run.status === "failed" ? "失败" : "就绪"}
                                </span>
                              </div>
                              <div style={{ ...metaTextStyle, fontSize: ".82rem" }}>{formatTime(run.startedAt)}</div>
                            </div>
                            <div style={{ display: "flex", gap: 6 }}>
                              <Link href={`/runs/${run.id}`} style={miniBtnStyle}>记录</Link>
                              <Link href={`/reports/${run.id}`} style={miniBtnStyle}>报告</Link>
                              <button
                                type="button"
                                style={{ ...miniBtnStyle, color: "#b91c1c", background: "rgba(254,242,242,.9)" }}
                                onClick={() => void deleteRun(run.id)}
                                disabled={deletingRunId === run.id}
                              >
                                {deletingRunId === run.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                                删除
                              </button>
                            </div>
                          </article>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div style={emptyStateStyle}>暂无记录。</div>
                )}
              </div>
            </div>
          </div>
        )}

        {testMode === "ui-locator" && (
          <div style={integratedSubViewStyle}>
            <div style={locatorToolbarStyle}>
              <div style={{ display: "grid", gap: 2 }}>
                <strong style={{ fontSize: ".92rem" }}>UI 元素定位编排</strong>
                <span style={{ fontSize: ".8rem", color: "var(--ink-soft)" }}>可直接保存到 UI 自动化用例（新建或覆盖已有）。</span>
              </div>
              <button type="button" style={primaryBtnStyle} onClick={openLocatorPayloadSaveEditor}>
                <Save size={16} />
                保存到 UI 用例
              </button>
            </div>
            <UiCaseBuilder value={locatorPayload} onChange={setLocatorPayload} />
          </div>
        )}
      </div>

      {isCaseEditorOpen ? (
        <div style={modalBackdropStyle}>
          <div style={modalCardStyle}>
            <div style={modalHeaderStyle}>
              <strong>{uiEditorMode === "create" ? "新建 UI 自动化用例" : "编辑 UI 自动化用例"}</strong>
              <button type="button" style={secondaryBtnStyle} onClick={() => setIsCaseEditorOpen(false)}>
                <X size={14} />
              </button>
            </div>
            <div style={editorFormStyle}>
              {uiEditorMode === "create" ? (
                <label style={editorLabelStyle}>
                  保存目标
                  <select
                    value={uiSaveTargetCaseId}
                    onChange={(event) => {
                      const targetId = event.target.value;
                      setUiSaveTargetCaseId(targetId);
                      if (!targetId) return;
                      const target = uiCases.find((item) => item.id === targetId);
                      if (!target) return;
                      setUiEditorProjectId(target.projectId || uiEditorProjectId);
                      setUiEditorSpecId(target.specId || "");
                      setUiEditorTitle(target.title || uiEditorTitle);
                      setUiEditorObjective(target.objective || uiEditorObjective);
                    }}
                    style={fieldStyle}
                  >
                    <option value="">新建用例</option>
                    {uiCases.map((item) => (
                      <option key={item.id} value={item.id}>
                        覆盖：{item.title}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label style={editorLabelStyle}>
                用例标题
                <input
                  value={uiEditorTitle}
                  onChange={(event) => setUiEditorTitle(event.target.value)}
                  style={fieldStyle}
                  placeholder="例如：登录并创建资产"
                />
              </label>
              <label style={editorLabelStyle}>
                目标项目
                <select
                  value={uiEditorProjectId}
                  onChange={(event) => {
                    setUiEditorProjectId(event.target.value);
                    setUiEditorSpecId("");
                  }}
                  style={fieldStyle}
                  disabled={isProjectContextLocked}
                >
                  <option value="">请选择项目</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
                {isProjectContextLocked ? (
                  <span style={{ fontSize: ".8rem", color: "var(--ink-soft)" }}>
                    当前按项目筛选：{currentProjectName}，新建用例将自动关联该项目。
                  </span>
                ) : null}
              </label>
              <label style={editorLabelStyle}>
                关联需求文档
                <select
                  value={uiEditorSpecId}
                  onChange={(event) => setUiEditorSpecId(event.target.value)}
                  style={fieldStyle}
                  disabled={!uiEditorProjectId || isLoadingUiSpecs}
                >
                  <option value="">
                    {!uiEditorProjectId
                      ? "请先选择项目"
                      : isLoadingUiSpecs
                        ? "需求文档加载中..."
                        : uiEditorSpecs.length === 0
                          ? "当前项目暂无需求文档（可不关联）"
                          : "请选择需求文档（可选）"}
                  </option>
                  {uiEditorSpecs.map((spec) => (
                    <option key={spec.id} value={spec.id}>
                      {spec.title}
                    </option>
                  ))}
                </select>
              </label>
              <label style={editorLabelStyle}>
                目标说明
                <input
                  value={uiEditorObjective}
                  onChange={(event) => setUiEditorObjective(event.target.value)}
                  style={fieldStyle}
                  placeholder="覆盖核心交互流程"
                />
              </label>
              <div style={{ border: "1px solid var(--line)", borderRadius: 12, padding: 10, background: "rgba(255,255,255,.72)" }}>
                <UiCaseBuilder value={uiEditorPayloadText} onChange={setUiEditorPayloadText} />
              </div>
            </div>
            <div style={modalActionStyle}>
              <button type="button" style={secondaryBtnStyle} onClick={() => setIsCaseEditorOpen(false)}>取消</button>
              <button type="button" style={primaryBtnStyle} onClick={() => void submitUiCase()} disabled={isSavingUiCase}>
                {isSavingUiCase ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                {uiEditorMode === "create" ? (uiSaveTargetCaseId ? "保存到所选用例" : "保存到新用例") : "保存到当前用例"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// --------------------------------------------------------------------------------
// Styles
// --------------------------------------------------------------------------------

const workbenchContainerStyle: CSSProperties = { display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-main)" };
const navBarStyle: CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid var(--line)", background: "var(--panel)", flexShrink: 0 };
const tabGroupStyle: CSSProperties = { display: "flex", gap: 12 };
const tabButtonStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 8, height: "38px", padding: "0 16px", borderRadius: "10px", borderWidth: 1, borderStyle: "solid", borderColor: "var(--line)", background: "transparent", color: "var(--ink-soft)", fontSize: ".9rem", fontWeight: 600, cursor: "pointer" };
const activeTabStyle: CSSProperties = { ...tabButtonStyle, background: "var(--primary)", color: "white", borderColor: "var(--primary)", boxShadow: "0 4px 12px var(--primary-alpha-20)" };
const filterActionRowStyle: CSSProperties = { display: "flex", gap: 12, alignItems: "center" };
const workspaceMainStyle: CSSProperties = { flex: 1, padding: "20px 24px", overflow: "hidden", display: "flex", flexDirection: "column" };
const uiAutomationGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  gap: 20,
  height: "100%",
  minHeight: 0,
};
const integratedSubViewStyle: CSSProperties = { height: "100%", overflow: "auto", background: "var(--panel)", borderRadius: "16px", border: "1px solid var(--line)" };
const panelStyle: CSSProperties = { padding: "20px", display: "flex", flexDirection: "column", gap: 16, minHeight: 0, overflow: "hidden" };
const panelHeadStyle: CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexShrink: 0 };
const panelTitleStyle: CSSProperties = { margin: "4px 0 0 0", fontSize: "1.1rem", fontWeight: 700 };
const kickerStyle: CSSProperties = { fontSize: ".65rem", letterSpacing: ".1em", textTransform: "uppercase", color: "var(--ink-soft)", fontWeight: 600 };
const fieldStyle: CSSProperties = { height: "36px", borderRadius: "8px", border: "1px solid var(--line)", padding: "0 12px", fontSize: ".88rem", background: "white" };
const caseCardStyle: CSSProperties = { padding: "16px", borderRadius: "12px", background: "white", border: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 };
const runCardStyle: CSSProperties = { padding: "12px 14px", borderRadius: "10px", background: "rgba(255,255,255,.6)", border: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 };
const primaryBtnStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6, height: "36px", padding: "0 14px", borderRadius: "8px", border: "none", background: "var(--primary)", color: "white", fontWeight: 600, fontSize: ".88rem", cursor: "pointer" };
const secondaryBtnStyle: CSSProperties = { display: "inline-flex", alignItems: "center", justifyContent: "center", width: "32px", height: "32px", borderRadius: "8px", border: "1px solid var(--line)", background: "white", cursor: "pointer" };
const miniBtnStyle: CSSProperties = { padding: "4px 10px", borderRadius: "6px", fontSize: ".78rem", fontWeight: 600, background: "rgba(15,23,42,.05)", color: "var(--ink)", border: "none", textDecoration: "none", cursor: "pointer" };
const badgeStyle: CSSProperties = { padding: "2px 8px", borderRadius: "999px", fontSize: ".7rem", fontWeight: 700, background: "rgba(15,23,42,.06)", color: "var(--ink-soft)" };
const lightBadgeStyle: CSSProperties = { ...badgeStyle, background: "rgba(15,23,42,.04)", fontSize: ".75rem" };
const badgePassedStyle: CSSProperties = { background: "rgba(16,185,129,.15)", color: "#10b981" };
const badgeFailedStyle: CSSProperties = { background: "rgba(239,68,68,.12)", color: "#ef4444" };
const badgeQueuedStyle: CSSProperties = { background: "rgba(245,158,11,.12)", color: "#f59e0b" };
const metaTextStyle: CSSProperties = { color: "var(--ink-soft)", fontSize: ".88rem", lineHeight: 1.5 };
const emptyStateStyle: CSSProperties = { padding: "32px", textAlign: "center", color: "var(--ink-soft)", fontSize: ".9rem", border: "1px dashed var(--line)", borderRadius: "12px" };
const noticeStyle: CSSProperties = { padding: "10px 16px", borderRadius: "10px", fontSize: ".88rem", borderWidth: 1, borderStyle: "solid", borderColor: "transparent" };
const noticeSuccessStyle: CSSProperties = { background: "rgba(16,185,129,0.1)", color: "#065f46", borderColor: "rgba(16,185,129,0.2)" };
const noticeErrorStyle: CSSProperties = { background: "rgba(239,68,68,0.08)", color: "#991b1b", borderColor: "rgba(239,68,68,0.2)" };
const modalBackdropStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(2,6,23,.45)",
  display: "grid",
  placeItems: "center",
  zIndex: 1200,
  padding: 18,
};
const modalCardStyle: CSSProperties = {
  width: "min(1180px, 95vw)",
  maxHeight: "92vh",
  overflow: "auto",
  borderRadius: 16,
  border: "1px solid var(--line)",
  background: "var(--panel)",
  padding: 14,
  display: "grid",
  gap: 12,
};
const modalHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};
const editorFormStyle: CSSProperties = {
  display: "grid",
  gap: 10,
};
const editorLabelStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  fontSize: ".88rem",
  color: "var(--ink-soft)",
};
const modalActionStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 8,
};
const locatorToolbarStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "14px 16px",
  borderBottom: "1px solid var(--line)",
  gap: 12,
  position: "sticky",
  top: 0,
  background: "var(--panel)",
  zIndex: 2,
};
