"use client";

import { type CSSProperties, type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { Edit3, History, Loader2, Plus, RotateCcw, Search, Trash2, Upload } from "lucide-react";

type RequirementStatus = "draft" | "analyzing" | "analyzed" | "failed";

type Requirement = {
  id: string;
  projectId: string;
  sourceSpecId: string | null;
  title: string;
  content: string;
  tags: string[];
  coverageCaseCount?: number;
  status: RequirementStatus;
  latestAnalysisVersion: number | null;
  createdBy: string | null;
  createdAt: string;
  updatedAt: string;
};

type RequirementTableDict = {
  projectName: string;
  status: string;
  scoreCol: string;
  date: string;
  searchPlaceholder?: string;
};

type ProjectOption = { id: string; name: string };
type Project = {
  id: string;
  name: string;
  description: string;
  createdAt: string;
  updatedAt: string;
};

type PagedResult<T> = {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  hasNext: boolean;
};

type RequirementImportResult = {
  total: number;
  created: Requirement[];
  warnings: string[];
};

type RequirementImportPreviewResult = {
  total: number;
  valid: number;
  invalid: number;
  duplicates: number;
  sample: Array<{ title: string; contentPreview: string; tags: string[] }>;
  warnings: string[];
};

type RequirementAnalysisVersion = {
  id: string;
  version: number;
  summary: string;
  functionalRequirements: string[];
  nonFunctionalRequirements: string[];
  acceptanceCriteria: string[];
  risks: string[];
  testFocus: string[];
  assumptions: string[];
  createdAt: string;
};

type RequirementAnalysisCompareResult = {
  left: RequirementAnalysisVersion;
  right: RequirementAnalysisVersion;
  diff: {
    summaryChanged: boolean;
    functionalRequirements: { added: string[]; removed: string[] };
    nonFunctionalRequirements: { added: string[]; removed: string[] };
    acceptanceCriteria: { added: string[]; removed: string[] };
    risks: { added: string[]; removed: string[] };
    testFocus: { added: string[]; removed: string[] };
    assumptions: { added: string[]; removed: string[] };
  };
};

function statusText(status: RequirementStatus): string {
  if (status === "analyzing") return "分析中";
  if (status === "analyzed") return "分析完成";
  if (status === "failed") return "失败";
  return "草稿";
}

function statusColor(status: RequirementStatus): string {
  if (status === "analyzing") return "#2563eb";
  if (status === "analyzed") return "#16a34a";
  if (status === "failed") return "#dc2626";
  return "#6b7280";
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function parseJsonSafe(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function readErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const data = payload as { message?: unknown };
  if (typeof data.message === "string" && data.message.trim()) return data.message;
  return fallback;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  const payload = await parseJsonSafe(response);
  if (!response.ok) throw new Error(readErrorMessage(payload, "请求失败"));
  return payload as T;
}

async function requestForm<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", body: formData, cache: "no-store" });
  const payload = await parseJsonSafe(response);
  if (!response.ok) throw new Error(readErrorMessage(payload, "请求失败"));
  return payload as T;
}

export function RequirementTable({
  dict,
  initialData,
  initialPage = 1,
  initialPageSize = 20,
  initialTotal,
  initialHasNext = false,
  defaultProjectId = "",
  projects = [],
}: {
  dict: RequirementTableDict;
  initialData: Requirement[];
  initialPage?: number;
  initialPageSize?: number;
  initialTotal?: number;
  initialHasNext?: boolean;
  defaultProjectId?: string;
  projects?: ProjectOption[];
}) {
  const [data, setData] = useState<Requirement[]>(initialData);
  const [projectOptions, setProjectOptions] = useState<ProjectOption[]>(projects);
  const [projectId, setProjectId] = useState(defaultProjectId);
  const [queryText, setQueryText] = useState("");
  const [status, setStatus] = useState<RequirementStatus | "">("");
  const [deletedFrom, setDeletedFrom] = useState("");
  const [deletedTo, setDeletedTo] = useState("");
  const [isRecycleMode, setIsRecycleMode] = useState(false);
  const [sortBy, setSortBy] = useState<"createdAt" | "updatedAt" | "status" | "title">("updatedAt");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(initialPage);
  const [pageSize] = useState(initialPageSize);
  const [total, setTotal] = useState(initialTotal ?? initialData.length);
  const [hasNext, setHasNext] = useState(initialHasNext);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createProjectId, setCreateProjectId] = useState(defaultProjectId);
  const [createTitle, setCreateTitle] = useState("");
  const [createContent, setCreateContent] = useState("");
  const [createTagsText, setCreateTagsText] = useState("");

  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editingId, setEditingId] = useState("");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editTagsText, setEditTagsText] = useState("");
  const [editStatus, setEditStatus] = useState<RequirementStatus>("draft");

  const [isProjectOpen, setIsProjectOpen] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDesc, setNewProjectDesc] = useState("");
  const [isRestoreProjectOpen, setIsRestoreProjectOpen] = useState(false);
  const [restoreProjectRows, setRestoreProjectRows] = useState<Project[]>([]);
  const [restoreProjectId, setRestoreProjectId] = useState("");
  const [restoreSearchText, setRestoreSearchText] = useState("");
  const [restoreProjectLoading, setRestoreProjectLoading] = useState(false);
  const [restoringProject, setRestoringProject] = useState(false);
  const [purgingProjectId, setPurgingProjectId] = useState<string | null>(null);
  const [purgingBatch, setPurgingBatch] = useState(false);
  const [restoreSelectedIds, setRestoreSelectedIds] = useState<string[]>([]);

  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importDedupe, setImportDedupe] = useState(true);
  const [importRollbackOnError, setImportRollbackOnError] = useState(false);
  const [importStrictTemplate, setImportStrictTemplate] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisRequirementId, setAnalysisRequirementId] = useState("");
  const [analysisTitle, setAnalysisTitle] = useState("");
  const [analysisVersions, setAnalysisVersions] = useState<RequirementAnalysisVersion[]>([]);
  const [analysisLeft, setAnalysisLeft] = useState<number>(0);
  const [analysisRight, setAnalysisRight] = useState<number>(1);
  const [analysisCompareLoading, setAnalysisCompareLoading] = useState(false);
  const [analysisCompare, setAnalysisCompare] = useState<RequirementAnalysisCompareResult | null>(null);

  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const restoreFilteredRows = useMemo(() => {
    const q = restoreSearchText.trim().toLowerCase();
    if (!q) return restoreProjectRows;
    return restoreProjectRows.filter(
      (item) => item.name.toLowerCase().includes(q) || item.id.toLowerCase().includes(q),
    );
  }, [restoreProjectRows, restoreSearchText]);
  const restoreSelectedCount = restoreSelectedIds.length;
  const restoreAllSelected = restoreFilteredRows.length > 0 && restoreFilteredRows.every((item) => restoreSelectedIds.includes(item.id));

  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [notice]);

  const rows = useMemo(() => data, [data]);
  const selectedCount = selectedIds.length;
  const allSelected = rows.length > 0 && selectedIds.length === rows.length;

  const loadProjects = async () => {
    const list = await requestJson<Project[]>("/api/projects");
    const active = (Array.isArray(list) ? list : []).filter(
      (item: any) => !item?.deletedAt && !item?.deleted_at,
    );
    const options = active.map((item) => ({ id: item.id, name: item.name }));
    setProjectOptions(options);
    if (projectId && !options.some((item) => item.id === projectId)) setProjectId("");
  };

  const loadRequirements = async (targetPage = 1, recycleMode = isRecycleMode) => {
    const search = new URLSearchParams();
    if (projectId.trim()) search.set("projectId", projectId.trim());
    if (!recycleMode && queryText.trim()) search.set("q", queryText.trim());
    if (!recycleMode && status) search.set("status", status);
    if (recycleMode && deletedFrom) search.set("deletedFrom", new Date(deletedFrom).toISOString());
    if (recycleMode && deletedTo) search.set("deletedTo", new Date(deletedTo).toISOString());
    search.set("page", String(targetPage));
    search.set("pageSize", String(pageSize));
    if (!recycleMode) {
      search.set("sortBy", sortBy);
      search.set("sortOrder", sortOrder);
    }
    setIsLoading(true);
    setNotice(null);
    try {
      const result = await requestJson<PagedResult<Requirement>>(
        `${recycleMode ? "/api/requirements/recycle-bin" : "/api/requirements/search"}?${search.toString()}`,
      );
      setData(result.items);
      setTotal(result.total);
      setPage(result.page);
      setHasNext(result.hasNext);
      setSelectedIds([]);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载需求失败" });
    } finally {
      setIsLoading(false);
    }
  };

  const openCreateModal = () => {
    setCreateProjectId(createProjectId || projectId || projectOptions[0]?.id || "");
    setCreateTitle("");
    setCreateContent("");
    setCreateTagsText("");
    setIsCreateOpen(true);
  };

  const openEditModal = (item: Requirement) => {
    setEditingId(item.id);
    setEditTitle(item.title);
    setEditContent(item.content);
    setEditTagsText(item.tags.join(", "));
    setEditStatus(item.status);
    setIsEditOpen(true);
  };

  const submitCreateProject = async () => {
    if (!newProjectName.trim()) {
      setNotice({ kind: "error", text: "项目名称不能为空" });
      return;
    }
    setCreatingProject(true);
    try {
      const created = await requestJson<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ name: newProjectName.trim(), description: newProjectDesc.trim() }),
      });
      setIsProjectOpen(false);
      setNewProjectName("");
      setNewProjectDesc("");
      await loadProjects();
      setProjectId(created.id);
      setNotice({ kind: "success", text: `项目已创建：${created.name}` });
      await loadRequirements(1);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "新增项目失败" });
    } finally {
      setCreatingProject(false);
    }
  };

  const editCurrentProject = async () => {
    if (!projectId) {
      setNotice({ kind: "error", text: "请先选择项目" });
      return;
    }
    const existing = projectOptions.find((item) => item.id === projectId);
    const nextName = window.prompt("输入新的项目名称", existing?.name ?? "");
    if (!nextName || !nextName.trim()) return;
    const nextDesc = window.prompt("输入项目描述（可选）", "");
    await requestJson<Project>(`/api/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({ name: nextName.trim(), description: (nextDesc || "").trim() }),
    });
    await loadProjects();
    setNotice({ kind: "success", text: "项目已更新" });
  };

  const deleteCurrentProject = async () => {
    if (!projectId) {
      setNotice({ kind: "error", text: "请先选择项目" });
      return;
    }
    if (!window.confirm("确认删除当前项目并移入回收站吗？")) return;
    try {
      await requestJson<null>(`/api/projects/${projectId}`, { method: "DELETE" });
      setProjectId("");
      await loadProjects();
      await loadRequirements(1);
      setNotice({ kind: "success", text: "项目已移入回收站" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "删除项目失败" });
    }
  };

  const restoreDeletedProject = async () => {
    setRestoreProjectLoading(true);
    try {
      const deleted = await requestJson<PagedResult<Project>>("/api/projects/recycle-bin?page=1&pageSize=200");
      if (deleted.items.length === 0) {
        setNotice({ kind: "error", text: "项目回收站为空" });
        return;
      }
      setRestoreProjectRows(deleted.items);
      setRestoreProjectId(deleted.items[0]?.id || "");
      setRestoreSelectedIds([]);
      setRestoreSearchText("");
      setIsRestoreProjectOpen(true);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载回收站失败" });
    } finally {
      setRestoreProjectLoading(false);
    }
  };

  const submitRestoreProject = async () => {
    const targetId = restoreProjectId.trim();
    if (!targetId) {
      setNotice({ kind: "error", text: "请选择要恢复的项目" });
      return;
    }
    setRestoringProject(true);
    try {
      const restored = await requestJson<Project>(`/api/projects/${targetId}/restore`, { method: "POST" });
      await loadProjects();
      setProjectId(restored.id);
      setIsRestoreProjectOpen(false);
      setNotice({ kind: "success", text: `项目已恢复：${restored.name}` });
      await loadRequirements(1);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "恢复项目失败" });
    } finally {
      setRestoringProject(false);
    }
  };

  const purgeDeletedProject = async (project: Project) => {
    const confirmText = [
      `确认永久删除项目「${project.name}」吗？`,
      "该操作会连带删除该项目下的需求、测试用例、接口集合/请求、测试报告及关联索引数据，且不可恢复。",
    ].join("\n");
    if (!window.confirm(confirmText)) return;
    setPurgingProjectId(project.id);
    try {
      const response = await fetch(`/api/projects/${project.id}/purge`, { method: "DELETE", cache: "no-store" });
      if (!response.ok && response.status !== 204) {
        const payload = await parseJsonSafe(response);
        throw new Error(readErrorMessage(payload, "永久删除项目失败"));
      }
      const nextRows = restoreProjectRows.filter((item) => item.id !== project.id);
      setRestoreProjectRows(nextRows);
      setRestoreProjectId((prev) => (prev === project.id ? (nextRows[0]?.id ?? "") : prev));
      setRestoreSelectedIds((prev) => prev.filter((id) => id !== project.id));
      if (nextRows.length === 0) setIsRestoreProjectOpen(false);
      setNotice({ kind: "success", text: `项目已永久删除：${project.name}` });
      await loadProjects();
      await loadRequirements(1);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "永久删除项目失败" });
    } finally {
      setPurgingProjectId(null);
    }
  };

  const toggleRestoreSelection = (projectId: string) => {
    setRestoreSelectedIds((prev) =>
      prev.includes(projectId) ? prev.filter((id) => id !== projectId) : [...prev, projectId],
    );
  };

  const toggleSelectAllRestore = () => {
    if (restoreFilteredRows.length === 0) return;
    if (restoreAllSelected) {
      const visible = new Set(restoreFilteredRows.map((item) => item.id));
      setRestoreSelectedIds((prev) => prev.filter((id) => !visible.has(id)));
      return;
    }
    const merged = new Set(restoreSelectedIds);
    for (const row of restoreFilteredRows) merged.add(row.id);
    setRestoreSelectedIds(Array.from(merged));
  };

  const batchPurgeDeletedProjects = async () => {
    if (restoreSelectedIds.length === 0) {
      setNotice({ kind: "error", text: "请先选择要永久删除的项目" });
      return;
    }
    const confirmText = [
      `确认永久删除选中的 ${restoreSelectedIds.length} 个项目吗？`,
      "该操作会连带删除关联的需求、测试用例、接口和报告，且不可恢复。",
    ].join("\n");
    if (!window.confirm(confirmText)) return;
    setPurgingBatch(true);
    try {
      const result = await requestJson<{ deleted: number; failedIds: string[] }>(
        "/api/projects/recycle-bin/batch-delete",
        {
          method: "POST",
          body: JSON.stringify({ ids: restoreSelectedIds }),
        },
      );
      const failed = new Set(result.failedIds ?? []);
      const nextRows = restoreProjectRows.filter((item) => failed.has(item.id));
      setRestoreProjectRows(nextRows);
      setRestoreSelectedIds([]);
      setRestoreProjectId((prev) => (prev && failed.has(prev) ? prev : (nextRows[0]?.id ?? "")));
      if (nextRows.length === 0) setIsRestoreProjectOpen(false);
      setNotice({
        kind: "success",
        text: failed.size > 0 ? `已永久删除 ${result.deleted} 个项目，失败 ${failed.size} 个` : `已永久删除 ${result.deleted} 个项目`,
      });
      await loadProjects();
      await loadRequirements(1);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "批量永久删除项目失败" });
    } finally {
      setPurgingBatch(false);
    }
  };

  const submitCreate = async () => {
    if (!createProjectId.trim()) return setNotice({ kind: "error", text: "请先选择项目" });
    if (!createTitle.trim() || !createContent.trim()) return setNotice({ kind: "error", text: "标题和正文不能为空" });
    const tags = createTagsText.split(/[,\n，]/).map((item) => item.trim()).filter(Boolean);
    setCreating(true);
    try {
      await requestJson<Requirement>("/api/requirements", {
        method: "POST",
        body: JSON.stringify({
          projectId: createProjectId.trim(),
          title: createTitle.trim(),
          content: createContent.trim(),
          tags,
        }),
      });
      setIsCreateOpen(false);
      setCreateTitle("");
      setCreateContent("");
      setCreateTagsText("");
      setProjectId(createProjectId.trim());
      setIsRecycleMode(false);
      await loadRequirements(1);
      setNotice({ kind: "success", text: "需求已创建" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "新增需求失败" });
    } finally {
      setCreating(false);
    }
  };

  const submitEdit = async () => {
    if (!editingId || !editTitle.trim() || !editContent.trim()) return;
    const tags = editTagsText.split(/[,\n，]/).map((item) => item.trim()).filter(Boolean);
    setEditing(true);
    try {
      await requestJson<Requirement>(`/api/requirements/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: editTitle.trim(),
          content: editContent.trim(),
          tags,
          status: editStatus,
        }),
      });
      setIsEditOpen(false);
      await loadRequirements(page);
      setNotice({ kind: "success", text: "需求已更新" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "更新需求失败" });
    } finally {
      setEditing(false);
    }
  };

  const deleteOne = async (item: Requirement) => {
    if (!window.confirm(`确认删除需求「${item.title}」吗？`)) return;
    setOperatingId(item.id);
    try {
      await requestJson<null>(`/api/requirements/${item.id}`, { method: "DELETE" });
      await loadRequirements(page);
      setNotice({ kind: "success", text: "需求已移入回收站" });
    } finally {
      setOperatingId(null);
    }
  };

  const restoreOne = async (item: Requirement) => {
    setOperatingId(item.id);
    try {
      await requestJson<Requirement>(`/api/requirements/${item.id}/restore`, { method: "POST" });
      await loadRequirements(page);
      setNotice({ kind: "success", text: "需求已恢复" });
    } finally {
      setOperatingId(null);
    }
  };

  const hardDeleteOne = async (item: Requirement) => {
    if (!window.confirm(`确认永久删除需求「${item.title}」吗？此操作不可恢复！`)) return;
    setOperatingId(item.id);
    try {
      await requestJson<null>(`/api/requirements/${item.id}?hard=true`, { method: "DELETE" });
      await loadRequirements(page);
      setNotice({ kind: "success", text: "需求已永久删除" });
    } finally {
      setOperatingId(null);
    }
  };

  const batchDelete = async () => {
    if (selectedIds.length === 0) return setNotice({ kind: "error", text: "请先选择要删除的需求" });
    if (!window.confirm(`确认批量删除 ${selectedIds.length} 条需求吗？`)) return;
    setBatchDeleting(true);
    try {
      const result = await requestJson<{ deleted: number }>("/api/requirements/batch-delete", {
        method: "POST",
        body: JSON.stringify({ requirementIds: selectedIds }),
      });
      setSelectedIds([]);
      await loadRequirements(page);
      setNotice({ kind: "success", text: `已删除 ${result.deleted} 条需求` });
    } finally {
      setBatchDeleting(false);
    }
  };

  const batchRestore = async () => {
    if (selectedIds.length === 0) return setNotice({ kind: "error", text: "请先选择要恢复的需求" });
    setBatchDeleting(true);
    try {
      const result = await requestJson<{ restored: number }>("/api/requirements/batch-restore", {
        method: "POST",
        body: JSON.stringify({ requirementIds: selectedIds }),
      });
      setSelectedIds([]);
      await loadRequirements(page);
      setNotice({ kind: "success", text: `已恢复 ${result.restored} 条需求` });
    } finally {
      setBatchDeleting(false);
    }
  };

  const batchHardDelete = async () => {
    if (selectedIds.length === 0) return setNotice({ kind: "error", text: "请先选择要删除的需求" });
    if (!window.confirm(`确认永久删除 ${selectedIds.length} 条需求吗？此操作不可恢复！`)) return;
    setBatchDeleting(true);
    try {
      const result = await requestJson<{ deleted: number }>("/api/requirements/batch-delete?hard=true", {
        method: "POST",
        body: JSON.stringify({ requirementIds: selectedIds }),
      });
      setSelectedIds([]);
      await loadRequirements(page);
      setNotice({ kind: "success", text: `已永久删除 ${result.deleted} 条需求` });
    } finally {
      setBatchDeleting(false);
    }
  };

  const batchMarkAnalyzed = async () => {
    if (selectedIds.length === 0) return setNotice({ kind: "error", text: "请先选择需求" });
    setBatchDeleting(true);
    try {
      const result = await requestJson<{ updated: number }>("/api/requirements/batch-status", {
        method: "POST",
        body: JSON.stringify({ requirementIds: selectedIds, status: "analyzed" }),
      });
      setSelectedIds([]);
      await loadRequirements(page);
      setNotice({ kind: "success", text: `已更新 ${result.updated} 条需求为已分析` });
    } finally {
      setBatchDeleting(false);
    }
  };

  const exportRequirements = (format: "json" | "csv") => {
    const search = new URLSearchParams();
    if (projectId.trim()) search.set("projectId", projectId.trim());
    if (!isRecycleMode && queryText.trim()) search.set("q", queryText.trim());
    if (!isRecycleMode && status) search.set("status", status);
    search.set("format", format);
    window.open(`/api/requirements/export?${search.toString()}`, "_blank");
  };

  const onPickImportFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
    if (!file || !projectId.trim()) return;
    setImporting(true);
    try {
      const previewForm = new FormData();
      previewForm.append("projectId", projectId.trim());
      previewForm.append("dedupe", String(importDedupe));
      previewForm.append("strictTemplate", String(importStrictTemplate));
      previewForm.append("file", file);
      const preview = await requestForm<RequirementImportPreviewResult>("/api/requirements/import/preview", previewForm);
      if (preview.valid <= 0) return setNotice({ kind: "error", text: "导入预览通过数为 0，已取消导入" });
      const ok = window.confirm(
        `导入预览：总 ${preview.total}，可导入 ${preview.valid}，重复 ${preview.duplicates}，无效 ${preview.invalid}。继续吗？`,
      );
      if (!ok) return;

      const formData = new FormData();
      formData.append("projectId", projectId.trim());
      formData.append("dedupe", String(importDedupe));
      formData.append("rollbackOnError", String(importRollbackOnError));
      formData.append("strictTemplate", String(importStrictTemplate));
      formData.append("file", file);
      const result = await requestForm<RequirementImportResult>("/api/requirements/import", formData);
      await loadRequirements(1);
      setNotice({
        kind: "success",
        text: `导入完成：解析 ${result.total}，创建 ${result.created.length}，告警 ${result.warnings.length}`,
      });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "导入失败" });
    } finally {
      setImporting(false);
    }
  };

  const openAnalysisHistory = async (item: Requirement) => {
    setAnalysisOpen(true);
    setAnalysisLoading(true);
    setAnalysisRequirementId(item.id);
    setAnalysisTitle(item.title);
    setAnalysisVersions([]);
    setAnalysisLeft(0);
    setAnalysisRight(1);
    setAnalysisCompare(null);
    try {
      const rows = await requestJson<RequirementAnalysisVersion[]>(
        `/api/requirements/${item.id}/analysis/versions?limit=20`,
      );
      setAnalysisVersions(Array.isArray(rows) ? rows : []);
      setAnalysisLeft(0);
      setAnalysisRight((Array.isArray(rows) ? rows.length : 0) > 1 ? 1 : 0);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载分析历史失败" });
    } finally {
      setAnalysisLoading(false);
    }
  };

  useEffect(() => {
    const loadCompare = async () => {
      const left = analysisVersions[analysisLeft];
      const right = analysisVersions[analysisRight];
      if (!analysisOpen || !analysisRequirementId || !left || !right) {
        setAnalysisCompare(null);
        return;
      }
      setAnalysisCompareLoading(true);
      try {
        const search = new URLSearchParams();
        search.set("leftVersion", String(left.version));
        search.set("rightVersion", String(right.version));
        const compared = await requestJson<RequirementAnalysisCompareResult>(
          `/api/requirements/${analysisRequirementId}/analysis/compare?${search.toString()}`,
        );
        setAnalysisCompare(compared);
      } catch (error) {
        setAnalysisCompare(null);
        setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载分析差异失败" });
      } finally {
        setAnalysisCompareLoading(false);
      }
    };
    void loadCompare();
  }, [analysisOpen, analysisRequirementId, analysisVersions, analysisLeft, analysisRight]);

  const exportAnalysisDiff = (format: "markdown" | "html") => {
    const left = analysisVersions[analysisLeft];
    const right = analysisVersions[analysisRight];
    if (!left || !right || !analysisRequirementId) return;
    const search = new URLSearchParams();
    search.set("leftVersion", String(left.version));
    search.set("rightVersion", String(right.version));
    search.set("format", format);
    window.open(
      `/api/requirements/${analysisRequirementId}/analysis/compare/export?${search.toString()}`,
      "_blank",
    );
  };

  return (
    <article className="panel requirements-panel" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, padding: 0 }}>
      {/* 顶部工具栏 - 重新设计的双翼布局 */}
      <div className="rm-toolbar-modern" style={{ 
        padding: "20px 24px", 
        background: "rgba(255, 255, 255, 0.62)", 
        backdropFilter: "blur(12px)",
        borderBottom: "1px solid var(--line)",
        display: "flex",
        flexDirection: "column",
        gap: "16px"
      }}>
        {/* 第一行：搜索与主操作 */}
        <div className="rm-toolbar-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "16px" }}>
          {/* 左侧：搜索与基础过滤 */}
          <div className="rm-toolbar-left" style={{ display: "flex", gap: "12px", alignItems: "center", flex: 1 }}>
            <div style={{ position: "relative", flex: 1, maxWidth: "400px" }}>
              <Search size={16} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--ink-soft)" }} />
              <input 
                value={queryText} 
                onChange={(e) => setQueryText(e.target.value)} 
                placeholder={dict.searchPlaceholder || "快速搜索需求..."} 
                className="modern-input"
                style={{ ...modernInputFieldStyle, paddingLeft: "36px", width: "100%" }} 
                disabled={isRecycleMode} 
              />
            </div>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="modern-select" style={modernSelectStyle}>
              <option value="">全部项目</option>
              {projectOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <button onClick={() => void loadRequirements(1)} className="btn-modern btn-search" style={primaryActionBtnStyle} disabled={isLoading}>
              {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
              查询
            </button>
          </div>

          {/* 右侧：核心动作 */}
          <div className="rm-toolbar-right" style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
             {!isRecycleMode && (
               <>
                <button onClick={openCreateModal} className="btn-modern btn-primary" style={premiumGradientBtnStyle}>
                  <Plus size={16} /> 新增需求
                </button>
                <button onClick={() => {
                  if (!projectId) {
                    setNotice({ kind: "error", text: "请先选择一个项目后再导入需求" });
                    return;
                  }
                  importInputRef.current?.click();
                }} className="btn-modern" style={secondaryActionBtnStyle} disabled={importing}>
                  {importing ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                  导入
                </button>
               </>
             )}
             <button 
                onClick={() => {
                  const nextRecycleMode = !isRecycleMode;
                  setIsRecycleMode(nextRecycleMode);
                  void loadRequirements(1, nextRecycleMode);
                }} 
                className="btn-modern" 
                style={secondaryActionBtnStyle}
             >
                <RotateCcw size={16} /> {isRecycleMode ? "正常列表" : "回收站"}
             </button>
          </div>
        </div>

        {/* 第二行：高级过滤与管理功能 (收纳次要操作) */}
        <div className="rm-toolbar-row rm-toolbar-sub" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid rgba(0,0,0,0.05)", paddingTop: "12px", gap: "16px", flexWrap: "wrap" }}>
          <div className="rm-toolbar-left" style={{ display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap" }}>
            {!isRecycleMode ? (
              <>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <span style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>状态:</span>
                  <select value={status} onChange={(e) => setStatus(e.target.value as RequirementStatus | "")} className="modern-select-sm" style={smallSelectStyle}>
                    <option value="">全部</option>
                    <option value="draft">草稿</option>
                    <option value="analyzing">分析中</option>
                    <option value="analyzed">已完成</option>
                    <option value="failed">失败</option>
                  </select>
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <span style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>排序:</span>
                  <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)} className="modern-select-sm" style={smallSelectStyle}>
                    <option value="updatedAt">更新时间</option>
                    <option value="createdAt">创建时间</option>
                    <option value="title">按标题</option>
                  </select>
                  <select value={sortOrder} onChange={(e) => setSortOrder(e.target.value as any)} className="modern-select-sm" style={smallSelectStyle}>
                    <option value="desc">降序</option>
                    <option value="asc">升序</option>
                  </select>
                </div>
              </>
            ) : (
              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>删除时间:</span>
                <input
                  type="datetime-local"
                  value={deletedFrom}
                  onChange={(e) => setDeletedFrom(e.target.value)}
                  style={smallInputStyle}
                />
                <span style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>至</span>
                <input
                  type="datetime-local"
                  value={deletedTo}
                  onChange={(e) => setDeletedTo(e.target.value)}
                  style={smallInputStyle}
                />
              </div>
            )}
            {!isRecycleMode && (
              <div style={{ display: "flex", gap: "12px", borderLeft: "1px solid var(--line)", paddingLeft: "16px", marginLeft: "4px" }}>
                <label style={checkboxLabelStyle}><input type="checkbox" checked={importDedupe} onChange={(e) => setImportDedupe(e.target.checked)} /> 导入去重</label>
                <label style={checkboxLabelStyle}><input type="checkbox" checked={importRollbackOnError} onChange={(e) => setImportRollbackOnError(e.target.checked)} /> 失败回滚</label>
              </div>
            )}
          </div>

          <div className="rm-toolbar-right" style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
             {isRecycleMode ? (
               <>
                 <button onClick={() => void batchRestore()} className="btn-modern" style={secondaryActionBtnStyle} disabled={selectedCount === 0 || batchDeleting}>
                   <RotateCcw size={14} /> 批量恢复 ({selectedCount})
                 </button>
                 <button onClick={() => void batchHardDelete()} className="btn-modern btn-danger" style={dangerActionBtnStyle} disabled={selectedCount === 0 || batchDeleting}>
                   <Trash2 size={14} /> 批量永久删除 ({selectedCount})
                 </button>
               </>
             ) : (
               <>
                 <button onClick={() => void batchMarkAnalyzed()} className="btn-modern" style={secondaryActionBtnStyle} disabled={selectedCount === 0 || batchDeleting}>
                   批量标记已分析 ({selectedCount})
                 </button>
                 <button onClick={() => void batchDelete()} className="btn-modern btn-danger" style={dangerActionBtnStyle} disabled={selectedCount === 0 || batchDeleting}>
                   <Trash2 size={14} /> 批量删除 ({selectedCount})
                 </button>
               </>
             )}
             <button onClick={() => exportRequirements("json")} className="btn-modern btn-ghost" style={ghostBtnStyle}>导出 JSON</button>
             <button onClick={() => exportRequirements("csv")} className="btn-modern btn-ghost" style={ghostBtnStyle}>导出 CSV</button>
             <div style={{ height: "24px", width: "1px", background: "var(--line)", margin: "0 8px" }} />
             <button onClick={() => setIsProjectOpen(true)} className="btn-modern btn-ghost" style={ghostBtnStyle} title="新增项目"><Plus size={14} /> 项目</button>
             {projectId && (
               <>
                 <button onClick={() => void editCurrentProject()} className="btn-modern btn-ghost" style={ghostBtnStyle} title="编辑项目"><Edit3 size={14} /></button>
                 <button onClick={() => void deleteCurrentProject()} className="btn-modern btn-ghost" style={ghostBtnStyle} title="删除项目"><Trash2 size={14} /></button>
               </>
             )}
            <button
              onClick={() => void restoreDeletedProject()}
              className="btn-modern btn-ghost"
              style={ghostBtnStyle}
              title="恢复项目"
              disabled={restoreProjectLoading}
            >
              {restoreProjectLoading ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
            </button>
          </div>
        </div>

        {notice && (
          <div className={`rm-notice ${notice.kind}`} style={{ 
            padding: "10px 16px", 
            borderRadius: "10px", 
            fontSize: "0.9rem",
            display: "flex",
            alignItems: "center",
            gap: "10px",
            background: notice.kind === "success" ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)",
            color: notice.kind === "success" ? "#15803d" : "#b91c1c",
            border: notice.kind === "success" ? "1px solid rgba(34, 197, 94, 0.2)" : "1px solid rgba(239, 68, 68, 0.2)"
          }}>
            {notice.text}
          </div>
        )}
        <input ref={importInputRef} type="file" accept=".txt,.md,.csv,.json" style={{ display: "none" }} onChange={(e) => void onPickImportFile(e)} />
      </div>

      {/* 数据表格区域 - 精致卡片悬浮感 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "14px 24px" }}>
        <table className="modern-table" style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 8px" }}>
          <thead>
            <tr style={{ color: "var(--ink-soft)", fontSize: "0.85rem", textAlign: "left" }}>
              <th style={{ padding: "12px" }}><input type="checkbox" checked={allSelected} onChange={(e) => setSelectedIds(e.target.checked ? rows.map((item) => item.id) : [])} /></th>
              <th style={{ padding: "12px" }}>需求定义</th>
              <th style={{ padding: "12px" }}>当前状态</th>
              <th style={{ padding: "12px" }}>覆盖规模</th>
              <th style={{ padding: "12px" }}>更新于</th>
              <th style={{ padding: "12px", textAlign: "right" }}>交互操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id} className="table-row-premium" style={{ 
                background: "white", 
                boxShadow: "0 2px 4px rgba(0,0,0,0.02)",
                transition: "all 0.2s"
              }}>
                <td style={{ padding: "16px 12px", borderRadius: "12px 0 0 12px" }}>
                  <input type="checkbox" checked={selectedIds.includes(item.id)} onChange={(e) => setSelectedIds((prev) => e.target.checked ? [...new Set([...prev, item.id])] : prev.filter((id) => id !== item.id))} />
                </td>
                <td style={{ padding: "16px 12px" }}>
                  <div style={{ fontWeight: 600, color: "var(--ink-strong)", fontSize: "0.95rem" }}>{item.title}</div>
                  <div style={{ fontSize: "0.85rem", color: "var(--ink-soft)", marginTop: "4px", maxWidth: "400px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.content}</div>
                </td>
                <td style={{ padding: "16px 12px" }}>
                  <span style={{ 
                    padding: "4px 10px", 
                    borderRadius: "20px", 
                    fontSize: "0.8rem", 
                    fontWeight: 600,
                    background: `${statusColor(item.status)}15`,
                    color: statusColor(item.status)
                  }}>
                    {statusText(item.status)}
                  </span>
                </td>
                <td style={{ padding: "16px 12px", color: "var(--ink-soft)", fontWeight: 500 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--primary)" }} />
                    {Math.max(0, Number(item.coverageCaseCount ?? 0))} 个关联用例
                  </div>
                </td>
                <td style={{ padding: "16px 12px", color: "var(--ink-soft)", fontSize: "0.85rem" }}>{formatTime(item.updatedAt)}</td>
                <td style={{ padding: "16px 12px", borderRadius: "0 12px 12px 0", textAlign: "right" }}>
                  {isRecycleMode ? (
                    <div style={{ display: "inline-flex", gap: "8px" }}>
                      <button className="btn-mini" style={miniBtnStyle} onClick={() => void restoreOne(item)} disabled={operatingId === item.id}>
                        <RotateCcw size={12} /> 恢复
                      </button>
                      <button className="btn-mini danger" style={miniDangerActionBtnStyle} onClick={() => void hardDeleteOne(item)} disabled={operatingId === item.id}>
                        永久删除
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: "inline-flex", gap: "8px" }}>
                      <button className="btn-mini" style={miniBtnStyle} onClick={() => void openAnalysisHistory(item)}>
                        <History size={12} /> 历史
                      </button>
                      <button className="btn-mini" style={miniActionBtnStyle} onClick={() => openEditModal(item)}>编辑</button>
                      <button className="btn-mini danger" style={miniDangerActionBtnStyle} onClick={() => void deleteOne(item)} disabled={operatingId === item.id}>删除</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="ui-empty">
            <div className="ui-empty-mark" />
            <div style={{ fontSize: ".9rem", fontWeight: 600, color: "var(--ink)" }}>
              {isLoading ? "努力加载中..." : "暂无需求数据"}
            </div>
            <div style={{ fontSize: ".82rem" }}>
              {isLoading ? "正在请求最新数据，请稍候。" : "可通过“新增需求”或“导入”快速开始。"}
            </div>
          </div>
        )}
      </div>

      {/* 底部分页 - 简约风格 */}
      <div style={{ padding: "16px 24px", background: "white", borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ color: "var(--ink-soft)", fontSize: "0.85rem" }}>
          显示 <b>{(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)}</b> / 共 <b>{total}</b> 条记录
        </div>
        <div style={{ display: "inline-flex", gap: "10px" }}>
          <button className="btn-page" style={paginationBtnStyle} disabled={page <= 1 || isLoading} onClick={() => void loadRequirements(page - 1)}>上一页</button>
          <div style={{ display: "flex", alignItems: "center", gap: "4px", padding: "0 12px", fontWeight: 600, color: "var(--primary)" }}>{page}</div>
          <button className="btn-page" style={paginationBtnStyle} disabled={!hasNext || isLoading} onClick={() => void loadRequirements(page + 1)}>下一页</button>
        </div>
      </div>

      {/* 弹窗部分样式略微优化保持统一步调 */}
      {isCreateOpen && (
        <div className="rm-modal-mask" style={modalMaskStyle} onClick={() => !creating && setIsCreateOpen(false)}>
          <div className="rm-modal-card" style={modernModalCardStyle} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 20px 0", fontSize: "1.25rem" }}>新增需求</h3>
            <div style={{ display: "grid", gap: "16px" }}>
              <div className="input-group">
                <label style={modalLabelStyle}>所属项目</label>
                <select value={createProjectId} onChange={(e) => setCreateProjectId(e.target.value)} style={{...fieldStyle, width: "100%"}}>
                  <option value="">选择项目</option>
                  {projectOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </div>
              <div className="input-group">
                <label style={modalLabelStyle}>需求标题</label>
                <input value={createTitle} onChange={(e) => setCreateTitle(e.target.value)} placeholder="简单明了的标题" style={{...fieldStyle, width: "100%"}} />
              </div>
              <div className="input-group">
                <label style={modalLabelStyle}>详细内容 (Markdown)</label>
                <textarea value={createContent} onChange={(e) => setCreateContent(e.target.value)} placeholder="在此输入具体的需求描述内容..." style={{ ...fieldStyle, width: "100%", height: "auto", minHeight: 160, padding: "12px" }} />
              </div>
              <div className="input-group">
                <label style={modalLabelStyle}>标签 / 模块 (使用逗号分隔)</label>
                <input value={createTagsText} onChange={(e) => setCreateTagsText(e.target.value)} placeholder="例如: 登录, 支付, 性能" style={{...fieldStyle, width: "100%"}} />
              </div>
            </div>
            <div style={{ marginTop: "24px", display: "flex", justifyContent: "flex-end", gap: "12px" }}>
              <button style={secondaryActionBtnStyle} onClick={() => setIsCreateOpen(false)} disabled={creating}>取消</button>
              <button style={{...premiumGradientBtnStyle, opacity: creating ? 0.6 : 1, cursor: creating ? "not-allowed" : "pointer"}} onClick={() => void submitCreate()} disabled={creating}>
                {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                {creating ? "创建中..." : "立即创建"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 其他 Modal (Edit/Project) 采用类似结构，此处由于代码长度省略内部重复结构调整，但在逻辑上保持稳定 */}
      {isEditOpen && (
        <div className="rm-modal-mask" style={modalMaskStyle} onClick={() => !editing && setIsEditOpen(false)}>
          <div className="rm-modal-card" style={modernModalCardStyle} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 20px 0" }}>编辑需求</h3>
            <div style={{ display: "grid", gap: "14px" }}>
              <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} style={{...fieldStyle, width: "100%"}} />
              <textarea value={editContent} onChange={(e) => setEditContent(e.target.value)} style={{ ...fieldStyle, width: "100%", minHeight: 150, padding: 12 }} />
              <select value={editStatus} onChange={(e) => setEditStatus(e.target.value as any)} style={{...fieldStyle, width: "100%"}}>
                <option value="draft">草稿 (Draft)</option>
                <option value="analyzing">分析中 (Analyzing)</option>
                <option value="analyzed">已完成 (Analyzed)</option>
                <option value="failed">失败 (Failed)</option>
              </select>
              <input value={editTagsText} onChange={(e) => setEditTagsText(e.target.value)} style={{...fieldStyle, width: "100%"}} />
            </div>
            <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button style={secondaryActionBtnStyle} onClick={() => setIsEditOpen(false)}>取消</button>
              <button style={primaryActionBtnStyle} onClick={() => void submitEdit()} disabled={editing}>{editing ? "同步中..." : "保存更改"}</button>
            </div>
          </div>
        </div>
      )}

      {isProjectOpen && (
        <div className="rm-modal-mask" style={modalMaskStyle} onClick={() => !creatingProject && setIsProjectOpen(false)}>
          <div className="rm-modal-card" style={modernModalCardStyle} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 16px 0" }}>管理项目空间</h3>
            <div style={{ display: "grid", gap: 12 }}>
              <input value={newProjectName} onChange={(e) => setNewProjectName(e.target.value)} placeholder="新项目名称" style={{...fieldStyle, width: "100%"}} />
              <textarea value={newProjectDesc} onChange={(e) => setNewProjectDesc(e.target.value)} placeholder="项目简述..." style={{ ...fieldStyle, width: "100%", height: 100, padding: 12 }} />
            </div>
            <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button style={secondaryActionBtnStyle} onClick={() => setIsProjectOpen(false)}>取消</button>
              <button style={{...primaryActionBtnStyle, opacity: creatingProject ? 0.6 : 1, cursor: creatingProject ? "not-allowed" : "pointer"}} onClick={() => void submitCreateProject()} disabled={creatingProject}>
                {creatingProject ? "创建中..." : "创建空间"}
              </button>
            </div>
          </div>
        </div>
      )}

      {isRestoreProjectOpen && (
        <div className="rm-modal-mask" style={modalMaskStyle} onClick={() => !restoringProject && setIsRestoreProjectOpen(false)}>
          <div className="rm-modal-card" style={{ ...modernModalCardStyle, width: "min(760px, 100%)" }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 8px 0" }}>恢复项目</h3>
            <p style={{ margin: "0 0 14px 0", fontSize: ".86rem", color: "var(--ink-soft)" }}>
              从回收站选择一个项目恢复到当前空间。
            </p>
            <input
              value={restoreSearchText}
              onChange={(e) => setRestoreSearchText(e.target.value)}
              placeholder="搜索项目名称或 ID..."
              style={{ ...fieldStyle, width: "100%", marginBottom: 12, padding: "0 12px" }}
            />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, gap: 10 }}>
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: ".83rem", color: "var(--ink-soft)" }}>
                <input type="checkbox" checked={restoreAllSelected} onChange={toggleSelectAllRestore} />
                全选当前列表
              </label>
              <button
                type="button"
                className="btn-mini danger"
                style={miniDangerActionBtnStyle}
                onClick={() => void batchPurgeDeletedProjects()}
                disabled={restoreSelectedCount === 0 || purgingBatch || restoringProject}
                title="批量永久删除并连带清理关联数据"
              >
                {purgingBatch ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                {purgingBatch ? "删除中..." : `批量永久删除 (${restoreSelectedCount})`}
              </button>
            </div>
            <div
              style={{
                border: "1px solid var(--line)",
                borderRadius: 12,
                maxHeight: 300,
                overflow: "auto",
                background: "rgba(255,255,255,0.86)",
              }}
            >
              {restoreFilteredRows.length === 0 ? (
                <div style={{ padding: 14, fontSize: ".85rem", color: "var(--ink-soft)" }}>没有匹配的项目</div>
              ) : (
                restoreFilteredRows.map((item) => {
                  const selected = restoreProjectId === item.id;
                  return (
                    <div
                      key={item.id}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "24px 1fr auto",
                        alignItems: "center",
                        gap: 8,
                        borderBottom: "1px solid var(--line)",
                        padding: "8px 10px",
                        background: selected ? "rgba(16,185,129,0.08)" : "transparent",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={restoreSelectedIds.includes(item.id)}
                        onChange={() => toggleRestoreSelection(item.id)}
                        disabled={purgingBatch || restoringProject}
                        aria-label={`选择项目 ${item.name}`}
                      />
                      <button
                        type="button"
                        onClick={() => setRestoreProjectId(item.id)}
                        style={{
                          width: "100%",
                          textAlign: "left",
                          border: "none",
                          background: "transparent",
                          padding: "2px 2px 2px 4px",
                          cursor: "pointer",
                        }}
                      >
                        <div style={{ fontWeight: 700, color: "var(--ink)" }}>{item.name}</div>
                        <div style={{ fontSize: ".78rem", color: "var(--ink-soft)" }}>{item.id}</div>
                      </button>
                      <button
                        type="button"
                        className="btn-mini danger"
                        style={miniDangerActionBtnStyle}
                        onClick={() => void purgeDeletedProject(item)}
                        disabled={restoringProject || purgingBatch || purgingProjectId === item.id}
                        title="永久删除并连带清理关联数据"
                      >
                        {purgingProjectId === item.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        {purgingProjectId === item.id ? "删除中..." : "永久删除"}
                      </button>
                    </div>
                  );
                })
              )}
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button style={secondaryActionBtnStyle} onClick={() => setIsRestoreProjectOpen(false)} disabled={restoringProject}>
                取消
              </button>
              <button
                style={{ ...primaryActionBtnStyle, opacity: restoringProject ? 0.7 : 1 }}
                onClick={() => void submitRestoreProject()}
                disabled={restoringProject || !restoreProjectId}
              >
                {restoringProject ? <Loader2 size={16} className="animate-spin" /> : <RotateCcw size={16} />}
                {restoringProject ? "恢复中..." : "确认恢复"}
              </button>
            </div>
          </div>
        </div>
      )}

      {analysisOpen && (
        <div className="rm-modal-mask" style={modalMaskStyle} onClick={() => !analysisLoading && setAnalysisOpen(false)}>
          <div className="rm-modal-card" style={{ ...modernModalCardStyle, width: "min(960px, 100%)" }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 14px 0", fontSize: "1.1rem" }}>分析历史对比: {analysisTitle}</h3>
            {analysisLoading ? (
              <div style={{ padding: "30px 0", textAlign: "center", color: "var(--ink-soft)" }}>加载中...</div>
            ) : analysisVersions.length === 0 ? (
              <div style={{ padding: "20px 0", color: "var(--ink-soft)" }}>暂无分析历史</div>
            ) : (
              <div style={{ display: "grid", gap: 12 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <span style={{ fontSize: ".85rem", color: "var(--ink-soft)" }}>版本A</span>
                  <select value={analysisLeft} onChange={(e) => setAnalysisLeft(Number(e.target.value))} style={smallSelectStyle}>
                    {analysisVersions.map((v, idx) => (
                      <option key={`left-${v.id}`} value={idx}>v{v.version} - {formatTime(v.createdAt)}</option>
                    ))}
                  </select>
                  <span style={{ fontSize: ".85rem", color: "var(--ink-soft)" }}>版本B</span>
                  <select value={analysisRight} onChange={(e) => setAnalysisRight(Number(e.target.value))} style={smallSelectStyle}>
                    {analysisVersions.map((v, idx) => (
                      <option key={`right-${v.id}`} value={idx}>v{v.version} - {formatTime(v.createdAt)}</option>
                    ))}
                  </select>
                  <button style={{ ...smallSelectStyle, cursor: "pointer" }} onClick={() => exportAnalysisDiff("markdown")}>导出 MD</button>
                  <button style={{ ...smallSelectStyle, cursor: "pointer" }} onClick={() => exportAnalysisDiff("html")}>导出 HTML</button>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  {[analysisVersions[analysisLeft], analysisVersions[analysisRight]].map((ver, idx) => (
                    <div key={ver.id + idx} style={{ border: "1px solid var(--line)", borderRadius: 12, padding: 12, background: "white" }}>
                      <div style={{ fontWeight: 700, marginBottom: 6 }}>v{ver.version} · {formatTime(ver.createdAt)}</div>
                      <div style={{ fontSize: ".86rem", color: "var(--ink-soft)", marginBottom: 6 }}>摘要</div>
                      <div style={{ fontSize: ".9rem", lineHeight: 1.5 }}>{ver.summary || "无摘要"}</div>
                      <div style={{ marginTop: 10, fontSize: ".82rem", color: "var(--ink-soft)" }}>
                        功能点 {ver.functionalRequirements?.length || 0} · 非功能 {ver.nonFunctionalRequirements?.length || 0} · 验收 {ver.acceptanceCriteria?.length || 0} · 风险 {ver.risks?.length || 0}
                      </div>
                    </div>
                  ))}
                </div>
                {analysisCompareLoading ? (
                  <div style={{ border: "1px dashed var(--line-strong)", borderRadius: 12, padding: 12, background: "rgba(0,0,0,0.01)", color: "var(--ink-soft)" }}>
                    正在计算版本差异...
                  </div>
                ) : analysisCompare ? (
                  <div style={{ border: "1px dashed var(--line-strong)", borderRadius: 12, padding: 12, background: "rgba(0,0,0,0.01)" }}>
                    <div style={{ fontWeight: 700, marginBottom: 8 }}>字段级变化（A {"->"} B）</div>
                    <div style={{ fontSize: ".85rem", color: "var(--ink-soft)", marginBottom: 6 }}>
                      摘要变化: {analysisCompare.diff.summaryChanged ? "有变化" : "无变化"}
                    </div>
                    <div style={{ display: "grid", gap: 8, fontSize: ".84rem" }}>
                      <div>功能点: +{analysisCompare.diff.functionalRequirements.added.length} / -{analysisCompare.diff.functionalRequirements.removed.length}</div>
                      <div>非功能: +{analysisCompare.diff.nonFunctionalRequirements.added.length} / -{analysisCompare.diff.nonFunctionalRequirements.removed.length}</div>
                      <div>验收标准: +{analysisCompare.diff.acceptanceCriteria.added.length} / -{analysisCompare.diff.acceptanceCriteria.removed.length}</div>
                      <div>风险项: +{analysisCompare.diff.risks.added.length} / -{analysisCompare.diff.risks.removed.length}</div>
                      <div>测试关注点: +{analysisCompare.diff.testFocus.added.length} / -{analysisCompare.diff.testFocus.removed.length}</div>
                      <div>假设条件: +{analysisCompare.diff.assumptions.added.length} / -{analysisCompare.diff.assumptions.removed.length}</div>
                      {[
                        { label: "功能点", detail: analysisCompare.diff.functionalRequirements },
                        { label: "非功能", detail: analysisCompare.diff.nonFunctionalRequirements },
                        { label: "验收标准", detail: analysisCompare.diff.acceptanceCriteria },
                        { label: "风险项", detail: analysisCompare.diff.risks },
                        { label: "测试关注点", detail: analysisCompare.diff.testFocus },
                        { label: "假设条件", detail: analysisCompare.diff.assumptions },
                      ].map(({ label, detail }) => {
                        if ((detail.added?.length || 0) + (detail.removed?.length || 0) === 0) return null;
                        return (
                          <div key={label} style={{ borderTop: "1px solid var(--line)", paddingTop: 6 }}>
                            <div style={{ fontWeight: 600 }}>{label}</div>
                            {detail.added.length > 0 ? (
                              <div style={{ color: "#15803d", marginTop: 2 }}>新增: {detail.added.join("；")}</div>
                            ) : null}
                            {detail.removed.length > 0 ? (
                              <div style={{ color: "#b91c1c", marginTop: 2 }}>删除: {detail.removed.join("；")}</div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            )}
            <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
              <button style={secondaryActionBtnStyle} onClick={() => setAnalysisOpen(false)}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

// --- 高端视觉组件样式常量 ---
const modernInputFieldStyle: CSSProperties = {
  height: 42,
  borderRadius: "12px",
  border: "1px solid var(--line-strong)",
  background: "rgba(255,255,255,0.92)",
  fontSize: "0.95rem",
  transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
  color: "var(--ink)",
  outline: "none"
};

const modernSelectStyle: CSSProperties = {
  height: 42,
  padding: "0 12px",
  borderRadius: "12px",
  border: "1px solid var(--line-strong)",
  background: "rgba(255,255,255,0.92)",
  minWidth: "160px",
  outline: "none"
};

const smallSelectStyle: CSSProperties = {
  height: 32,
  padding: "0 10px",
  fontSize: "0.8rem",
  borderRadius: "8px",
  border: "1px solid var(--line-strong)",
  background: "rgba(255,255,255,0.85)",
  outline: "none"
};

const smallInputStyle: CSSProperties = {
  height: 32,
  padding: "0 10px",
  fontSize: "0.8rem",
  borderRadius: "8px",
  border: "1px solid var(--line-strong)",
  background: "rgba(255,255,255,0.85)",
  outline: "none",
};

const premiumGradientBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "0 20px",
  height: 42,
  borderRadius: 12,
  border: "none",
  background: "linear-gradient(135deg, hsl(var(--theme-h), var(--theme-s), 43%), hsl(var(--theme-h), var(--theme-s), 36%))",
  color: "white",
  fontWeight: 600,
  cursor: "pointer",
  boxShadow: "0 8px 18px hsla(var(--theme-h), var(--theme-s), var(--theme-l), 0.22)",
  transition: "opacity 0.2s, cursor 0.2s"
};

const primaryActionBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "0 18px",
  height: 42,
  borderRadius: 12,
  border: "none",
  background: "linear-gradient(135deg, hsl(var(--theme-h), var(--theme-s), 43%), hsl(var(--theme-h), var(--theme-s), 36%))",
  color: "white",
  fontWeight: 600,
  cursor: "pointer"
};

const secondaryActionBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "0 18px",
  height: 42,
  borderRadius: "12px",
  border: "1px solid var(--line-strong)",
  background: "rgba(255,255,255,0.86)",
  color: "var(--ink)",
  fontWeight: 500,
  cursor: "pointer",
  transition: "all 0.2s"
};

const dangerActionBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "0 18px",
  height: 42,
  borderRadius: "12px",
  border: "1px solid rgba(239, 68, 68, 0.28)",
  background: "rgba(254, 226, 226, 0.78)",
  color: "#b91c1c",
  fontWeight: 500,
  cursor: "pointer",
  transition: "all 0.2s"
};

const ghostBtnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 0,
  height: 34,
  padding: "0 10px",
  borderRadius: "10px",
  border: "1px solid var(--line)",
  background: "rgba(255,255,255,0.72)",
  color: "var(--ink-soft)",
  cursor: "pointer",
  fontSize: "0.78rem",
  fontWeight: 600,
  whiteSpace: "nowrap",
  transition: "all 0.2s"
};

const checkboxLabelStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  fontSize: "0.85rem",
  color: "var(--ink-soft)",
  cursor: "pointer"
};

const paginationBtnStyle: CSSProperties = {
  height: 34,
  padding: "0 14px",
  borderRadius: "10px",
  border: "1px solid var(--line-strong)",
  background: "rgba(255,255,255,0.86)",
  fontSize: "0.85rem",
  fontWeight: 600,
  cursor: "pointer"
};

const miniActionBtnStyle: CSSProperties = {
  padding: "6px 10px",
  borderRadius: "8px",
  border: "1px solid var(--line-strong)",
  background: "rgba(255,255,255,0.84)",
  fontSize: "0.78rem",
  fontWeight: 600,
  whiteSpace: "nowrap",
  cursor: "pointer"
};

const miniDangerActionBtnStyle: CSSProperties = {
  padding: "6px 10px",
  borderRadius: "8px",
  border: "1px solid rgba(239,68,68,0.24)",
  background: "rgba(254,226,226,0.68)",
  color: "#b91c1c",
  fontSize: "0.78rem",
  fontWeight: 600,
  whiteSpace: "nowrap",
  cursor: "pointer"
};

const modernModalCardStyle: CSSProperties = {
  width: "min(680px, 100%)",
  background: "white",
  borderRadius: "24px",
  boxShadow: "0 30px 90px rgba(0,0,0,0.2)",
  padding: "32px",
  border: "1px solid rgba(255,255,255,0.2)"
};

const modalLabelStyle: CSSProperties = {
  display: "block",
  fontSize: "0.85rem",
  fontWeight: 600,
  color: "var(--ink-soft)",
  marginBottom: "6px"
};

const fieldStyle: CSSProperties = { ...modernInputFieldStyle, height: 42 };
const modalMaskStyle: CSSProperties = { position: "fixed", inset: 0, background: "rgba(15,23,42,.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1200, padding: 20 };
const miniBtnStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 8px", borderRadius: 8, border: "1px solid var(--line-strong)", background: "white", cursor: "pointer" };
