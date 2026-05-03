"use client";

import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import type { Project, SourceSpec, TestCase } from "@ai-test-platform/shared-schema";
import { UiCaseBuilder } from "./ui-case-builder";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Edit3,
  Loader2,
  Plus,
  Save,
  Search,
  Trash2,
  X,
} from "lucide-react";

type CaseFormState = {
  projectId: string;
  specId: string;
  kind: "api" | "ui";
  title: string;
  objective: string;
  stepsText: string;
  assertionHintsText: string;
  payloadText: string;
};

type ModalMode = "create" | "edit";

type CaseSearchResult = {
  items: TestCase[];
  total: number;
  page: number;
  pageSize: number;
  hasNext: boolean;
};

type CaseQueryState = {
  projectFilter: string;
  kindFilter: "all" | "api" | "ui";
  statusFilter: "all" | CaseStatus;
  searchText: string;
};

function parseResponseMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const data = payload as { detail?: unknown; message?: unknown };
  if (typeof data.message === "string" && data.message.trim()) return data.message;
  if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
  return fallback;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (response.status === 204) {
    return undefined as T;
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw new Error(parseResponseMessage(payload, "请求失败"));
  }
  return payload as T;
}

function splitByLine(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinByLine(items: string[]): string {
  return (items || []).join("\n");
}

function formatDate(iso: string): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function mergeSpecs(existing: SourceSpec[], incoming: SourceSpec[]): SourceSpec[] {
  const byId = new Map<string, SourceSpec>();
  for (const item of existing) {
    byId.set(item.id, item);
  }
  for (const item of incoming) {
    byId.set(item.id, item);
  }
  return Array.from(byId.values());
}

function replaceSpecsForProjects(
  existing: SourceSpec[],
  projectIds: string[],
  incoming: SourceSpec[],
): SourceSpec[] {
  const projectSet = new Set(projectIds.map((item) => item.trim()).filter(Boolean));
  if (projectSet.size === 0) return existing;
  const retained = existing.filter((item) => !projectSet.has(item.projectId));
  return mergeSpecs(retained, incoming);
}

function buildEmptyForm(projects: Project[], specs: SourceSpec[]): CaseFormState {
  const projectIdsWithSpecs = new Set(specs.map((item) => item.projectId));
  const firstProjectId =
    projects.find((item) => projectIdsWithSpecs.has(item.id))?.id ?? projects[0]?.id ?? "";
  const firstSpecId = specs.find((item) => item.projectId === firstProjectId)?.id ?? "";
  return {
    projectId: firstProjectId,
    specId: firstSpecId,
    kind: "api",
    title: "",
    objective: "",
    stepsText: "",
    assertionHintsText: "",
    payloadText: "{}",
  };
}

function buildEditForm(testCase: TestCase): CaseFormState {
  return {
    projectId: testCase.projectId,
    specId: testCase.specId,
    kind: testCase.kind,
    title: testCase.title,
    objective: testCase.objective,
    stepsText: joinByLine(testCase.steps || []),
    assertionHintsText: joinByLine(testCase.assertionHints || []),
    payloadText: JSON.stringify(testCase.payload ?? {}, null, 2),
  };
}

type CaseStatus = "unexecuted" | "passed" | "failed" | "blocked";

const caseStatusOptions = [
  { value: "unexecuted", label: "尚未执行" },
  { value: "passed", label: "执行通过" },
  { value: "failed", label: "执行失败" },
  { value: "blocked", label: "条件阻塞" },
];

function getCaseStatusLabel(testCase: TestCase): string {
  const value = (testCase.payload?.status as CaseStatus | undefined) || "unexecuted";
  const option = caseStatusOptions.find(opt => opt.value === value);
  return option?.label || "尚未执行";
}

function getCaseStatusStyle(testCase: TestCase): CSSProperties {
  const value = (testCase.payload?.status as CaseStatus | undefined) || "unexecuted";
  if (value === "passed") {
    return {
      color: "#10b981",
      background: "rgba(16,185,129,.12)",
    };
  }
  if (value === "failed") {
    return {
      color: "#ef4444",
      background: "rgba(239,68,68,.12)",
    };
  }
  if (value === "blocked") {
    return {
      color: "#f59e0b",
      background: "rgba(245,158,11,.12)",
    };
  }
  return {
    color: "#64748b",
    background: "rgba(100,116,139,.12)",
  };
}

async function updateCaseStatus(caseId: string, status: CaseStatus): Promise<void> {
  const caseData = await fetch(`/api/cases/${caseId}`).then(r => r.json());
  const response = await fetch(`/api/cases/${caseId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload: { ...caseData.payload, status } }),
  });
  if (!response.ok) {
    throw new Error("更新状态失败");
  }
}

export function TestCaseTable({
  initialCases,
  initialPage = 1,
  initialPageSize = 20,
  initialTotal,
  initialHasNext = false,
  projects,
  specs,
}: {
  dict?: unknown;
  initialCases: TestCase[];
  initialPage?: number;
  initialPageSize?: number;
  initialTotal?: number;
  initialHasNext?: boolean;
  projects: Project[];
  specs: SourceSpec[];
}) {
  const [cases, setCases] = useState<TestCase[]>(initialCases);
  const [specRows, setSpecRows] = useState<SourceSpec[]>(specs);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [projectFilter, setProjectFilter] = useState<string>("all");
  const [kindFilter, setKindFilter] = useState<"all" | "api" | "ui">("all");
  const [statusFilter, setStatusFilter] = useState<"all" | CaseStatus>("all");
  const [searchText, setSearchText] = useState("");
  const [page, setPage] = useState(initialPage);
  const [pageSize] = useState(initialPageSize);
  const [total, setTotal] = useState(initialTotal ?? initialCases.length);
  const [hasNext, setHasNext] = useState(initialHasNext);
  const [notice, setNotice] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isSpecLoading, setIsSpecLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<ModalMode>("create");
  const [editingCaseId, setEditingCaseId] = useState<string | null>(null);
  const [modalNotice, setModalNotice] = useState("");
  const [form, setForm] = useState<CaseFormState>(() => buildEmptyForm(projects, specs));
    const [isUpdatingStatus, setIsUpdatingStatus] = useState<string | null>(null);
    const [expandedCaseIds, setExpandedCaseIds] = useState<Set<string>>(new Set());
    const [editingStepIndex, setEditingStepIndex] = useState<number | null>(null);
    const [stepFormOpen, setStepFormOpen] = useState(false);
    const [editingCaseIdForStep, setEditingCaseIdForStep] = useState<string | null>(null);
  const specRowsRef = useRef<SourceSpec[]>(specs);
  const specLoadRequestRef = useRef(0);

  const projectNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects) {
      map.set(project.id, project.name);
    }
    return map;
  }, [projects]);

  const specNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const spec of specRows) {
      map.set(spec.id, spec.title);
    }
    return map;
  }, [specRows]);

  const filteredSpecsForForm = useMemo(
    () => specRows.filter((item) => item.projectId === form.projectId),
    [specRows, form.projectId],
  );

  useEffect(() => {
    specRowsRef.current = specRows;
  }, [specRows]);

  const selectedCount = selectedIds.size;

  const resetSelection = () => setSelectedIds(new Set());

  const ensureSpecsForProjects = async (
    projectIds: string[],
    options?: { forceRefresh?: boolean },
  ): Promise<SourceSpec[]> => {
    const uniqueProjectIds = Array.from(new Set(projectIds.map((item) => item.trim()).filter(Boolean)));
    if (uniqueProjectIds.length === 0) {
      return specRowsRef.current;
    }
    const currentSpecs = specRowsRef.current;
    const targetProjectIds = (options?.forceRefresh ? uniqueProjectIds : uniqueProjectIds.filter(
      (projectId) => !currentSpecs.some((item) => item.projectId === projectId),
    ));
    if (targetProjectIds.length === 0) {
      return currentSpecs;
    }
    const loadedGroups = await Promise.all(
      targetProjectIds.map((projectId) =>
        requestJson<SourceSpec[]>(`/api/specs?projectId=${encodeURIComponent(projectId)}`),
      ),
    );
    const replaced = replaceSpecsForProjects(
      specRowsRef.current,
      targetProjectIds,
      loadedGroups.flat(),
    );
    specRowsRef.current = replaced;
    setSpecRows(replaced);
    return replaced;
  };

  useEffect(() => {
    const projectIds = cases.map((item) => item.projectId);
    if (projectIds.length === 0) return;
    void ensureSpecsForProjects(projectIds).catch(() => undefined);
  }, [cases]);

  const loadCases = async (
    targetPage = 1,
    overrides?: Partial<CaseQueryState>,
  ): Promise<CaseSearchResult> => {
    const nextQuery: CaseQueryState = {
      projectFilter,
      kindFilter,
      statusFilter,
      searchText,
      ...overrides,
    };
    const search = new URLSearchParams();
    if (nextQuery.projectFilter !== "all") search.set("projectId", nextQuery.projectFilter);
    if (nextQuery.kindFilter !== "all") search.set("kind", nextQuery.kindFilter);
    if (nextQuery.statusFilter !== "all") search.set("status", nextQuery.statusFilter);
    if (nextQuery.searchText.trim()) search.set("q", nextQuery.searchText.trim());
    search.set("page", String(targetPage));
    search.set("pageSize", String(pageSize));
    search.set("sortBy", "updatedAt");
    search.set("sortOrder", "desc");

    setIsLoading(true);
    setNotice("");
    try {
      const result = await requestJson<CaseSearchResult>(`/api/cases/search?${search.toString()}`);
      setCases(result.items);
      setTotal(result.total);
      setPage(result.page);
      setHasNext(result.hasNext);
      resetSelection();
      void ensureSpecsForProjects(result.items.map((item) => item.projectId)).catch(() => undefined);
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载测试用例失败";
      setNotice(message);
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const openCreateModal = async () => {
    const nextForm = buildEmptyForm(projects, specRowsRef.current);
    setModalMode("create");
    setEditingCaseId(null);
    setModalNotice(projects.length === 0 ? "还没有项目，请先创建项目后再添加用例。" : "");
    setForm(nextForm);
    setModalOpen(true);
    if (nextForm.projectId) {
      void onProjectChange(nextForm.projectId, { preferredSpecId: nextForm.specId, preserveCurrentSpec: true });
    }
  };

  const openEditModal = async (testCase: TestCase) => {
    setModalMode("edit");
    setEditingCaseId(testCase.id);
    setModalNotice("");
    setForm(buildEditForm(testCase));
    setModalOpen(true);
    void onProjectChange(testCase.projectId, {
      preferredSpecId: testCase.specId,
      preserveCurrentSpec: true,
    });
  };

  const closeModal = () => {
    if (isSaving) return;
    specLoadRequestRef.current += 1;
    setIsSpecLoading(false);
    setModalNotice("");
    setModalOpen(false);
  };

  const updateForm = <K extends keyof CaseFormState>(key: K, value: CaseFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const onProjectChange = async (
    projectId: string,
    options?: { preferredSpecId?: string; preserveCurrentSpec?: boolean },
  ) => {
    const requestId = specLoadRequestRef.current + 1;
    specLoadRequestRef.current = requestId;
    const preferredSpecId = options?.preferredSpecId?.trim() ?? "";

    setModalNotice("");
    setForm((prev) => ({
      ...prev,
      projectId,
      specId: options?.preserveCurrentSpec ? preferredSpecId || prev.specId : "",
    }));

    if (!projectId) {
      setIsSpecLoading(false);
      return;
    }

    setIsSpecLoading(true);
    try {
      const resolvedSpecs = await ensureSpecsForProjects([projectId], { forceRefresh: true });
      if (specLoadRequestRef.current !== requestId) {
        return;
      }
      const candidateSpec =
        resolvedSpecs.find((item) => item.projectId === projectId && item.id === preferredSpecId)?.id ??
        resolvedSpecs.find((item) => item.projectId === projectId)?.id ??
        "";
      setForm((prev) => {
        if (prev.projectId !== projectId) return prev;
        return {
          ...prev,
          specId: candidateSpec,
        };
      });
      if (!candidateSpec) {
        setModalNotice("当前项目下还没有需求文档，请先在项目中创建需求文档后再添加用例。");
      }
    } catch (error) {
      if (specLoadRequestRef.current !== requestId) {
        return;
      }
      setModalNotice(error instanceof Error ? error.message : "加载需求文档失败");
    } finally {
      if (specLoadRequestRef.current === requestId) {
        setIsSpecLoading(false);
      }
    }
  };

  const buildPayloadFromForm = () => {
    const title = form.title.trim();
    if (!title) {
      throw new Error("用例标题不能为空");
    }
    if (!form.projectId) {
      throw new Error("请选择项目");
    }
    if (!form.specId) {
      throw new Error("请选择需求文档");
    }
    let payloadObject: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(form.payloadText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("payload 需为 JSON 对象");
      }
      payloadObject = parsed as Record<string, unknown>;
    } catch (error) {
      throw new Error(error instanceof Error ? error.message : "payload JSON 解析失败");
    }
    return {
      projectId: form.projectId,
      specId: form.specId,
      kind: form.kind,
      title,
      objective: form.objective.trim(),
      steps: splitByLine(form.stepsText),
      assertionHints: splitByLine(form.assertionHintsText),
      payload: payloadObject,
    };
  };

  const submitCase = async () => {
    setIsSaving(true);
    setModalNotice("");
    try {
      const body = buildPayloadFromForm();
      if (modalMode === "create") {
        await requestJson<TestCase>("/api/cases", {
          method: "POST",
          body: JSON.stringify(body),
        });
        setProjectFilter(body.projectId);
        setKindFilter("all");
        setSearchText("");
        await loadCases(1, {
          projectFilter: body.projectId,
          kindFilter: "all",
          searchText: "",
        });
        setNotice("测试用例创建成功");
      } else if (editingCaseId) {
        await requestJson<TestCase>(`/api/cases/${editingCaseId}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        await loadCases(page);
        setNotice("测试用例更新成功");
      }
      setModalOpen(false);
      resetSelection();
    } catch (error) {
      const message = error instanceof Error ? error.message : "保存测试用例失败";
      setModalNotice(message);
      setNotice(message);
    } finally {
      setIsSaving(false);
    }
  };

  const deleteOneCase = async (id: string) => {
    if (!confirm("确认删除该测试用例吗？")) return;
    setIsDeleting(true);
    try {
      await requestJson<void>(`/api/cases/${id}`, { method: "DELETE" });
      const nextPage = cases.length === 1 && page > 1 ? page - 1 : page;
      await loadCases(nextPage);
      setNotice("测试用例删除成功");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除测试用例失败");
    } finally {
      setIsDeleting(false);
    }
  };

  const batchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`确认删除选中的 ${selectedIds.size} 条测试用例吗？`)) return;
    setIsDeleting(true);
    try {
      const caseIds = Array.from(selectedIds);
      const deletedOnCurrentPage = cases.filter((item) => selectedIds.has(item.id)).length;
      const result = await requestJson<{ deleted: number }>("/api/cases/batch-delete", {
        method: "POST",
        body: JSON.stringify({ caseIds }),
      });
      const nextPage = cases.length - deletedOnCurrentPage <= 0 && page > 1 ? page - 1 : page;
      await loadCases(nextPage);
      setNotice(`已删除 ${result.deleted} 条测试用例`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "批量删除失败");
    } finally {
      setIsDeleting(false);
    }
  };

  const handleStatusChange = async (caseId: string, status: CaseStatus) => {
    setIsUpdatingStatus(caseId);
    try {
      await updateCaseStatus(caseId, status);
      await loadCases(page);
      setNotice("状态更新成功");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "状态更新失败");
    } finally {
      setIsUpdatingStatus(null);
    }
  };

  const deleteStep = async (caseId: string, stepIndex: number) => {
    if (!confirm("确认删除该步骤吗？")) return;
    try {
      const caseItem = cases.find((c) => c.id === caseId);
      if (!caseItem) return;
      const apiSteps: Array<Record<string, unknown>> = Array.isArray(caseItem.payload?.apiSteps)
        ? [...caseItem.payload.apiSteps]
        : [];
      apiSteps.splice(stepIndex, 1);
      const updatedPayload = { ...caseItem.payload, apiSteps };
      await requestJson<void>(`/api/cases/${caseId}`, {
        method: "PATCH",
        body: JSON.stringify({ payload: updatedPayload }),
      });
      await loadCases(page);
      setNotice("步骤已删除");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除步骤失败");
    }
  };

  const toggleSelectAllCurrentPage = (checked: boolean) => {
    const idsOnPage = cases.map((item) => item.id);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        idsOnPage.forEach((id) => next.add(id));
      } else {
        idsOnPage.forEach((id) => next.delete(id));
      }
      return next;
    });
  };

  const allPageSelected = cases.length > 0 && cases.every((item) => selectedIds.has(item.id));

  return (
    <article className="panel panel-table" style={containerStyle}>
      <div style={toolbarStyle}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button style={primaryBtnStyle} onClick={() => void openCreateModal()}>
            <Plus size={16} />
            添加用例
          </button>
          <button
            style={dangerBtnStyle}
            onClick={() => void batchDelete()}
            disabled={selectedCount === 0 || isDeleting}
          >
            {isDeleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            批量删除 ({selectedCount})
          </button>
        </div>
        <div style={{ fontSize: ".9rem", color: "var(--ink-soft)" }}>共 {total} 条</div>
      </div>

      <div style={filterBarStyle}>
        <select value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)} style={inputStyle}>
          <option value="all">全部项目</option>
          {projects.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          value={kindFilter}
          onChange={(event) => setKindFilter(event.target.value as "all" | "api" | "ui")}
          style={inputStyle}
        >
          <option value="all">全部类型</option>
          <option value="api">API</option>
          <option value="ui">UI</option>
        </select>
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as "all" | CaseStatus)}
          style={inputStyle}
        >
          <option value="all">全部状态</option>
          {caseStatusOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <input
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void loadCases(1);
            }
          }}
          placeholder="搜索标题、目标、步骤..."
          style={{ ...inputStyle, minWidth: 240, flex: 1 }}
        />
        <button style={secondaryBtnStyle} onClick={() => void loadCases(1)} disabled={isLoading}>
          {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          查询
        </button>
      </div>

      {notice ? <div style={noticeStyle}>{notice}</div> : null}

      <div style={{ overflow: "auto", flex: 1 }}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thCheckboxStyle}>
                <input
                  type="checkbox"
                  checked={allPageSelected}
                  onChange={(event) => toggleSelectAllCurrentPage(event.target.checked)}
                />
              </th>
              <th style={thStyle}>用例标题</th>
              <th style={thStyle}>类型</th>
              <th style={thStyle}>项目</th>
              <th style={thStyle}>需求文档</th>
              <th style={thStyle}>状态</th>
              <th style={thStyle}>创建时间</th>
              <th style={thStyle}>操作</th>
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr>
                <td colSpan={8} style={emptyRowStyle}>
                  {isLoading ? "加载中..." : "暂无测试用例"}
                </td>
              </tr>
            ) : (
              cases.map((item) => {
                const isExpanded = expandedCaseIds.has(item.id);
                const apiSteps: Array<Record<string, unknown>> = Array.isArray(item.payload?.apiSteps)
                  ? item.payload.apiSteps
                  : [];
                return (
                  <>
                    <tr key={item.id}>
                      <td style={tdCheckboxStyle}>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(item.id)}
                          onChange={() =>
                            setSelectedIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(item.id)) {
                                next.delete(item.id);
                              } else {
                                next.add(item.id);
                              }
                              return next;
                            })
                          }
                        />
                      </td>
                      <td style={tdTitleStyle}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          {item.kind === "api" && apiSteps.length > 0 && (
                            <button
                              onClick={() =>
                                setExpandedCaseIds((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(item.id)) {
                                    next.delete(item.id);
                                  } else {
                                    next.add(item.id);
                                  }
                                  return next;
                                })
                              }
                              style={{
                                border: "none",
                                background: "transparent",
                                cursor: "pointer",
                                padding: 2,
                                display: "flex",
                                alignItems: "center",
                              }}
                            >
                              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </button>
                          )}
                          <div>
                            <div style={{ fontWeight: 600 }}>{item.title}</div>
                            <div style={{ fontSize: ".78rem", color: "var(--ink-soft)" }}>{item.id}</div>
                          </div>
                        </div>
                      </td>
                      <td style={tdStyle}>
                        {item.kind.toUpperCase()}
                        {item.kind === "api" && apiSteps.length > 0 && (
                          <span style={{ marginLeft: 4, fontSize: ".7rem", color: "var(--ink-soft)" }}>
                            ({apiSteps.length} 步骤)
                          </span>
                        )}
                      </td>
                      <td style={tdStyle}>{projectNameMap.get(item.projectId) || item.projectId}</td>
                      <td style={tdStyle}>{specNameMap.get(item.specId) || item.specId}</td>
                      <td style={tdStyle}>
                        <select
                          value={(item.payload?.status as CaseStatus) || "unexecuted"}
                          onChange={(e) => handleStatusChange(item.id, e.target.value as CaseStatus)}
                          disabled={isUpdatingStatus === item.id}
                          style={{
                            ...statusBadgeStyle,
                            ...getCaseStatusStyle(item),
                            border: "none",
                            cursor: isUpdatingStatus === item.id ? "not-allowed" : "pointer",
                            padding: "4px 12px",
                            borderRadius: "999px",
                            fontSize: ".74rem",
                            fontWeight: 600,
                            appearance: "none",
                            backgroundColor: "transparent",
                            color: getCaseStatusStyle(item).color,
                          }}
                        >
                          {caseStatusOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td style={tdStyle}>{formatDate(item.createdAt)}</td>
                      <td style={tdStyle}>
                        <div style={{ display: "flex", gap: 8 }}>
                          <button style={iconBtnStyle} onClick={() => void openEditModal(item)}>
                            <Edit3 size={14} />
                          </button>
                          <button
                            style={iconDangerBtnStyle}
                            onClick={() => void deleteOneCase(item.id)}
                            disabled={isDeleting}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                    {isExpanded && item.kind === "api" && (
                      <tr key={`${item.id}-steps`}>
                        <td colSpan={8} style={{ padding: 0, background: "#f8fafc" }}>
                          <div style={{ padding: "12px 24px", borderTop: "1px solid #e2e8f0" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                              <strong style={{ fontSize: ".85rem" }}>API 步骤列表</strong>
                              <button
                                style={{ ...primaryBtnStyle, fontSize: ".75rem", padding: "4px 12px" }}
                                onClick={() => {
                                  setEditingCaseId(item.id);
                                  setEditingStepIndex(null);
                                  setStepFormOpen(true);
                                }}
                              >
                                <Plus size={12} />
                                添加步骤
                              </button>
                            </div>
                            {apiSteps.length === 0 ? (
                              <div style={{ color: "var(--ink-soft)", fontSize: ".85rem", padding: 12, textAlign: "center" }}>
                                暂无 API 步骤，点击上方按钮添加
                              </div>
                            ) : (
                              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: ".85rem" }}>
                                <thead>
                                  <tr style={{ background: "#f1f5f9" }}>
                                    <th style={{ padding: "8px 12px", textAlign: "left", borderBottom: "1px solid #e2e8f0", width: 40 }}>#</th>
                                    <th style={{ padding: "8px 12px", textAlign: "left", borderBottom: "1px solid #e2e8f0" }}>名称</th>
                                    <th style={{ padding: "8px 12px", textAlign: "left", borderBottom: "1px solid #e2e8f0", width: 80 }}>方法</th>
                                    <th style={{ padding: "8px 12px", textAlign: "left", borderBottom: "1px solid #e2e8f0" }}>URL</th>
                                    <th style={{ padding: "8px 12px", textAlign: "left", borderBottom: "1px solid #e2e8f0", width: 80 }}>操作</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {apiSteps.map((step, idx) => (
                                    <tr key={idx}>
                                      <td style={{ padding: "8px 12px", borderBottom: "1px solid #e2e8f0" }}>{idx + 1}</td>
                                      <td style={{ padding: "8px 12px", borderBottom: "1px solid #e2e8f0" }}>{String(step.name || `步骤 ${idx + 1}`)}</td>
                                      <td style={{ padding: "8px 12px", borderBottom: "1px solid #e2e8f0" }}>
                                        <span style={{
                                          padding: "2px 8px",
                                          borderRadius: 4,
                                          fontSize: ".75rem",
                                          fontWeight: 600,
                                          background: step.method === "GET" ? "#dbeafe" : step.method === "POST" ? "#dcfce7" : step.method === "PUT" ? "#fef3c7" : step.method === "DELETE" ? "#fee2e2" : "#f3f4f6",
                                          color: step.method === "GET" ? "#1d4ed8" : step.method === "POST" ? "#15803d" : step.method === "PUT" ? "#b45309" : step.method === "DELETE" ? "#b91c1c" : "#374151",
                                        }}>
                                          {String(step.method || "GET")}
                                        </span>
                                      </td>
                                      <td style={{ padding: "8px 12px", borderBottom: "1px solid #e2e8f0", fontFamily: "var(--mono)", fontSize: ".8rem" }}>{String(step.url || "-")}</td>
                                      <td style={{ padding: "8px 12px", borderBottom: "1px solid #e2e8f0" }}>
                                        <div style={{ display: "flex", gap: 4 }}>
                                          <button
                                            style={{ border: "none", background: "transparent", cursor: "pointer", padding: 4 }}
                                            onClick={() => {
                                              setEditingCaseId(item.id);
                                              setEditingStepIndex(idx);
                                              setStepFormOpen(true);
                                            }}
                                          >
                                            <Edit3 size={12} />
                                          </button>
                                          <button
                                            style={{ border: "none", background: "transparent", cursor: "pointer", padding: 4, color: "#dc2626" }}
                                            onClick={() => void deleteStep(item.id, idx)}
                                          >
                                            <Trash2 size={12} />
                                          </button>
                                        </div>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div style={paginationStyle}>
        <span style={{ fontSize: ".85rem", color: "var(--ink-soft)" }}>
          第 {page} 页 / 每页 {pageSize}
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            style={pageBtnStyle}
            onClick={() => void loadCases(page - 1)}
            disabled={page <= 1 || isLoading}
          >
            <ChevronLeft size={14} />
            上一页
          </button>
          <button
            style={pageBtnStyle}
            onClick={() => void loadCases(page + 1)}
            disabled={!hasNext || isLoading}
          >
            下一页
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {modalOpen ? (
        <div style={modalBackdropStyle}>
          <div style={modalCardStyle}>
            <div style={modalHeaderStyle}>
              <strong>{modalMode === "create" ? "新增测试用例" : "编辑测试用例"}</strong>
              <button style={iconBtnStyle} onClick={closeModal}>
                <X size={14} />
              </button>
            </div>

            {modalNotice ? <div style={modalNoticeStyle}>{modalNotice}</div> : null}

            <div style={formGridStyle}>
              <label style={labelStyle}>
                项目
                <select
                  value={form.projectId}
                  onChange={(event) => void onProjectChange(event.target.value)}
                  style={inputStyle}
                  disabled={projects.length === 0}
                >
                  <option value="">请选择项目</option>
                  {projects.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <span style={helperTextStyle}>
                  {projects.length === 0
                    ? "请先在项目页面创建项目。"
                    : "先选择项目，再自动联动当前项目下的需求文档。"}
                </span>
              </label>
              <label style={labelStyle}>
                需求文档
                <select
                  value={form.specId}
                  onChange={(event) => updateForm("specId", event.target.value)}
                  style={inputStyle}
                  disabled={!form.projectId || isSpecLoading}
                >
                  <option value="">请选择文档</option>
                  {filteredSpecsForForm.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
                </select>
                <span style={helperTextStyle}>
                  {!form.projectId
                    ? "请先选择项目。"
                    : isSpecLoading
                      ? "正在加载当前项目下的需求文档..."
                      : filteredSpecsForForm.length > 0
                        ? `已加载 ${filteredSpecsForForm.length} 份需求文档。`
                        : "当前项目下还没有需求文档，请先在项目中创建需求文档。"}
                </span>
              </label>
              <label style={labelStyle}>
                类型
                <select
                  value={form.kind}
                  onChange={(event) => updateForm("kind", event.target.value as "api" | "ui")}
                  style={inputStyle}
                >
                  <option value="api">API</option>
                  <option value="ui">UI</option>
                </select>
              </label>
              <label style={labelStyle}>
                标题
                <input
                  value={form.title}
                  onChange={(event) => updateForm("title", event.target.value)}
                  style={inputStyle}
                  placeholder="例如：登录接口返回 200"
                />
              </label>
              <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
                测试目标
                <textarea
                  value={form.objective}
                  onChange={(event) => updateForm("objective", event.target.value)}
                  style={areaStyle}
                  placeholder="写清楚这个用例验证什么"
                />
              </label>
              <label style={labelStyle}>
                步骤（每行一个）
                <textarea
                  value={form.stepsText}
                  onChange={(event) => updateForm("stepsText", event.target.value)}
                  style={areaStyle}
                  placeholder={"步骤 1\n步骤 2\n步骤 3"}
                />
              </label>
              <label style={labelStyle}>
                断言提示（每行一个）
                <textarea
                  value={form.assertionHintsText}
                  onChange={(event) => updateForm("assertionHintsText", event.target.value)}
                  style={areaStyle}
                  placeholder={"status=200\ndata.token 存在"}
                />
              </label>
              {form.kind === "ui" ? (
                <UiCaseBuilder
                  value={form.payloadText}
                  onChange={(nextValue) => updateForm("payloadText", nextValue)}
                />
              ) : (
                <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
                  Payload (JSON)
                  <textarea
                    value={form.payloadText}
                    onChange={(event) => updateForm("payloadText", event.target.value)}
                    style={{ ...areaStyle, minHeight: 120, fontFamily: "var(--mono)" }}
                    placeholder='{"priority":"P1","status":"unexecuted"}'
                  />
                </label>
              )}
            </div>

            <div style={modalActionStyle}>
              <button style={secondaryBtnStyle} onClick={closeModal} disabled={isSaving}>
                取消
              </button>
              <button
                style={primaryBtnStyle}
                onClick={() => void submitCase()}
                disabled={isSaving || isSpecLoading}
              >
                {isSaving || isSpecLoading ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {isSpecLoading ? "加载文档中" : "保存"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {stepFormOpen && editingCaseId ? (
        <StepFormModal
          caseId={editingCaseId}
          stepIndex={editingStepIndex}
          cases={cases}
          onClose={() => {
            setStepFormOpen(false);
            setEditingCaseId(null);
            setEditingStepIndex(null);
          }}
          onSave={async () => {
            await loadCases(page);
            setStepFormOpen(false);
            setEditingCaseId(null);
            setEditingStepIndex(null);
          }}
        />
      ) : null}
    </article>
  );
}

const containerStyle: CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  minHeight: 0,
  padding: 0,
};

const toolbarStyle: CSSProperties = {
  borderBottom: "1px solid var(--line)",
  padding: "14px 16px",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  background: "var(--panel-strong)",
};

const filterBarStyle: CSSProperties = {
  padding: "10px 16px",
  borderBottom: "1px solid var(--line)",
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
  background: "var(--panel)",
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

const dangerBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  height: 42,
  padding: "0 16px",
  borderRadius: 14,
  border: "1px solid rgba(239,68,68,.25)",
  background: "rgba(254,226,226,.75)",
  color: "#b91c1c",
  cursor: "pointer",
  fontWeight: 600,
  transition: "all 0.3s ease",
};

const iconBtnStyle: CSSProperties = {
  width: 36,
  height: 36,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 12,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.75)",
  cursor: "pointer",
  transition: "all 0.3s ease",
};

const iconDangerBtnStyle: CSSProperties = {
  width: 36,
  height: 36,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 12,
  border: "1px solid rgba(239,68,68,.25)",
  background: "rgba(254,226,226,.75)",
  color: "#b91c1c",
  cursor: "pointer",
  transition: "all 0.3s ease",
};

const noticeStyle: CSSProperties = {
  margin: "10px 16px",
  border: "1px solid var(--primary-alpha-20)",
  color: "var(--primary-hover)",
  background: "var(--primary-alpha-10)",
  borderRadius: 14,
  fontSize: ".88rem",
  padding: "10px 16px",
  lineHeight: 1.6,
};

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
};

const thStyle: CSSProperties = {
  textAlign: "left",
  fontSize: ".82rem",
  color: "var(--ink-soft)",
  fontWeight: 600,
  padding: "10px 12px",
  borderBottom: "1px solid var(--line)",
};

const thCheckboxStyle: CSSProperties = {
  ...thStyle,
  width: 40,
};

const tdStyle: CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid var(--line)",
  verticalAlign: "top",
  fontSize: ".9rem",
};

const tdTitleStyle: CSSProperties = {
  ...tdStyle,
  minWidth: 220,
};

const tdCheckboxStyle: CSSProperties = {
  ...tdStyle,
  width: 40,
};

const statusBadgeStyle: CSSProperties = {
  borderRadius: 999,
  fontSize: ".74rem",
  fontWeight: 600,
  padding: "4px 8px",
};

const emptyRowStyle: CSSProperties = {
  textAlign: "center",
  color: "var(--ink-soft)",
  padding: "40px 0",
};

const paginationStyle: CSSProperties = {
  padding: "12px 16px",
  borderTop: "1px solid var(--line)",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  background: "var(--panel-strong)",
};

const pageBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 36,
  padding: "0 12px",
  borderRadius: 12,
  border: "1px solid var(--line)",
  background: "rgba(255, 255, 255, 0.75)",
  color: "var(--ink)",
  cursor: "pointer",
  fontWeight: 600,
  transition: "all 0.3s ease",
};

const modalBackdropStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "grid",
  placeItems: "center",
  background: "rgba(2,6,23,.42)",
  zIndex: 1200,
  padding: 16,
};

const modalCardStyle: CSSProperties = {
  width: "min(1180px, 96vw)",
  maxHeight: "90vh",
  overflow: "auto",
  borderRadius: 24,
  border: "1px solid var(--line)",
  background: "var(--panel-strong)",
  backdropFilter: "blur(14px)",
  boxShadow: "var(--shadow-xl)",
  padding: 20,
  display: "grid",
  gap: 16,
};

const modalHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

const formGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 10,
};

const labelStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  fontSize: ".84rem",
  color: "#334155",
  fontWeight: 600,
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

const helperTextStyle: CSSProperties = {
  fontSize: ".78rem",
  fontWeight: 500,
  color: "#64748b",
  lineHeight: 1.6,
};

const modalNoticeStyle: CSSProperties = {
  border: "1px solid rgba(217,119,6,.22)",
  background: "rgba(251,191,36,.12)",
  color: "#92400e",
  borderRadius: 10,
  padding: "10px 12px",
  fontSize: ".84rem",
  lineHeight: 1.6,
};

const modalActionStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 8,
};

type ApiStep = {
  name: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
  headers?: Array<{ key: string; value: string; enabled: boolean }>;
  body?: string;
  tests?: Array<Record<string, unknown>>;
};

function StepFormModal({
  caseId,
  stepIndex,
  cases,
  onClose,
  onSave,
}: {
  caseId: string;
  stepIndex: number | null;
  cases: TestCase[];
  onClose: () => void;
  onSave: () => void;
}) {
  const caseItem = cases.find((c) => c.id === caseId);
  const existingSteps: ApiStep[] = Array.isArray(caseItem?.payload?.apiSteps)
    ? caseItem.payload.apiSteps
    : [];
  const isEdit = stepIndex !== null;
  const [form, setForm] = useState<ApiStep>(() => {
    if (isEdit && existingSteps[stepIndex]) {
      return { ...existingSteps[stepIndex] };
    }
    return {
      name: "",
      method: "GET",
      url: "",
      headers: [],
      body: "",
      tests: [],
    };
  });
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const handleSubmit = async () => {
    setIsSaving(true);
    setNotice("");
    try {
      const updatedSteps = isEdit
        ? existingSteps.map((s, i) => (i === stepIndex ? form : s))
        : [...existingSteps, form];
      const updatedPayload = {
        ...caseItem?.payload,
        apiSteps: updatedSteps,
      };
      await requestJson<void>(`/api/cases/${caseId}`, {
        method: "PATCH",
        body: JSON.stringify({ payload: updatedPayload }),
      });
      setNotice("保存成功");
      onSave();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div style={modalBackdropStyle}>
      <div style={{ ...modalCardStyle, width: 600 }}>
        <div style={modalHeaderStyle}>
          <strong>{isEdit ? "编辑步骤" : "添加步骤"}</strong>
          <button style={iconBtnStyle} onClick={onClose}>
            <X size={14} />
          </button>
        </div>
        {notice && <div style={modalNoticeStyle}>{notice}</div>}
        <div style={{ display: "grid", gap: 16, padding: 16 }}>
          <label style={labelStyle}>
            步骤名称
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              style={inputStyle}
              placeholder="例如：登录接口"
            />
          </label>
          <label style={labelStyle}>
            请求方法
            <select
              value={form.method}
              onChange={(e) => setForm({ ...form, method: e.target.value as ApiStep["method"] })}
              style={inputStyle}
            >
              <option value="GET">GET</option>
              <option value="POST">POST</option>
              <option value="PUT">PUT</option>
              <option value="PATCH">PATCH</option>
              <option value="DELETE">DELETE</option>
            </select>
          </label>
          <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
            URL
            <input
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              style={inputStyle}
              placeholder="例如：/api/login"
            />
          </label>
          <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
            Headers (JSON)
            <textarea
              value={form.headers ? JSON.stringify(form.headers, null, 2) : ""}
              onChange={(e) => {
                try {
                  const parsed = e.target.value ? JSON.parse(e.target.value) : [];
                  setForm({ ...form, headers: parsed });
                } catch {
                  setForm({ ...form, headers: [] });
                }
              }}
              style={{ ...areaStyle, fontFamily: "var(--mono)", fontSize: ".8rem" }}
              placeholder='[{"key": "Content-Type", "value": "application/json"}]'
            />
          </label>
          <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
            Body (JSON)
            <textarea
              value={form.body || ""}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
              style={{ ...areaStyle, fontFamily: "var(--mono)", fontSize: ".8rem" }}
              placeholder="请求体 JSON"
            />
          </label>
          <label style={{ ...labelStyle, gridColumn: "1 / span 2" }}>
            断言 (JSON)
            <textarea
              value={form.tests ? JSON.stringify(form.tests, null, 2) : ""}
              onChange={(e) => {
                try {
                  const parsed = e.target.value ? JSON.parse(e.target.value) : [];
                  setForm({ ...form, tests: parsed });
                } catch {
                  setForm({ ...form, tests: [] });
                }
              }}
              style={{ ...areaStyle, fontFamily: "var(--mono)", fontSize: ".8rem" }}
              placeholder="断言配置 JSON 数组"
            />
          </label>
        </div>
        <div style={modalActionStyle}>
          <button style={secondaryBtnStyle} onClick={onClose}>
            取消
          </button>
          <button style={primaryBtnStyle} onClick={() => void handleSubmit()} disabled={isSaving}>
            {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
