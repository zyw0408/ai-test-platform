"use client";

import { type CSSProperties, useState } from "react";
import { Edit3, Loader2, Plus, RotateCcw, Search, Trash2 } from "lucide-react";

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
  const data = payload as { message?: unknown; detail?: unknown };
  if (typeof data.message === "string" && data.message.trim()) return data.message;
  if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
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

export function ProjectManager({
  initialProjects,
  initialPage = 1,
  initialPageSize = 20,
  initialTotal,
  initialHasNext = false,
}: {
  initialProjects: Project[];
  initialPage?: number;
  initialPageSize?: number;
  initialTotal?: number;
  initialHasNext?: boolean;
}) {
  const [rows, setRows] = useState<Project[]>(initialProjects);
  const [queryText, setQueryText] = useState("");
  const [isRecycleMode, setIsRecycleMode] = useState(false);
  const [page, setPage] = useState(initialPage);
  const [pageSize] = useState(initialPageSize);
  const [total, setTotal] = useState(initialTotal ?? initialProjects.length);
  const [hasNext, setHasNext] = useState(initialHasNext);
  const [isLoading, setIsLoading] = useState(false);
  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [selectedRecycleIds, setSelectedRecycleIds] = useState<string[]>([]);

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editingId, setEditingId] = useState("");

  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");

  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const loadData = async (targetPage = 1, recycleMode = isRecycleMode) => {
    const search = new URLSearchParams();
    if (!recycleMode && queryText.trim()) {
      search.set("q", queryText.trim());
    }
    search.set("page", String(targetPage));
    search.set("pageSize", String(pageSize));
    if (!recycleMode) {
      search.set("sortBy", "updated_at");
      search.set("sortOrder", "desc");
    }
    setIsLoading(true);
    setNotice(null);
    try {
      const result = await requestJson<PagedResult<Project>>(
        `${recycleMode ? "/api/projects/recycle-bin" : "/api/projects/search"}?${search.toString()}`,
      );
      setRows(result.items);
      setTotal(result.total);
      setPage(result.page);
      setHasNext(result.hasNext);
      setSelectedRecycleIds([]);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "加载项目失败" });
    } finally {
      setIsLoading(false);
    }
  };

  const openCreate = () => {
    setName("");
    setDesc("");
    setIsCreateOpen(true);
  };

  const openEdit = (project: Project) => {
    setEditingId(project.id);
    setEditName(project.name);
    setEditDesc(project.description || "");
    setIsEditOpen(true);
  };

  const createProject = async () => {
    if (!name.trim()) {
      setNotice({ kind: "error", text: "项目名称不能为空" });
      return;
    }
    setCreating(true);
    try {
      await requestJson<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), description: desc.trim() }),
      });
      setIsCreateOpen(false);
      await loadData(1);
      setNotice({ kind: "success", text: "项目已创建" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "创建项目失败" });
    } finally {
      setCreating(false);
    }
  };

  const updateProject = async () => {
    if (!editingId || !editName.trim()) {
      setNotice({ kind: "error", text: "项目名称不能为空" });
      return;
    }
    setEditing(true);
    try {
      await requestJson<Project>(`/api/projects/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: editName.trim(), description: editDesc.trim() }),
      });
      setIsEditOpen(false);
      await loadData(page);
      setNotice({ kind: "success", text: "项目已更新" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "更新项目失败" });
    } finally {
      setEditing(false);
    }
  };

  const deleteProject = async (project: Project) => {
    if (
      !window.confirm(
        [
          `确认删除项目「${project.name}」吗？`,
          "",
          "该操作会级联删除该项目下的：",
          "1. 需求",
          "2. 测试用例（UI/API）",
          "3. 接口集合/接口请求/环境",
          "4. 运行记录与报告（自动化/性能/安全）",
          "",
          "删除后相关数据将不可在正常列表中使用。",
        ].join("\n"),
      )
    ) return;
    setOperatingId(project.id);
    try {
      await requestJson<null>(`/api/projects/${project.id}`, { method: "DELETE" });
      await loadData(page);
      setNotice({ kind: "success", text: "项目及关联数据已级联删除并移入回收站" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "删除项目失败" });
    } finally {
      setOperatingId(null);
    }
  };

  const restoreProject = async (project: Project) => {
    setOperatingId(project.id);
    try {
      await requestJson<Project>(`/api/projects/${project.id}/restore`, { method: "POST" });
      await loadData(page);
      setNotice({ kind: "success", text: "项目已恢复" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "恢复项目失败" });
    } finally {
      setOperatingId(null);
    }
  };

  const toggleRecycleSelection = (projectId: string) => {
    setSelectedRecycleIds((prev) =>
      prev.includes(projectId) ? prev.filter((id) => id !== projectId) : [...prev, projectId],
    );
  };

  const allRecycleSelected = isRecycleMode && rows.length > 0 && rows.every((item) => selectedRecycleIds.includes(item.id));

  const toggleSelectAllRecycle = () => {
    if (!isRecycleMode || rows.length === 0) return;
    if (allRecycleSelected) {
      setSelectedRecycleIds([]);
      return;
    }
    setSelectedRecycleIds(rows.map((item) => item.id));
  };

  const purgeProject = async (project: Project) => {
    if (!window.confirm(`确认彻底删除项目「${project.name}」吗？此操作不可恢复。`)) return;
    setOperatingId(project.id);
    try {
      await requestJson<null>(`/api/projects/${project.id}/purge`, { method: "DELETE" });
      await loadData(page);
      setNotice({ kind: "success", text: "项目已彻底删除" });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "彻底删除项目失败" });
    } finally {
      setOperatingId(null);
    }
  };

  const batchPurgeProjects = async () => {
    if (!isRecycleMode || selectedRecycleIds.length === 0) return;
    if (!window.confirm(`确认批量彻底删除 ${selectedRecycleIds.length} 个项目吗？此操作不可恢复。`)) return;
    setIsLoading(true);
    try {
      const result = await requestJson<{ deleted: number; failedIds: string[] }>(
        "/api/projects/recycle-bin/batch-delete",
        {
          method: "POST",
          body: JSON.stringify({ ids: selectedRecycleIds }),
        },
      );
      await loadData(page, true);
      const failed = Array.isArray(result?.failedIds) ? result.failedIds.length : 0;
      if (failed > 0) {
        setNotice({ kind: "error", text: `批量删除完成，成功 ${result.deleted}，失败 ${failed}` });
      } else {
        setNotice({ kind: "success", text: `已彻底删除 ${result.deleted} 个项目` });
      }
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "批量彻底删除失败" });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <article className="panel panel-table project-panel" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, padding: 0 }}>
      <div className="table-toolbar pm-toolbar" style={{ borderBottom: "1px solid var(--line)", padding: "16px 20px", display: "flex", flexDirection: "column", gap: "10px", background: "var(--panel-strong)" }}>
        <div className="pm-toolbar-row" style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void loadData(1);
              }
            }}
            placeholder="搜索项目名称/描述"
            style={{ ...fieldStyle, width: "260px" }}
            disabled={isRecycleMode}
          />
          <button onClick={() => void loadData(1)} style={secondaryBtnStyle} disabled={isLoading}>{isLoading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}查询</button>
          <button
            onClick={() => {
              const nextRecycleMode = !isRecycleMode;
              setIsRecycleMode(nextRecycleMode);
              void loadData(1, nextRecycleMode);
            }}
            style={secondaryBtnStyle}
          >
            <RotateCcw size={14} />{isRecycleMode ? "正常列表" : "回收站"}
          </button>
          {!isRecycleMode && <button onClick={openCreate} style={primaryBtnStyle}><Plus size={14} />新增项目</button>}
          {isRecycleMode && (
            <button
              onClick={() => void batchPurgeProjects()}
              style={selectedRecycleIds.length === 0 ? secondaryBtnStyle : miniDangerBtnStyle}
              disabled={selectedRecycleIds.length === 0 || isLoading}
            >
              <Trash2 size={14} />
              批量彻底删除 ({selectedRecycleIds.length})
            </button>
          )}
        </div>
        <div className="pm-count" style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>总数 {total}，当前第 {page} 页。</div>
        {notice && <div className={`pm-notice ${notice.kind === "success" ? "is-success" : "is-error"}`} style={{ padding: "8px 10px", borderRadius: 8, border: notice.kind === "success" ? "1px solid rgba(22,163,74,.3)" : "1px solid rgba(220,38,38,.3)", background: notice.kind === "success" ? "rgba(22,163,74,.08)" : "rgba(220,38,38,.08)" }}>{notice.text}</div>}
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        <table className="table recent-table pm-table" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead style={{ position: "sticky", top: 0, background: "var(--panel)" }}>
            <tr>
              {isRecycleMode ? <th style={{ width: 42 }}><input type="checkbox" checked={allRecycleSelected} onChange={toggleSelectAllRecycle} /></th> : null}
              <th>项目名称</th>
              <th>项目描述</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id}>
                {isRecycleMode ? (
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedRecycleIds.includes(item.id)}
                      onChange={() => toggleRecycleSelection(item.id)}
                    />
                  </td>
                ) : null}
                <td>
                  <div style={{ fontWeight: 600 }}>{item.name}</div>
                  <div style={{ fontSize: ".8rem", color: "var(--ink-soft)" }}>{item.id}</div>
                </td>
                <td>{item.description || "—"}</td>
                <td>{formatTime(item.updatedAt)}</td>
                <td>
                  {isRecycleMode ? (
                    <div style={{ display: "inline-flex", gap: 8 }}>
                      <button className="pm-mini-btn" style={miniBtnStyle} onClick={() => void restoreProject(item)} disabled={operatingId === item.id}>
                        {operatingId === item.id ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                        恢复
                      </button>
                      <button className="pm-mini-btn danger" style={miniDangerBtnStyle} onClick={() => void purgeProject(item)} disabled={operatingId === item.id}>
                        {operatingId === item.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                        彻底删除
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: "inline-flex", gap: 8 }}>
                      <button className="pm-mini-btn" style={miniBtnStyle} onClick={() => openEdit(item)}><Edit3 size={12} />编辑</button>
                      <button className="pm-mini-btn danger" style={miniDangerBtnStyle} onClick={() => void deleteProject(item)} disabled={operatingId === item.id}>
                        {operatingId === item.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                        删除
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={isRecycleMode ? 5 : 4} style={{ textAlign: "center", padding: 42, color: "var(--ink-soft)" }}>{isLoading ? "加载中..." : "暂无数据"}</td></tr>}
          </tbody>
        </table>
      </div>

      <div style={{ padding: "10px 16px", borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between" }}>
        <span style={{ color: "var(--ink-soft)", fontSize: ".85rem" }}>第 {page} 页 / 每页 {pageSize}</span>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button style={secondaryBtnStyle} disabled={page <= 1 || isLoading} onClick={() => void loadData(page - 1)}>上一页</button>
          <button style={secondaryBtnStyle} disabled={!hasNext || isLoading} onClick={() => void loadData(page + 1)}>下一页</button>
        </div>
      </div>

      {isCreateOpen && (
        <div className="pm-modal-mask" style={modalMaskStyle} onClick={() => !creating && setIsCreateOpen(false)}>
          <div className="pm-modal-card" style={modalCardStyle} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>新增项目</h3>
            <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="项目名称" style={fieldStyle} />
              <textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="项目描述" style={{ ...fieldStyle, height: "auto", minHeight: 90, padding: 10 }} />
            </div>
            <div style={{ marginTop: 14, display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button style={secondaryBtnStyle} onClick={() => setIsCreateOpen(false)} disabled={creating}>取消</button>
              <button style={primaryBtnStyle} onClick={() => void createProject()} disabled={creating}>{creating ? "创建中..." : "创建"}</button>
            </div>
          </div>
        </div>
      )}

      {isEditOpen && (
        <div className="pm-modal-mask" style={modalMaskStyle} onClick={() => !editing && setIsEditOpen(false)}>
          <div className="pm-modal-card" style={modalCardStyle} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>编辑项目</h3>
            <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
              <input value={editName} onChange={(e) => setEditName(e.target.value)} placeholder="项目名称" style={fieldStyle} />
              <textarea value={editDesc} onChange={(e) => setEditDesc(e.target.value)} placeholder="项目描述" style={{ ...fieldStyle, height: "auto", minHeight: 90, padding: 10 }} />
            </div>
            <div style={{ marginTop: 14, display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button style={secondaryBtnStyle} onClick={() => setIsEditOpen(false)} disabled={editing}>取消</button>
              <button style={primaryBtnStyle} onClick={() => void updateProject()} disabled={editing}>{editing ? "保存中..." : "保存"}</button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

const fieldStyle: CSSProperties = {
  height: 36,
  borderRadius: 8,
  border: "1px solid var(--line)",
  padding: "0 10px",
  background: "white",
};
const primaryBtnStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 12px", borderRadius: 8, border: "none", background: "var(--primary)", color: "white", cursor: "pointer" };
const secondaryBtnStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 12px", borderRadius: 8, border: "1px solid var(--line-strong)", background: "white", cursor: "pointer" };
const miniBtnStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 8px", borderRadius: 8, border: "1px solid var(--line-strong)", background: "white", cursor: "pointer" };
const miniDangerBtnStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 8px", borderRadius: 8, border: "1px solid rgba(220,38,38,.35)", background: "rgba(220,38,38,.08)", color: "#991b1b", cursor: "pointer" };
const modalMaskStyle: CSSProperties = { position: "fixed", inset: 0, background: "rgba(15,23,42,.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1200, padding: 20 };
const modalCardStyle: CSSProperties = { width: "min(640px,100%)", background: "white", borderRadius: 12, boxShadow: "0 24px 60px rgba(15,23,42,.2)", padding: 18 };
