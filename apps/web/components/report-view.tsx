"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { PieChart, FileText, CheckCircle2, XCircle, Sparkles, Download, LayoutDashboard, Bug, BarChart3, History, RefreshCcw, ExternalLink, Trash2 } from "lucide-react";
import { PageHeader } from "./page-header";

interface ReportStats {
  totalRuns: number;
  passedRuns: number;
  failedRuns: number;
  passRate: number;
  totalCases: number;
  totalProjects: number;
  recentRuns: any[];
  moduleCoverage: any[];
}

interface ExecutionSummary {
  totalRuns: number;
  passRate: number;
  statusBreakdown: Record<string, number>;
  runnerBreakdown: Record<string, number>;
  topFailedCases: Array<{ caseId: string; caseTitle: string; failedCount: number }>;
  topFailureReasons: Array<{ reason: string; count: number }>;
  trends: Array<{ day: string; passed: number; failed: number; running: number; queued: number }>;
}

type HistoryCategory = "all" | "automation" | "performance" | "security";

interface UnifiedHistoryItem {
  id: string;
  type: "automation" | "performance" | "security";
  projectId: string;
  status: string;
  title: string;
  summary: string;
  startedAt: string;
  endedAt: string;
  source: unknown;
}

export function ReportView() {
  const [activeTab, setActiveTab] = useState("overview");
  const [stats, setStats] = useState<ReportStats | null>(null);
  const [execution, setExecution] = useState<ExecutionSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [projectFilter, setProjectFilter] = useState("");
  const [runnerFilter, setRunnerFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [historyTypeFilter, setHistoryTypeFilter] = useState<HistoryCategory>("all");
  const [historyItems, setHistoryItems] = useState<UnifiedHistoryItem[]>([]);
  const [selectedHistoryKeys, setSelectedHistoryKeys] = useState<string[]>([]);
  const [selectedLogRunIds, setSelectedLogRunIds] = useState<string[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");

  // States for AI Diagnosis in 'failures' tab
  const [rcaResult, setRcaResult] = useState("");
  const [isDiagnosing, setIsDiagnosing] = useState(false);

  const normalizeIso = (value: unknown): string => {
    if (!value) return "";
    const text = String(value);
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return "";
    return date.toISOString();
  };

  const toText = (value: unknown, fallback = ""): string => {
    const text = String(value ?? "").trim();
    return text || fallback;
  };

  const loadReports = async () => {
    setIsLoading(true);
    const query = new URLSearchParams();
    if (projectFilter.trim()) query.set("projectId", projectFilter.trim());
    if (runnerFilter) query.set("runnerType", runnerFilter);
    if (statusFilter) query.set("status", statusFilter);
    if (startDate) query.set("startDate", new Date(startDate).toISOString());
    if (endDate) query.set("endDate", new Date(endDate).toISOString());
    query.set("days", "10");
    query.set("limit", "500");
    const qs = query.toString();
    await Promise.all([
      fetch(`/api/reports/dashboard${qs ? `?${qs}` : ""}`).then((res) => res.json()),
      fetch(`/api/reports/execution-summary${qs ? `?${qs}` : ""}`).then((res) => res.json()),
    ])
      .then(([dashboardData, executionData]) => {
        setStats(dashboardData);
        setExecution(executionData);
      })
      .catch(err => console.error(err))
      .finally(() => setIsLoading(false));
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const query = new URLSearchParams();
      if (projectFilter.trim()) query.set("projectId", projectFilter.trim());
      if (runnerFilter) query.set("runnerType", runnerFilter);
      if (statusFilter) query.set("status", statusFilter);

      const [automationRes, performanceRes, securityRes] = await Promise.all([
        fetch(`/api/reports/runs?page=1&pageSize=80${query.toString() ? `&${query.toString()}` : ""}`, { cache: "no-store" }),
        fetch(`/api/testing/performance/runs?limit=80${projectFilter.trim() ? `&projectId=${encodeURIComponent(projectFilter.trim())}` : ""}`, { cache: "no-store" }),
        fetch(`/api/security/scans?limit=80${projectFilter.trim() ? `&projectId=${encodeURIComponent(projectFilter.trim())}` : ""}`, { cache: "no-store" }),
      ]);

      const [automationData, performanceData, securityData] = await Promise.all([
        automationRes.json().catch(() => ({})),
        performanceRes.json().catch(() => []),
        securityRes.json().catch(() => ({})),
      ]);

      const automationRows = Array.isArray((automationData as any)?.items) ? (automationData as any).items : [];
      const performanceRows = Array.isArray(performanceData) ? performanceData : [];
      const securityRows = Array.isArray((securityData as any)?.items) ? (securityData as any).items : [];

      const merged: UnifiedHistoryItem[] = [
        ...automationRows.map((item: any): UnifiedHistoryItem => ({
          id: toText(item?.id, ""),
          type: "automation",
          projectId: toText(item?.projectId, "-"),
          status: toText(item?.status, "unknown"),
          title: toText(item?.caseTitle, "自动化测试执行"),
          summary: toText(item?.summary, `${toText(item?.runnerType, "runner").toUpperCase()} 执行`),
          startedAt: normalizeIso(item?.startedAt ?? item?.createdAt),
          endedAt: normalizeIso(item?.finishedAt),
          source: item,
        })),
        ...performanceRows.map((item: any): UnifiedHistoryItem => ({
          id: toText(item?.id, ""),
          type: "performance",
          projectId: toText(item?.projectId, "-"),
          status: toText(item?.status, "unknown"),
          title: toText(item?.collectionName, "性能压测任务"),
          summary: `TPS ${item?.tps ?? "-"} · P95 ${item?.p95LatencyMs ?? "-"}ms · 成功率 ${item?.successRate ?? "-"}%`,
          startedAt: normalizeIso(item?.createdAt ?? item?.startedAt),
          endedAt: normalizeIso(item?.finishedAt),
          source: item,
        })),
        ...securityRows.map((item: any): UnifiedHistoryItem => ({
          id: toText(item?.scanId || item?.id, ""),
          type: "security",
          projectId: toText(item?.projectId, "-"),
          status: "completed",
          title: "安全扫描报告",
          summary: `漏洞 ${item?.totalIssues ?? 0}（Critical ${item?.criticalCount ?? 0} / High ${item?.highCount ?? 0}）`,
          startedAt: normalizeIso(item?.createdAt),
          endedAt: "",
          source: item,
        })),
      ]
        .filter((item) => item.id)
        .sort((a, b) => {
          const t1 = a.startedAt ? new Date(a.startedAt).getTime() : 0;
          const t2 = b.startedAt ? new Date(b.startedAt).getTime() : 0;
          return t2 - t1;
        });

      setHistoryItems(merged);
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "历史报告加载失败");
      setHistoryItems([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    void loadReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeTab !== "history") return;
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const handleDiagnose = async () => {
    setIsDiagnosing(true);
    setRcaResult("");
    try {
      // Pick the first failed run to diagnose
      const failedRun = stats?.recentRuns.find(r => r.status === 'failed');
      if (!failedRun) {
         setRcaResult("当前没有失败的用例记录需要诊断。");
         return;
      }
      
      const res = await fetch("/api/ai/chat", {
         method: "POST",
         headers: { "Content-Type": "application/json" },
         body: JSON.stringify({ 
           stream: false,
           messages: [{
             role: "user", 
             content: `请帮我诊断这个失败的测试执行。\n用例标题: ${failedRun.caseTitle}\n错误信息: ${failedRun.error || '执行断言失败'}`
           }]
         })
      });
      if (res.ok) {
        const data = await res.json();
        setRcaResult(data.content);
      }
    } catch {
      setRcaResult("AI 诊断过程中发生错误，请重试。");
    } finally {
      setIsDiagnosing(false);
    }
  };

  const handleExportPDF = () => {
    window.print();
  };

  const parseDownloadFilename = (disposition: string | null, fallback: string) => {
    if (!disposition) return fallback;
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match?.[1]) {
      try {
        return decodeURIComponent(utf8Match[1]);
      } catch {
        return utf8Match[1];
      }
    }
    const plainMatch = disposition.match(/filename="?([^"]+)"?/i);
    return plainMatch?.[1] || fallback;
  };

  const handleExportExecution = async (
    format: "json" | "csv" | "markdown",
    template: "weekly" | "monthly" = "weekly",
  ) => {
    const search = new URLSearchParams();
    if (projectFilter.trim()) search.set("projectId", projectFilter.trim());
    if (runnerFilter) search.set("runnerType", runnerFilter);
    if (statusFilter) search.set("status", statusFilter);
    if (startDate) search.set("startDate", new Date(startDate).toISOString());
    if (endDate) search.set("endDate", new Date(endDate).toISOString());
    search.set("format", format);
    search.set("template", template);
    search.set("days", "10");
    search.set("limit", "500");
    try {
      const response = await fetch(`/api/reports/execution-summary/export?${search.toString()}`, {
        method: "GET",
        cache: "no-store",
      });
      if (!response.ok) {
        let message = "报告导出失败";
        try {
          const data = await response.json();
          if (typeof data?.message === "string" && data.message.trim()) {
            message = data.message;
          }
        } catch {}
        throw new Error(message);
      }
      const blob = await response.blob();
      const fallbackName =
        format === "markdown"
          ? `execution-${template}-report.md`
          : `execution-summary.${format}`;
      const fileName = parseDownloadFilename(
        response.headers.get("content-disposition"),
        fallbackName,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      alert(error instanceof Error ? error.message : "报告导出失败");
    }
  };

  const filteredHistoryItems = historyItems.filter((item) =>
    historyTypeFilter === "all" ? true : item.type === historyTypeFilter,
  );
  const historyRowKey = (row: UnifiedHistoryItem): string => `${row.type}:${row.id}`;
  const selectedHistoryRows = filteredHistoryItems.filter((row) => selectedHistoryKeys.includes(historyRowKey(row)));
  const allVisibleSelected = filteredHistoryItems.length > 0 && filteredHistoryItems.every((row) => selectedHistoryKeys.includes(historyRowKey(row)));
  const visibleLogRunIds = (stats?.recentRuns || []).map((run: any) => String(run.id || "")).filter(Boolean);
  const allLogsSelected = visibleLogRunIds.length > 0 && visibleLogRunIds.every((id) => selectedLogRunIds.includes(id));

  const formatHistoryType = (type: UnifiedHistoryItem["type"]): string => {
    if (type === "automation") return "自动化";
    if (type === "performance") return "性能";
    return "安全";
  };

  const exportHistoryRow = (row: UnifiedHistoryItem) => {
    const blob = new Blob([JSON.stringify(row.source, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${row.type}-report-${row.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const deleteHistoryRow = async (row: UnifiedHistoryItem, withConfirm = true) => {
    if (withConfirm && !confirm(`确认删除该报告记录吗？\n${row.id}`)) return false;
    try {
      if (row.type === "automation") {
        const res = await fetch(`/api/reports/run/${encodeURIComponent(row.id)}`, { method: "DELETE" });
        if (!res.ok) throw new Error("自动化报告删除失败");
      } else if (row.type === "performance") {
        const res = await fetch(`/api/testing/performance/runs/${encodeURIComponent(row.id)}/record`, { method: "DELETE" });
        if (!res.ok) throw new Error("性能报告删除失败");
      } else {
        const res = await fetch(`/api/security/scans/${encodeURIComponent(row.id)}`, { method: "DELETE" });
        if (!res.ok) throw new Error("安全报告删除失败");
      }
      return true;
    } catch (error) {
      alert(error instanceof Error ? error.message : "删除失败");
      return false;
    }
  };

  const toggleHistoryRowSelection = (row: UnifiedHistoryItem) => {
    const key = historyRowKey(row);
    setSelectedHistoryKeys((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]));
  };

  const toggleLogSelection = (runId: string) => {
    setSelectedLogRunIds((prev) => (prev.includes(runId) ? prev.filter((id) => id !== runId) : [...prev, runId]));
  };

  const toggleSelectAllLogs = () => {
    if (visibleLogRunIds.length === 0) return;
    setSelectedLogRunIds((prev) => {
      if (allLogsSelected) {
        return prev.filter((id) => !visibleLogRunIds.includes(id));
      }
      return Array.from(new Set([...prev, ...visibleLogRunIds]));
    });
  };

  const deleteExecutionRun = async (runId: string, withConfirm = true): Promise<boolean> => {
    if (withConfirm && !confirm(`确认删除该执行记录吗？\n${runId}`)) return false;
    try {
      const res = await fetch(`/api/reports/run/${encodeURIComponent(runId)}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除执行记录失败");
      return true;
    } catch (error) {
      alert(error instanceof Error ? error.message : "删除执行记录失败");
      return false;
    }
  };

  const batchDeleteExecutionRuns = async () => {
    if (selectedLogRunIds.length === 0) return;
    if (!confirm(`确认批量删除 ${selectedLogRunIds.length} 条执行记录吗？删除后不可恢复。`)) return;
    const failed: string[] = [];
    for (const runId of selectedLogRunIds) {
      // eslint-disable-next-line no-await-in-loop
      const ok = await deleteExecutionRun(runId, false);
      if (!ok) failed.push(runId);
    }
    await loadReports();
    setSelectedLogRunIds([]);
    if (failed.length > 0) {
      alert(`批量删除完成，失败 ${failed.length} 条。`);
    }
  };

  const toggleSelectAllVisibleHistory = () => {
    const visibleKeys = filteredHistoryItems.map(historyRowKey);
    if (visibleKeys.length === 0) return;
    setSelectedHistoryKeys((prev) => {
      if (allVisibleSelected) {
        return prev.filter((item) => !visibleKeys.includes(item));
      }
      return Array.from(new Set([...prev, ...visibleKeys]));
    });
  };

  const batchDeleteHistoryRows = async () => {
    if (selectedHistoryRows.length === 0) return;
    if (!confirm(`确认批量删除 ${selectedHistoryRows.length} 条报告记录吗？删除后不可恢复。`)) return;
    const failed: string[] = [];
    for (const row of selectedHistoryRows) {
      // eslint-disable-next-line no-await-in-loop
      const ok = await deleteHistoryRow(row, false);
      if (!ok) failed.push(row.id);
    }
    await loadHistory();
    setSelectedHistoryKeys([]);
    if (failed.length > 0) {
      alert(`批量删除已完成，失败 ${failed.length} 条。`);
    }
  };

  useEffect(() => {
    setSelectedHistoryKeys([]);
  }, [historyTypeFilter, historyItems.length]);

  useEffect(() => {
    setSelectedLogRunIds([]);
  }, [stats?.recentRuns?.length]);

  if (isLoading || !stats || !execution) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ animation: 'spin 1s linear infinite' }}><PieChart size={32} color="var(--primary)" /></div>
      </div>
    );
  }

  // Generic styling
  const cardStyle = { background: 'var(--bg-main)', border: '1px solid var(--line)', borderRadius: '16px', padding: '24px' };

  return (
    <div style={{ padding: '32px', display: 'flex', flexDirection: 'column', height: '100%', boxSizing: 'border-box' }}>
      {/* 头部导航 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '14px', marginBottom: '24px', flexWrap: 'wrap' }} className="no-print">
        <PageHeader
          icon={<Sparkles size={18} />}
          title="质量扫描报告"
          subtitle="平台全量自动化测试质效统计分析。"
          tags={["趋势分析", "AI 归因", "执行明细"]}
          style={{ marginBottom: 0 }}
        />
        <div style={{ display: 'flex', gap: '12px', marginLeft: 'auto' }}>
          <button onClick={handleExportPDF} style={{ background: 'var(--ink)', color: 'var(--bg-main)', border: 'none', padding: '10px 20px', borderRadius: '10px', fontSize: '0.95rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
            <Download size={16} /> 导出 / 打印 PDF
          </button>
        </div>
      </div>

      <div className="no-print" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: '14px' }}>
        <input value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)} placeholder="项目ID筛选（可选）" style={{ height: 36, borderRadius: 8, border: '1px solid var(--line)', padding: '0 10px' }} />
        <select value={runnerFilter} onChange={(e) => setRunnerFilter(e.target.value)} style={{ height: 36, borderRadius: 8, border: '1px solid var(--line)', padding: '0 10px' }}>
          <option value="">全部Runner</option>
          <option value="api">API</option>
          <option value="ui">UI</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ height: 36, borderRadius: 8, border: '1px solid var(--line)', padding: '0 10px' }}>
          <option value="">全部状态</option>
          <option value="passed">passed</option>
          <option value="failed">failed</option>
          <option value="running">running</option>
          <option value="queued">queued</option>
        </select>
        <input type="datetime-local" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={{ height: 36, borderRadius: 8, border: '1px solid var(--line)', padding: '0 10px' }} />
        <input type="datetime-local" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={{ height: 36, borderRadius: 8, border: '1px solid var(--line)', padding: '0 10px' }} />
        <button onClick={() => void loadReports()} style={{ border: '1px solid var(--line)', background: 'white', borderRadius: 8, padding: '0 12px', cursor: 'pointer' }}>应用筛选</button>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden', ...cardStyle, padding: 0 }}>
        {/* Tab 栏 */}
        <div className="no-print" style={{ display: 'flex', gap: '24px', padding: '0 32px', borderBottom: '1px solid var(--line)', background: 'var(--panel)', flexWrap: 'wrap' }}>
          {[
            { id: 'overview', label: '大盘概览', icon: LayoutDashboard },
            { id: 'failures', label: 'AI 归因诊断', icon: Bug },
            { id: 'logs', label: '执行明细', icon: FileText },
            { id: 'history', label: '历史报告中心', icon: History },
          ].map(tab => (
            <div 
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{ 
                padding: '16px 0', borderBottom: activeTab === tab.id ? '2px solid var(--primary)' : '2px solid transparent',
                color: activeTab === tab.id ? 'var(--primary)' : 'var(--ink-soft)', fontWeight: activeTab === tab.id ? 600 : 500,
                cursor: 'pointer', fontSize: '0.95rem', transition: 'all 0.2s', display: 'flex', alignItems: 'center', gap: '8px'
              }}
            >
              <tab.icon size={16} /> {tab.label}
            </div>
          ))}
        </div>

        {/* 报告内容区 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '32px' }} className="print-content">
          
          {activeTab === 'overview' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
              
              {/* Core Metrics */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '20px' }}>
                <MetricCard title="总体通过率" value={`${stats.passRate}%`} trend="" isGood={stats.passRate > 90} icon={<PieChart color={stats.passRate > 90 ? "#10b981" : "#f59e0b"} size={26} />} />
                <MetricCard title="总执行次数" value={stats.totalRuns.toString()} icon={<FileText color="var(--primary)" size={26} />} />
                <MetricCard title="失败用例" value={stats.failedRuns.toString()} isGood={stats.failedRuns === 0} icon={<XCircle color="#ef4444" size={26} />} />
                <MetricCard title="覆盖项目数" value={stats.totalProjects.toString()} icon={<CheckCircle2 color="#10b981" size={26} />} />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px' }}>
                <div style={{ ...cardStyle }}>
                  <h3 style={{ margin: '0 0 14px 0', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <BarChart3 size={18} /> 执行趋势（最近10天）
                  </h3>
                  <TrendBars trends={execution.trends} />
                </div>
                <div style={{ ...cardStyle }}>
                  <h3 style={{ margin: '0 0 14px 0', fontSize: '1.05rem' }}>执行分布</h3>
                  <div style={{ display: 'grid', gap: 10, fontSize: '.9rem' }}>
                    <div>API: {execution.runnerBreakdown.api || 0}</div>
                    <div>UI: {execution.runnerBreakdown.ui || 0}</div>
                    <div>Passed: {execution.statusBreakdown.passed || 0}</div>
                    <div>Failed: {execution.statusBreakdown.failed || 0}</div>
                    <div>Running: {execution.statusBreakdown.running || 0}</div>
                    <div>Queued: {execution.statusBreakdown.queued || 0}</div>
                  </div>
                  <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
                    <button onClick={() => void handleExportExecution("json")} style={{ border: '1px solid var(--line)', background: 'white', borderRadius: 8, padding: '6px 10px', cursor: 'pointer' }}>导出 JSON</button>
                    <button onClick={() => void handleExportExecution("csv")} style={{ border: '1px solid var(--line)', background: 'white', borderRadius: 8, padding: '6px 10px', cursor: 'pointer' }}>导出 CSV</button>
                    <button onClick={() => void handleExportExecution("markdown", "weekly")} style={{ border: '1px solid var(--line)', background: 'white', borderRadius: 8, padding: '6px 10px', cursor: 'pointer' }}>导出周报</button>
                    <button onClick={() => void handleExportExecution("markdown", "monthly")} style={{ border: '1px solid var(--line)', background: 'white', borderRadius: 8, padding: '6px 10px', cursor: 'pointer' }}>导出月报</button>
                  </div>
                </div>
              </div>

              {/* 模块覆盖率 */}
              <div style={{ display: 'flex', gap: '24px' }}>
                <div style={{ flex: 1, ...cardStyle, padding: '24px' }}>
                  <h3 style={{ margin: '0 0 20px 0', fontSize: '1.2rem', color: 'var(--ink)' }}>独立项目覆盖率与成功率</h3>
                  {stats.moduleCoverage.length === 0 ? (
                    <div style={{ color: 'var(--ink-soft)', padding: '20px', textAlign: 'center' }}>暂无项目执行数据</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {stats.moduleCoverage.map((mod, idx) => (
                        <CoverageBar key={idx} label={mod.name} value={mod.passRate} totalCount={mod.runCount} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'failures' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '900px', margin: '0 auto' }}>
              <div style={{ ...cardStyle }}>
                <h3 style={{ margin: '0 0 14px 0', fontSize: '1.05rem' }}>失败用例 Top 5</h3>
                {execution.topFailedCases.length === 0 ? (
                  <div style={{ color: 'var(--ink-soft)' }}>暂无失败聚合数据</div>
                ) : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {execution.topFailedCases.map((item) => (
                      <div key={item.caseId} style={{ display: 'flex', justifyContent: 'space-between', border: '1px solid var(--line)', borderRadius: 10, padding: '10px 12px' }}>
                        <div style={{ fontWeight: 500 }}>{item.caseTitle}</div>
                        <div style={{ color: '#b91c1c', fontWeight: 600 }}>失败 {item.failedCount}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div style={{ ...cardStyle }}>
                <h3 style={{ margin: '0 0 14px 0', fontSize: '1.05rem' }}>失败原因聚类 Top 5</h3>
                {execution.topFailureReasons.length === 0 ? (
                  <div style={{ color: 'var(--ink-soft)' }}>暂无失败原因聚类</div>
                ) : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {execution.topFailureReasons.map((item, idx) => (
                      <div key={`${item.reason}-${idx}`} style={{ display: 'flex', justifyContent: 'space-between', border: '1px solid var(--line)', borderRadius: 10, padding: '10px 12px' }}>
                        <div style={{ maxWidth: '70%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.reason}</div>
                        <div style={{ color: '#b91c1c', fontWeight: 600 }}>{item.count}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div style={{ background: 'var(--primary-alpha-10)', border: '1px solid var(--primary)', borderRadius: '16px', padding: '32px', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                   <div style={{ background: 'linear-gradient(135deg, var(--primary) 0%, #a855f7 100%)', width: '40px', height: '40px', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                     <Sparkles color="white" size={20} />
                   </div>
                   <h2 style={{ margin: 0, fontSize: '1.4rem', color: 'var(--primary)' }}>全局失败诊断 (Root Cause Analysis)</h2>
                </div>
                
                <p style={{ margin: 0, color: 'var(--ink-soft)', fontSize: '1rem', lineHeight: '1.6' }}>
                  基于最近 {stats.failedRuns} 次测试失败记录，调用大模型（LLM）融合错误日志与用例上下文进行智能扫描。该模块将为您自动归结核心失效原因。
                </p>

                <button 
                  onClick={handleDiagnose} 
                  disabled={isDiagnosing || stats.failedRuns === 0}
                  style={{ background: 'var(--ink)', color: 'var(--bg-main)', border: 'none', padding: '12px 24px', borderRadius: '10px', fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginTop: '8px' }}
                >
                  {isDiagnosing ? "AI 深度诊断分析中..." : "一键开始 AI 归因诊断"}
                </button>

                {rcaResult && (
                  <div style={{ width: '100%', marginTop: '24px', background: 'var(--bg-main)', padding: '24px', borderRadius: '12px', border: '1px solid var(--line)', whiteSpace: 'pre-wrap', lineHeight: '1.6', fontSize: '0.95rem' }}>
                    {rcaResult}
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'logs' && (
            <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--line)', background: 'var(--panel)' }}>
                <div style={{ fontSize: '.9rem', fontWeight: 600, color: 'var(--ink)' }}>执行明细列表</div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button
                    onClick={toggleSelectAllLogs}
                    className="ui-btn ui-btn-muted"
                    style={{ height: 30, padding: '0 10px', fontSize: '.8rem' }}
                  >
                    {allLogsSelected ? "取消全选可见" : "全选可见"}
                  </button>
                  <button
                    onClick={() => void batchDeleteExecutionRuns()}
                    disabled={selectedLogRunIds.length === 0}
                    className={selectedLogRunIds.length === 0 ? "ui-btn ui-btn-muted" : "ui-btn ui-btn-danger"}
                    style={{ height: 30, padding: '0 10px', fontSize: '.8rem' }}
                  >
                    批量删除 ({selectedLogRunIds.length})
                  </button>
                </div>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line)', color: 'var(--ink-soft)', fontSize: '0.85rem', background: 'var(--panel)' }}>
                    <th style={{ padding: '16px 12px', fontWeight: 500, width: 36 }}>
                      <input type="checkbox" checked={allLogsSelected} onChange={toggleSelectAllLogs} />
                    </th>
                    <th style={{ padding: '16px 24px', fontWeight: 500 }}>用例标题</th>
                    <th style={{ padding: '16px 24px', fontWeight: 500 }}>执行类型</th>
                    <th style={{ padding: '16px 24px', fontWeight: 500 }}>状态</th>
                    <th style={{ padding: '16px 24px', fontWeight: 500 }}>时间</th>
                    <th style={{ padding: '16px 24px', fontWeight: 500 }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recentRuns.length === 0 && (
                    <tr><td colSpan={6} style={{ padding: '32px', textAlign: 'center', color: 'var(--ink-soft)'}}>暂无历史执行记录</td></tr>
                  )}
                  {stats.recentRuns.map((run, i) => (
                    <tr key={run.id || i} style={{ borderBottom: '1px solid var(--line)' }}>
                       <td style={{ padding: '16px 12px' }}>
                          <input
                            type="checkbox"
                            checked={selectedLogRunIds.includes(String(run.id || ""))}
                            onChange={() => toggleLogSelection(String(run.id || ""))}
                            disabled={!run.id}
                          />
                       </td>
                       <td style={{ padding: '16px 24px' }}>
                          <div style={{ fontWeight: 500, fontSize: '0.95rem', color: 'var(--ink)', marginBottom: '4px' }}>{run.caseTitle}</div>
                          <div style={{ fontSize: '0.8rem', color: 'var(--ink-soft)' }}>ID: {run.id}</div>
                       </td>
                       <td style={{ padding: '16px 24px' }}>
                          <span style={{ fontSize: '0.8rem', background: 'var(--panel-strong)', padding: '4px 10px', borderRadius: '4px', textTransform: 'uppercase' }}>{run.runnerType}</span>
                       </td>
                       <td style={{ padding: '16px 24px' }}>
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', fontWeight: 600, color: run.status === 'passed' ? '#10b981' : run.status === 'failed' ? '#ef4444' : '#f59e0b' }}>
                            {run.status === 'passed' ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                            {run.status === 'passed' ? '成功' : run.status === 'failed' ? '失败' : run.status}
                          </div>
                       </td>
                       <td style={{ padding: '16px 24px', color: 'var(--ink-soft)', fontSize: '0.9rem' }}>
                          {run.startedAt ? new Date(run.startedAt).toLocaleString() : '-'}
                       </td>
                       <td style={{ padding: '16px 24px' }}>
                          <button
                            onClick={async () => {
                              const runId = String(run.id || "");
                              if (!runId) return;
                              const ok = await deleteExecutionRun(runId);
                              if (ok) {
                                setSelectedLogRunIds((prev) => prev.filter((id) => id !== runId));
                                await loadReports();
                              }
                            }}
                            className="ui-btn ui-btn-danger"
                            style={{ height: 30, padding: '0 10px', fontSize: '.8rem' }}
                            disabled={!run.id}
                          >
                            <Trash2 size={13} /> 删除
                          </button>
                       </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {activeTab === 'history' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ ...cardStyle, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.05rem' }}>历史报告中心</h3>
                  <div style={{ marginTop: 6, color: 'var(--ink-soft)', fontSize: '.9rem' }}>
                    已持久化保存自动化测试报告、性能压测报告、安全扫描报告。关闭页面后仍可在这里查看历史数据。
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <button
                    onClick={toggleSelectAllVisibleHistory}
                    className="ui-btn ui-btn-muted"
                    style={{ height: 34, padding: '0 10px', fontSize: '.8rem' }}
                  >
                    {allVisibleSelected ? "取消全选可见" : "全选可见"}
                  </button>
                  <button
                    onClick={() => void batchDeleteHistoryRows()}
                    disabled={selectedHistoryRows.length === 0}
                    className={selectedHistoryRows.length === 0 ? "ui-btn ui-btn-muted" : "ui-btn ui-btn-danger"}
                    style={{ height: 34, padding: '0 10px', fontSize: '.8rem' }}
                  >
                    批量删除 ({selectedHistoryRows.length})
                  </button>
                  <select
                    value={historyTypeFilter}
                    onChange={(e) => setHistoryTypeFilter(e.target.value as HistoryCategory)}
                    style={{ height: 34, borderRadius: 8, border: '1px solid var(--line)', padding: '0 10px' }}
                  >
                    <option value="all">全部类型</option>
                    <option value="automation">自动化</option>
                    <option value="performance">性能</option>
                    <option value="security">安全</option>
                  </select>
                  <button
                    onClick={() => void loadHistory()}
                    style={{ border: '1px solid var(--line)', background: 'white', borderRadius: 8, padding: '6px 10px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                  >
                    <RefreshCcw size={14} /> 刷新
                  </button>
                </div>
              </div>

              <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--line)', color: 'var(--ink-soft)', fontSize: '0.85rem', background: 'var(--panel)' }}>
                      <th style={{ padding: '14px 12px', fontWeight: 500, width: 36 }}>
                        <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAllVisibleHistory} />
                      </th>
                      <th style={{ padding: '14px 18px', fontWeight: 500 }}>类型</th>
                      <th style={{ padding: '14px 18px', fontWeight: 500 }}>报告 ID</th>
                      <th style={{ padding: '14px 18px', fontWeight: 500 }}>项目</th>
                      <th style={{ padding: '14px 18px', fontWeight: 500 }}>状态</th>
                      <th style={{ padding: '14px 18px', fontWeight: 500 }}>摘要</th>
                      <th style={{ padding: '14px 18px', fontWeight: 500 }}>时间</th>
                      <th style={{ padding: '14px 18px', fontWeight: 500 }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyLoading && (
                      <tr><td colSpan={8} style={{ padding: '24px 18px', color: 'var(--ink-soft)' }}>历史报告加载中...</td></tr>
                    )}
                    {!historyLoading && historyError && (
                      <tr><td colSpan={8} style={{ padding: '24px 18px', color: '#b91c1c' }}>{historyError}</td></tr>
                    )}
                    {!historyLoading && !historyError && filteredHistoryItems.length === 0 && (
                      <tr><td colSpan={8} style={{ padding: '24px 18px', color: 'var(--ink-soft)' }}>暂无历史报告记录</td></tr>
                    )}
                    {!historyLoading && !historyError && filteredHistoryItems.map((row) => (
                      <tr key={`${row.type}-${row.id}`} style={{ borderBottom: '1px solid var(--line)' }}>
                        <td style={{ padding: '14px 12px' }}>
                          <input type="checkbox" checked={selectedHistoryKeys.includes(historyRowKey(row))} onChange={() => toggleHistoryRowSelection(row)} />
                        </td>
                        <td style={{ padding: '14px 18px' }}>
                          <span style={{ fontSize: '.8rem', borderRadius: 999, background: 'var(--panel-strong)', padding: '4px 10px' }}>
                            {formatHistoryType(row.type)}
                          </span>
                        </td>
                        <td style={{ padding: '14px 18px', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace', fontSize: '.82rem' }}>{row.id}</td>
                        <td style={{ padding: '14px 18px' }}>{row.projectId || "-"}</td>
                        <td style={{ padding: '14px 18px' }}>
                          <span style={{ color: row.status === 'passed' || row.status === 'completed' ? '#10b981' : row.status === 'failed' ? '#ef4444' : 'var(--ink-soft)', fontWeight: 600 }}>
                            {row.status}
                          </span>
                        </td>
                        <td style={{ padding: '14px 18px', maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.summary}>{row.summary}</td>
                        <td style={{ padding: '14px 18px', color: 'var(--ink-soft)', fontSize: '.85rem' }}>
                          {row.startedAt ? new Date(row.startedAt).toLocaleString() : "-"}
                        </td>
                        <td style={{ padding: '14px 18px' }}>
                          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            {row.type === "automation" ? (
                              <Link
                                href={`/reports/${encodeURIComponent(row.id)}`}
                                className="ui-btn ui-btn-muted"
                                style={{ height: 30, padding: '0 10px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '.8rem' }}
                              >
                                <ExternalLink size={13} /> 查看
                              </Link>
                            ) : row.type === "performance" ? (
                              <button
                                onClick={() => window.open(`/api/testing/performance/runs/${encodeURIComponent(row.id)}`, "_blank")}
                                className="ui-btn ui-btn-muted"
                                style={{ height: 30, padding: '0 10px', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '.8rem' }}
                              >
                                <ExternalLink size={13} /> 查看
                              </button>
                            ) : (
                              <button
                                onClick={() => exportHistoryRow(row)}
                                className="ui-btn ui-btn-muted"
                                style={{ height: 30, padding: '0 10px', fontSize: '.8rem' }}
                              >
                                导出
                              </button>
                            )}
                            <button
                              onClick={async () => {
                                const ok = await deleteHistoryRow(row);
                                if (ok) {
                                  setSelectedHistoryKeys((prev) => prev.filter((key) => key !== historyRowKey(row)));
                                  await loadHistory();
                                }
                              }}
                              className="ui-btn ui-btn-danger"
                              style={{ height: 30, padding: '0 10px', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '.8rem' }}
                            >
                              <Trash2 size={13} /> 删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}

// -------------------------------------------------------------
// Component Helpers
// -------------------------------------------------------------

function TrendBars({ trends }: { trends: Array<{ day: string; passed: number; failed: number; running: number; queued: number }> }) {
  if (!Array.isArray(trends) || trends.length === 0) {
    return <div style={{ color: 'var(--ink-soft)' }}>暂无趋势数据</div>;
  }
  const maxValue = Math.max(1, ...trends.map((item) => item.passed + item.failed + item.running + item.queued));
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, flexWrap: 'wrap' }}>
      {trends.map((item) => {
        const total = item.passed + item.failed + item.running + item.queued;
        const h = Math.max(12, Math.round((total / maxValue) * 84));
        return (
          <div key={item.day} style={{ width: 44, display: 'grid', justifyItems: 'center', gap: 4 }}>
            <div style={{ width: 20, height: h, borderRadius: 8, border: '1px solid var(--line)', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', background: 'rgba(100,116,139,.08)' }}>
              <div style={{ flex: item.passed || 0, background: 'rgba(16,185,129,.75)' }} />
              <div style={{ flex: item.failed || 0, background: 'rgba(239,68,68,.75)' }} />
              <div style={{ flex: item.running || 0, background: 'rgba(59,130,246,.75)' }} />
              <div style={{ flex: item.queued || 0, background: 'rgba(100,116,139,.55)' }} />
            </div>
            <div style={{ fontSize: '.72rem', color: 'var(--ink-soft)' }}>{item.day}</div>
          </div>
        );
      })}
    </div>
  );
}

function MetricCard({ title, value, subtext, trend, isGood, icon }: any) {
  return (
    <div style={{ padding: '24px', borderRadius: '16px', background: 'var(--panel)', border: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '16px', position: 'relative', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ fontSize: '0.95rem', color: 'var(--ink-soft)', fontWeight: 500 }}>{title}</div>
        <div style={{ padding: '8px', background: 'var(--bg-main)', borderRadius: '10px' }}>{icon}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
        <h2 style={{ margin: 0, fontSize: '2.4rem', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--ink)' }}>{value}</h2>
        {trend && (
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: isGood ? '#10b981' : '#ef4444', background: isGood ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)', padding: '2px 8px', borderRadius: '4px' }}>
            {trend}
          </span>
        )}
      </div>
      {subtext && <div style={{ fontSize: '0.85rem', color: 'var(--ink-soft)' }}>{subtext}</div>}
    </div>
  );
}

function CoverageBar({ label, value, totalCount }: { label: string, value: number, totalCount: number }) {
  const isHigh = value >= 95;
  const isWarning = value < 95 && value > 80;
  const color = isHigh ? '#10b981' : isWarning ? '#f59e0b' : '#ef4444';
  
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', fontWeight: 500 }}>
        <span style={{ color: 'var(--ink)' }}>{label} <span style={{ color: 'var(--ink-soft)', fontSize: '0.8rem', marginLeft: '6px' }}>({totalCount} 次运行)</span></span>
        <span style={{ color }}>{value}%</span>
      </div>
      <div style={{ height: '8px', width: '100%', background: 'var(--panel-strong)', borderRadius: '4px', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${value}%`, background: color, borderRadius: '4px' }} />
      </div>
    </div>
  );
}
