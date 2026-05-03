"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { 
  Activity, 
  Play, 
  Loader2, 
  CheckCircle2, 
  AlertCircle,
  TrendingDown,
  Timer,
  FileText,
  Zap,
  ArrowRight
} from "lucide-react";
import { 
  listApiCollections, 
  listApiCollectionRequests,
  listApiCollectionEnvironments,
  startApiPerformanceRun,
  listApiPerformanceRuns,
  stopApiPerformanceRun,
  getApiPerformanceCapacity,
  compareApiPerformanceRuns,
  getApiPerformanceRegressionConfig,
  updateApiPerformanceRegressionConfig,
  batchDeleteApiPerformanceRunRecords,
} from "../lib/api";
import type { Project, ApiCollection, ApiEnvironment } from "../lib/api";

interface ApiRequestLite {
  id: string;
  name?: string;
  method?: string;
  url?: string;
  groupName?: string;
  isFolder?: boolean;
}

interface PerformancePoint {
  timestamp: number;
  tps: number;
  latencyMs: number;
  errorRate: number;
}

interface PerformanceRunResult {
  runId: string;
  totalRequests: number;
  successCount: number;
  failCount: number;
  avgLatencyMs: number;
  p95LatencyMs: number;
  p99LatencyMs: number;
  maxLatencyMs: number;
  tps: number;
  timeSeries: PerformancePoint[];
  status: string;
  passedSla: boolean;
  errorMsg: string | null;
}

interface PerformanceRunEntity {
  id: string;
  status: string;
  createdAt?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  progress?: {
    elapsedSeconds?: number;
    totalRequests?: number;
    successCount?: number;
    failCount?: number;
    tps?: number;
    errorRate?: number;
  };
  result?: PerformanceRunResult | null;
  regression?: {
    regressed?: boolean;
    alerts?: string[];
    deltas?: {
      tpsDelta?: number;
      p95DeltaMs?: number;
      errorRateDelta?: number;
    };
  } | null;
  errorMsg?: string | null;
}

interface PerformanceCapacity {
  maxConcurrentRuns: number;
  maxQueueSize: number;
  projectMaxConcurrentRuns?: number;
  projectMaxQueueSize?: number;
  running: number;
  queued: number;
}

interface PerformanceCompareData {
  latest?: {
    runId: string;
    tps: number;
    p95LatencyMs: number;
    errorRate: number;
    createdAt: string;
  } | null;
  baseline?: {
    runId: string;
    tps: number;
    p95LatencyMs: number;
    errorRate: number;
    createdAt: string;
  } | null;
  deltas?: {
    tpsDelta: number;
    p95DeltaMs: number;
    errorRateDelta: number;
  } | null;
  timeline?: Array<{
    runId: string;
    tps: number;
    p95LatencyMs: number;
    errorRate: number;
    createdAt: string;
  }>;
}

export function PerformanceTestView({ projects }: { projects: Project[] }) {
  const runEventSourceRef = useRef<EventSource | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [collections, setCollections] = useState<ApiCollection[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState<string>("");
  const [collectionRequests, setCollectionRequests] = useState<ApiRequestLite[]>([]);
  const [selectedRequestIds, setSelectedRequestIds] = useState<string[]>([]);
  const [requestKeyword, setRequestKeyword] = useState("");
  const [requestMethodFilter, setRequestMethodFilter] = useState("all");
  const [requestGroupFilter, setRequestGroupFilter] = useState("all");
  const [environments, setEnvironments] = useState<ApiEnvironment[]>([]);
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState<string>("");
  const [vus, setVus] = useState(10);
  const [duration, setDuration] = useState(30);
  const [rampUp, setRampUp] = useState(5);
  const [targetTps, setTargetTps] = useState<number>(0);
  const [slaP95, setSlaP95] = useState<number>(500);
  const [slaErr, setSlaErr] = useState<number>(0.01);
  const [timeoutMs, setTimeoutMs] = useState<number>(15000);
  const [verifySsl, setVerifySsl] = useState(true);
  const [dataFileUri, setDataFileUri] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string>("");
  const [runStatus, setRunStatus] = useState<string>("");
  const [progress, setProgress] = useState<PerformanceRunEntity["progress"] | null>(null);
  const [recentRuns, setRecentRuns] = useState<PerformanceRunEntity[]>([]);
  const [runFilterStatus, setRunFilterStatus] = useState<string>("all");
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [capacity, setCapacity] = useState<PerformanceCapacity | null>(null);
  const [compareData, setCompareData] = useState<PerformanceCompareData | null>(null);
  const [regressionInfo, setRegressionInfo] = useState<PerformanceRunEntity["regression"] | null>(null);
  const [regressionThresholds, setRegressionThresholds] = useState<{
    maxP95DeltaMs: number;
    maxErrorRateDelta: number;
    minTpsDelta: number;
  }>({
    maxP95DeltaMs: 100,
    maxErrorRateDelta: 0.02,
    minTpsDelta: -5,
  });
  const [detectedColumns, setDetectedColumns] = useState<string[]>([]);
  const [result, setResult] = useState<PerformanceRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const chartPaths = useMemo(() => {
    const series = result?.timeSeries || [];
    if (series.length === 0) {
      return { width: 0, areaPath: "", linePath: "" };
    }
    const width = Math.max(series.length * 50, 50);
    const tpsMax = Math.max(...series.map((point) => point.tps), 1);
    const points = series
      .map((point, index) => {
        const x = index * 50;
        const y = 120 - (point.tps / tpsMax) * 100;
        return { x, y };
      });
    const pointPath = points.map((point) => `L ${point.x},${point.y}`).join(" ");
    const firstY = points[0]?.y ?? 120;
    const lastX = points[points.length - 1]?.x ?? 0;
    return {
      width,
      areaPath: `M 0,120 ${pointPath} L ${lastX},120 Z`,
      linePath: `M 0,${firstY} ${pointPath}`,
    };
  }, [result?.timeSeries]);

  const closeRunEventSource = () => {
    if (runEventSourceRef.current) {
      runEventSourceRef.current.close();
      runEventSourceRef.current = null;
    }
  };

  const handleRunEvent = (run: PerformanceRunEntity) => {
    setRunStatus(run.status);
    setProgress(run.progress ?? null);
    if (run.result) {
      setResult(run.result);
    }
    if (run.regression) {
      setRegressionInfo(run.regression);
    }
    if (run.errorMsg) {
      setError(run.errorMsg);
    }
    if (run.status === "completed" || run.status === "failed" || run.status === "cancelled") {
      closeRunEventSource();
      setIsRunning(false);
      setActiveRunId("");
      void loadRecentRuns(selectedProjectId);
      void loadCompareData(selectedProjectId, selectedCollectionId);
      void loadCapacity();
    }
  };

  useEffect(() => {
    if (projects.length > 0 && !selectedProjectId) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId) {
      void loadCollections(selectedProjectId);
      void loadRecentRuns(selectedProjectId);
      void loadCapacity();
      void loadRegressionConfig();
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedCollectionId) {
      setEnvironments([]);
      setSelectedEnvironmentId("");
      setCollectionRequests([]);
      setSelectedRequestIds([]);
      return;
    }
    void (async () => {
      try {
        const envRows = await listApiCollectionEnvironments(selectedCollectionId);
        setEnvironments(envRows);
        const defaultEnv = envRows.find((e) => e.isDefault) ?? envRows[0];
        setSelectedEnvironmentId(defaultEnv?.id ?? "");
      } catch {
        setEnvironments([]);
        setSelectedEnvironmentId("");
      }
      try {
        const reqRows = await listApiCollectionRequests(selectedCollectionId);
        const runnable = (Array.isArray(reqRows) ? reqRows : []).filter((item) => !Boolean(item?.isFolder));
        setCollectionRequests(runnable);
        setSelectedRequestIds(runnable.map((item) => String(item.id)));
      } catch {
        setCollectionRequests([]);
        setSelectedRequestIds([]);
      }
    })();
  }, [selectedCollectionId]);

  useEffect(() => {
    if (selectedProjectId && selectedCollectionId) {
      void loadCompareData(selectedProjectId, selectedCollectionId);
    } else {
      setCompareData(null);
    }
  }, [selectedProjectId, selectedCollectionId]);

  useEffect(() => {
    if (!activeRunId) return;
    closeRunEventSource();
    const source = new EventSource(`/api/testing/performance/runs/${encodeURIComponent(activeRunId)}/events`);
    runEventSourceRef.current = source;
    const onStatus = (event: MessageEvent<string>) => {
      try {
        handleRunEvent(JSON.parse(event.data) as PerformanceRunEntity);
      } catch {
        // ignore malformed chunk
      }
    };
    source.addEventListener("status", onStatus as EventListener);
    source.onerror = () => {
      closeRunEventSource();
      setIsRunning(false);
      setActiveRunId("");
      setError("性能任务实时连接中断，请刷新后重试。");
    };
    return () => {
      closeRunEventSource();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRunId, selectedProjectId, selectedCollectionId]);

  useEffect(() => {
    return () => {
      closeRunEventSource();
    };
  }, []);

  const loadRecentRuns = async (projectId: string) => {
    if (!projectId) return;
    try {
      const rows = await listApiPerformanceRuns({ projectId, limit: 20 });
      setRecentRuns(Array.isArray(rows) ? rows : []);
      setSelectedRunIds([]);
    } catch {
      setRecentRuns([]);
      setSelectedRunIds([]);
    }
  };

  const loadRegressionConfig = async () => {
    try {
      const data = await getApiPerformanceRegressionConfig();
      setRegressionThresholds({
        maxP95DeltaMs: Number(data?.maxP95DeltaMs ?? 100),
        maxErrorRateDelta: Number(data?.maxErrorRateDelta ?? 0.02),
        minTpsDelta: Number(data?.minTpsDelta ?? -5),
      });
    } catch {
      // no-op: keep defaults
    }
  };

  const loadCapacity = async () => {
    try {
      const data = await getApiPerformanceCapacity();
      setCapacity(data as PerformanceCapacity);
    } catch {
      setCapacity(null);
    }
  };

  const loadCompareData = async (projectId: string, collectionId: string) => {
    if (!projectId || !collectionId) {
      setCompareData(null);
      return;
    }
    try {
      const data = await compareApiPerformanceRuns({ projectId, collectionId, limit: 20 });
      setCompareData(data as PerformanceCompareData);
    } catch {
      setCompareData(null);
    }
  };

  const loadCollections = async (projId: string) => {
    try {
      const data = await listApiCollections(projId);
      setCollections(data);
      if (data.length > 0) {
        setSelectedCollectionId(data[0].id);
      } else {
        setSelectedCollectionId("");
      }
    } catch (e) {
      console.error("加载集合失败", e);
    }
  };

  const handleRun = async () => {
    if (!selectedCollectionId) return;
    if (selectedRequestIds.length === 0) {
      setError("请至少选择一个接口再启动压测。");
      return;
    }
    setIsRunning(true);
    setRunStatus("queued");
    setProgress(null);
    setError(null);
    setResult(null);
    setRegressionInfo(null);

    try {
      const run = await startApiPerformanceRun({
        projectId: selectedProjectId,
        collectionId: selectedCollectionId,
        environmentId: selectedEnvironmentId || null,
        requestIds: selectedRequestIds,
        vus,
        durationSeconds: duration,
        rampUpSeconds: rampUp,
        targetTps: targetTps > 0 ? targetTps : null,
        slaMaxP95Latency: slaP95 || null,
        slaMaxErrorRate: slaErr || null,
        timeoutMs,
        verifySsl,
        dataFileUri: dataFileUri.trim() || null,
      });
      setActiveRunId(run.id);
      setRunStatus(run.status);
      setProgress(run.progress ?? null);
      void loadRecentRuns(selectedProjectId);
      void loadCapacity();
    } catch (err: any) {
      setError(err.message);
      setRunStatus("failed");
      setIsRunning(false);
    }
  };

  const handleStopRun = async () => {
    if (!activeRunId) return;
    try {
      await stopApiPerformanceRun(activeRunId);
      closeRunEventSource();
      setRunStatus("cancelled");
      setIsRunning(false);
      setActiveRunId("");
      await loadRecentRuns(selectedProjectId);
      await loadCompareData(selectedProjectId, selectedCollectionId);
      await loadCapacity();
    } catch (err: any) {
      setError(err?.message || "停止任务失败");
    }
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

  const handleExportRun = async (runId: string, format: "json" | "csv") => {
    try {
      const response = await fetch(`/api/testing/performance/runs/${runId}/export?format=${format}`, {
        method: "GET",
        cache: "no-store",
      });
      if (!response.ok) {
        let message = "性能报告导出失败";
        try {
          const data = await response.json();
          if (typeof data?.message === "string" && data.message.trim()) {
            message = data.message;
          }
        } catch {}
        throw new Error(message);
      }
      const blob = await response.blob();
      const fileName = parseDownloadFilename(
        response.headers.get("content-disposition"),
        `${runId}.${format}`,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err?.message || "性能报告导出失败");
    }
  };

  const toggleRunSelection = (runId: string) => {
    setSelectedRunIds((prev) =>
      prev.includes(runId) ? prev.filter((id) => id !== runId) : [...prev, runId]
    );
  };

  const toggleRequestSelection = (requestId: string) => {
    setSelectedRequestIds((prev) =>
      prev.includes(requestId) ? prev.filter((id) => id !== requestId) : [...prev, requestId],
    );
  };

  const selectAllVisibleRequests = () => {
    const visibleIds = visibleRequests.map((item) => String(item.id));
    setSelectedRequestIds((prev) => Array.from(new Set([...prev, ...visibleIds])));
  };

  const clearAllVisibleRequests = () => {
    const visibleSet = new Set(visibleRequests.map((item) => String(item.id)));
    setSelectedRequestIds((prev) => prev.filter((id) => !visibleSet.has(id)));
  };

  const invertVisibleRequests = () => {
    const visibleIds = visibleRequests.map((item) => String(item.id));
    const visibleSet = new Set(visibleIds);
    setSelectedRequestIds((prev) => {
      const prevSet = new Set(prev);
      const next = prev.filter((id) => !visibleSet.has(id));
      for (const id of visibleIds) {
        if (!prevSet.has(id)) next.push(id);
      }
      return next;
    });
  };

  const handleSaveRegressionThresholds = async () => {
    try {
      await updateApiPerformanceRegressionConfig(regressionThresholds);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "保存回归阈值失败");
    }
  };

  const handleBatchDeleteRuns = async () => {
    if (selectedRunIds.length === 0) return;
    try {
      await batchDeleteApiPerformanceRunRecords({ runIds: selectedRunIds });
      await loadRecentRuns(selectedProjectId);
      await loadCompareData(selectedProjectId, selectedCollectionId);
    } catch (err: any) {
      setError(err?.message || "批量删除失败");
    }
  };

  const filteredRuns = recentRuns.filter((run) => {
    if (runFilterStatus === "all") return true;
    if (runFilterStatus === "regressed") return !!run.regression?.regressed;
    return run.status === runFilterStatus;
  });

  const requestMethodOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of collectionRequests) {
      const method = String(item.method || "").trim().toUpperCase();
      if (method) set.add(method);
    }
    return ["all", ...Array.from(set)];
  }, [collectionRequests]);

  const requestGroupOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of collectionRequests) {
      const group = String(item.groupName || "default").trim();
      if (group) set.add(group);
    }
    return ["all", ...Array.from(set)];
  }, [collectionRequests]);

  const visibleRequests = useMemo(() => {
    const kw = requestKeyword.trim().toLowerCase();
    return collectionRequests.filter((item) => {
      const method = String(item.method || "").trim().toUpperCase();
      const group = String(item.groupName || "default").trim();
      const name = String(item.name || "").toLowerCase();
      const url = String(item.url || "").toLowerCase();
      if (requestMethodFilter !== "all" && method !== requestMethodFilter) return false;
      if (requestGroupFilter !== "all" && group !== requestGroupFilter) return false;
      if (kw && !name.includes(kw) && !url.includes(kw)) return false;
      return true;
    });
  }, [collectionRequests, requestGroupFilter, requestKeyword, requestMethodFilter]);

  return (
    <div className={result ? "perf-layout" : "perf-layout is-compact"} style={{ padding: 0 }}>
      {/* 左侧配置栏 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        <section className="stat-card" style={{ padding: 28, display: 'grid', gap: 24, background: 'var(--panel-strong)' }}>
          <div>
            <div className="kicker" style={{ marginBottom: 4 }}>Performance Setup</div>
            <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 700 }}>压测引擎配置</h2>
          </div>

          <div style={{ display: 'grid', gap: 18 }}>
            <div style={formGroupStyle}>
              <label style={labelStyle}>目标项目</label>
              <select value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)} style={refinedSelectStyle}>
                {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>

            <div style={formGroupStyle}>
              <label style={labelStyle}>API 业务集合</label>
              <select value={selectedCollectionId} onChange={(e) => setSelectedCollectionId(e.target.value)} style={refinedSelectStyle}>
                {collections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>

            <div style={formGroupStyle}>
              <label style={labelStyle}>测试环境 (可选)</label>
              <select value={selectedEnvironmentId} onChange={(e) => setSelectedEnvironmentId(e.target.value)} style={refinedSelectStyle}>
                <option value="">不使用环境变量</option>
                {environments.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            </div>

            <div style={{ display: "grid", gap: 10, border: "1px solid var(--line)", borderRadius: 12, padding: 12, background: "rgba(255,255,255,.65)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <label style={{ ...labelStyle, margin: 0 }}>压测接口选择</label>
                <span style={{ fontSize: ".76rem", color: "var(--ink-soft)" }}>
                  已选 {selectedRequestIds.length} / {collectionRequests.length}
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 }}>
                <input
                  className="search-box"
                  value={requestKeyword}
                  onChange={(e) => setRequestKeyword(e.target.value)}
                  placeholder="搜索名称/URL"
                />
                <select value={requestMethodFilter} onChange={(e) => setRequestMethodFilter(e.target.value)} style={refinedSelectStyle}>
                  {requestMethodOptions.map((method) => (
                    <option key={method} value={method}>
                      {method === "all" ? "全部方法" : method}
                    </option>
                  ))}
                </select>
                <select value={requestGroupFilter} onChange={(e) => setRequestGroupFilter(e.target.value)} style={refinedSelectStyle}>
                  {requestGroupOptions.map((group) => (
                    <option key={group} value={group}>
                      {group === "all" ? "全部分组" : group}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" className="ui-btn ui-btn-muted" style={smallActionBtnStyle} onClick={selectAllVisibleRequests}>全选可见</button>
                <button type="button" className="ui-btn ui-btn-muted" style={smallActionBtnStyle} onClick={clearAllVisibleRequests}>清空可见</button>
                <button type="button" className="ui-btn ui-btn-muted" style={smallActionBtnStyle} onClick={invertVisibleRequests}>反选可见</button>
              </div>
              <div style={{ maxHeight: 180, overflowY: "auto", display: "grid", gap: 6 }}>
                {visibleRequests.length === 0 ? (
                  <div style={{ fontSize: ".8rem", color: "var(--ink-soft)", padding: "8px 2px" }}>当前条件下无可选接口</div>
                ) : (
                  visibleRequests.map((item) => {
                    const id = String(item.id);
                    const checked = selectedRequestIds.includes(id);
                    return (
                      <label key={id} style={requestRowStyle}>
                        <input type="checkbox" checked={checked} onChange={() => toggleRequestSelection(id)} />
                        <span style={requestMethodBadgeStyle}>{String(item.method || "GET").toUpperCase()}</span>
                        <span style={{ fontSize: ".8rem", fontWeight: 600 }}>{String(item.name || id)}</span>
                        <span style={{ fontSize: ".74rem", color: "var(--ink-soft)", marginLeft: "auto" }}>
                          {String(item.groupName || "default")}
                        </span>
                      </label>
                    );
                  })
                )}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20, borderTop: '1px solid var(--line)', paddingTop: 20 }}>
              <div>
                <label style={labelStyle}>负载配置 (Profile)</label>
                <div style={{ display: 'grid', gap: 12, marginTop: 10 }}>
                  <div style={inlineFormRow}><span style={subLabelStyle}>并发 VUs</span><input type="number" value={vus} onChange={e => setVus(Number(e.target.value))} className="search-box" style={compactInputStyle} /></div>
                  <div style={inlineFormRow}><span style={subLabelStyle}>持续时间 (s)</span><input type="number" value={duration} onChange={e => setDuration(Number(e.target.value))} className="search-box" style={compactInputStyle} /></div>
                  <div style={inlineFormRow}><span style={subLabelStyle}>爬坡时间 (s)</span><input type="number" value={rampUp} onChange={e => setRampUp(Number(e.target.value))} className="search-box" style={compactInputStyle} /></div>
                  <div style={inlineFormRow}><span style={subLabelStyle}>目标 TPS</span><input type="number" value={targetTps} onChange={e => setTargetTps(Number(e.target.value) || 0)} className="search-box" style={compactInputStyle} /></div>
                </div>
              </div>
              <div>
                <label style={labelStyle}>SLA 质量熔断</label>
                <div style={{ display: 'grid', gap: 12, marginTop: 10 }}>
                  <div style={inlineFormRow}><span style={subLabelStyle}>Max P95 (ms)</span><input type="number" value={slaP95} onChange={e => setSlaP95(Number(e.target.value))} className="search-box" style={compactInputStyle} /></div>
                  <div style={inlineFormRow}><span style={subLabelStyle}>Max Error (%)</span><input type="number" value={slaErr * 100} onChange={e => setSlaErr(Number(e.target.value) / 100)} className="search-box" style={compactInputStyle} /></div>
                  <div style={inlineFormRow}><span style={subLabelStyle}>超时 (ms)</span><input type="number" value={timeoutMs} onChange={e => setTimeoutMs(Number(e.target.value) || 15000)} className="search-box" style={compactInputStyle} /></div>
                  <label style={{ ...subLabelStyle, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <input type="checkbox" checked={verifySsl} onChange={(e) => setVerifySsl(e.target.checked)} />
                    校验证书 SSL
                  </label>
                </div>
              </div>
            </div>

            <div style={formGroupStyle}>
              <label style={labelStyle}>数据文件 URI (CSV，可选)</label>
              <input
                value={dataFileUri}
                onChange={(e) => setDataFileUri(e.target.value)}
                className="search-box"
                placeholder="例如: D:\\data\\users.csv 或 file:///D:/data/users.csv"
              />
            </div>
          </div>

          <button 
            onClick={handleRun} 
            disabled={isRunning || !selectedCollectionId}
            className="ui-btn ui-btn-primary ui-btn-block"
            style={{ 
              fontSize: '0.95rem', height: 46,
              opacity: (isRunning || !selectedCollectionId) ? 0.6 : 1
            }}
          >
            {isRunning ? <Loader2 size={20} className="animate-spin" /> : <Play size={20} fill="currentColor" />}
            <span>启动压测</span>
          </button>
          {isRunning && activeRunId ? (
            <button
              onClick={handleStopRun}
              className="ui-btn ui-btn-danger ui-btn-block"
              style={{
                fontSize: ".95rem",
                height: 42,
              }}
            >
              停止当前任务
            </button>
          ) : null}
          {capacity ? (
            <div style={{ fontSize: ".8rem", color: "var(--ink-soft)" }}>
              执行容量: 全局运行中 {capacity.running}/{capacity.maxConcurrentRuns}，全局排队 {capacity.queued}/{capacity.maxQueueSize}
              {(capacity.projectMaxConcurrentRuns || capacity.projectMaxQueueSize) ? (
                <>，项目并发上限 {capacity.projectMaxConcurrentRuns ?? "-"}，项目排队上限 {capacity.projectMaxQueueSize ?? "-"}</>
              ) : null}
            </div>
          ) : null}
          <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14, display: "grid", gap: 8 }}>
            <div style={{ fontSize: ".82rem", fontWeight: 700 }}>回归阈值策略</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
              <div style={inlineFormRow}>
                <span style={subLabelStyle}>P95 允许增量(ms)</span>
                <input
                  type="number"
                  value={regressionThresholds.maxP95DeltaMs}
                  onChange={(e) =>
                    setRegressionThresholds((prev) => ({
                      ...prev,
                      maxP95DeltaMs: Number(e.target.value) || 0,
                    }))
                  }
                  className="search-box"
                  style={compactInputStyle}
                />
              </div>
              <div style={inlineFormRow}>
                <span style={subLabelStyle}>错误率允许增量(%)</span>
                <input
                  type="number"
                  value={regressionThresholds.maxErrorRateDelta * 100}
                  onChange={(e) =>
                    setRegressionThresholds((prev) => ({
                      ...prev,
                      maxErrorRateDelta: (Number(e.target.value) || 0) / 100,
                    }))
                  }
                  className="search-box"
                  style={compactInputStyle}
                />
              </div>
            </div>
            <div style={inlineFormRow}>
              <span style={subLabelStyle}>TPS 最小允许变化</span>
              <input
                type="number"
                value={regressionThresholds.minTpsDelta}
                onChange={(e) =>
                  setRegressionThresholds((prev) => ({
                    ...prev,
                    minTpsDelta: Number(e.target.value) || 0,
                  }))
                }
                className="search-box"
                style={compactInputStyle}
              />
            </div>
            <button
              type="button"
              onClick={handleSaveRegressionThresholds}
              className="ui-btn ui-btn-muted ui-btn-block"
              style={{ height: 34, fontSize: ".78rem" }}
            >
              保存回归阈值
            </button>
          </div>
        </section>

        {/* 数据驱动中心 */}
        <section className="stat-card" style={{ padding: 24, border: '1px solid var(--line-strong)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
            <div style={{ background: '#6366f1', color: 'white', padding: 6, borderRadius: 8 }}><FileText size={16} /></div>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>数据中心 (Data Center)</h3>
          </div>

          {detectedColumns.length === 0 ? (
            <div style={{ padding: '20px', border: '2px dashed var(--line)', borderRadius: 12, textAlign: 'center' }}>
              <button 
                onClick={() => setDetectedColumns(['user_id', 'token', 'order_id', 'client_type'])}
                className="ui-btn ui-btn-muted"
                style={{ margin: '0 auto' }}
              >
                识别数据源变量
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 16 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {detectedColumns.map(c => <div key={c} className="badge" style={{ fontSize: '.7rem' }}>{"{{" + c + "}}"}</div>)}
              </div>
              
              <div style={{ padding: 16, background: 'var(--panel)', borderRadius: 12, border: '1px solid var(--line)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                  <div style={{ fontSize: '.8rem', fontWeight: 600 }}>智能映射预览 (Suggest)</div>
                  <Zap size={14} style={{ color: 'var(--primary)' }} />
                </div>
                <div style={{ display: 'grid', gap: 8 }}>
                  <div style={mappingRow}><span>username</span><ArrowRight size={12}/><span style={{color:'var(--primary)'}}>{"{{user_id}}"}</span></div>
                  <div style={mappingRow}><span>client_id</span><ArrowRight size={12}/><span style={{color:'var(--primary)'}}>{"{{client_type}}"}</span></div>
                </div>
                <button className="ui-btn ui-btn-primary ui-btn-block" style={{ marginTop: 12, height: 32, fontSize: '.75rem' }}>
                  同步到所有请求体
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="panel" style={{ padding: 20, display: "grid", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <div style={{ fontWeight: 700 }}>最近性能任务</div>
            <select
              value={runFilterStatus}
              onChange={(e) => setRunFilterStatus(e.target.value)}
              style={{ ...refinedSelectStyle, width: 160, height: 32, fontSize: ".78rem" }}
            >
              <option value="all">全部状态</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
              <option value="cancelled">cancelled</option>
              <option value="regressed">仅回归告警</option>
            </select>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              onClick={handleBatchDeleteRuns}
              disabled={selectedRunIds.length === 0}
              className={selectedRunIds.length === 0 ? "ui-btn ui-btn-muted" : "ui-btn ui-btn-danger"}
              style={{
                height: 30,
                fontSize: ".76rem",
              }}
            >
              批量删除 ({selectedRunIds.length})
            </button>
          </div>
          {filteredRuns.length === 0 ? (
            <div style={{ fontSize: ".82rem", color: "var(--ink-soft)" }}>暂无记录</div>
          ) : (
            <div style={{ display: "grid", gap: 8, maxHeight: 220, overflowY: "auto" }}>
              {filteredRuns.map((run) => (
                <div
                  key={run.id}
                  style={{
                    border: "1px solid var(--line)",
                    borderRadius: 10,
                    padding: "8px 10px",
                    display: "grid",
                    gap: 4,
                  }}
                >
                  <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: ".74rem", color: "var(--ink-soft)" }}>
                    <input
                      type="checkbox"
                      checked={selectedRunIds.includes(run.id)}
                      onChange={() => toggleRunSelection(run.id)}
                    />
                    选择
                  </label>
                  <div style={{ fontSize: ".78rem", color: "var(--ink-soft)" }}>{run.id}</div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: ".82rem" }}>
                    <span>{run.status}</span>
                    <span>{run.createdAt || "-"}</span>
                  </div>
                  {run.regression?.regressed ? (
                    <div style={{ fontSize: ".78rem", color: "#dc2626" }}>
                      回归告警: {(run.regression.alerts || []).join("；") || "指标下降"}
                    </div>
                  ) : null}
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      onClick={() => void handleExportRun(run.id, "json")}
                      className="ui-btn ui-btn-muted"
                      style={{ height: 28, fontSize: ".74rem" }}
                    >
                      导出 JSON
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleExportRun(run.id, "csv")}
                      className="ui-btn ui-btn-muted"
                      style={{ height: 28, fontSize: ".74rem" }}
                    >
                      导出 CSV
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel" style={{ padding: 20, display: "grid", gap: 10 }}>
          <div style={{ fontWeight: 700 }}>历史对比</div>
          {compareData?.latest ? (
            <div style={{ display: "grid", gap: 8, fontSize: ".82rem" }}>
              <div>Latest: {compareData.latest.runId}</div>
              <div>
                TPS {compareData.latest.tps.toFixed(2)} | P95 {compareData.latest.p95LatencyMs.toFixed(2)}ms | Error {(compareData.latest.errorRate * 100).toFixed(2)}%
              </div>
              {compareData.deltas ? (
                <div style={{ color: "var(--ink-soft)" }}>
                  ΔTPS {compareData.deltas.tpsDelta >= 0 ? "+" : ""}{compareData.deltas.tpsDelta.toFixed(2)} |
                  ΔP95 {compareData.deltas.p95DeltaMs >= 0 ? "+" : ""}{compareData.deltas.p95DeltaMs.toFixed(2)}ms |
                  ΔErr {(compareData.deltas.errorRateDelta * 100).toFixed(2)}%
                </div>
              ) : (
                <div style={{ color: "var(--ink-soft)" }}>暂无基线可对比（至少需要 2 次完成任务）</div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: ".82rem", color: "var(--ink-soft)" }}>暂无可对比历史</div>
          )}
        </section>
      </div>

      {/* 结果展示区 */}
      {(isRunning || runStatus || result) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          <section className="panel" style={{ padding: 20, display: 'grid', gap: 8 }}>
            <div style={{ fontSize: '.8rem', color: 'var(--ink-soft)' }}>Run Status</div>
            <div style={{ fontWeight: 700, fontSize: '1rem' }}>
              {runStatus || (isRunning ? "running" : "idle")}
            </div>
            {progress ? (
              <div style={{ fontSize: '.85rem', color: 'var(--ink-soft)' }}>
                已执行 {progress.totalRequests ?? 0} 次，成功 {progress.successCount ?? 0}，失败 {progress.failCount ?? 0}，
                当前 TPS {progress.tps ?? 0}
              </div>
            ) : null}
            {error ? <div style={{ color: '#dc2626', fontSize: '.85rem' }}>{error}</div> : null}
          </section>

          {result ? (
          <div className={result.passedSla ? "status-passed" : "status-failed"} style={{ padding: '16px 24px', borderRadius: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
            {result.passedSla ? <CheckCircle2 size={24} /> : <AlertCircle size={24} />}
            <div>
              <div style={{ opacity: 0.8, fontSize: '.8rem' }}>质量校验结状态</div>
              <div style={{ fontWeight: 700 }}>{result.passedSla ? "所有 SLA 指标达标" : result.errorMsg}</div>
            </div>
          </div>
          ) : null}

          {result ? (
          <div className="metrics-grid">
            <ModernMetricCard title="TPS (Throughput)" value={result.tps.toFixed(1)} sub="Req/sec" icon={<Activity size={20} />} trend="+12%" color="var(--primary)" />
            <ModernMetricCard title="Avg Latency" value={`${result.avgLatencyMs.toFixed(0)}ms`} sub="Average" icon={<Timer size={20} />} color="#f59e0b" />
            <ModernMetricCard title="P95 Latency" value={`${result.p95LatencyMs.toFixed(0)}ms`} sub="Tail (95th)" icon={<TrendingDown size={20} />} color="#ef4444" />
            <ModernMetricCard title="Success Rate" value={`${((result.successCount / result.totalRequests) * 100).toFixed(1)}%`} sub={`${result.successCount}/${result.totalRequests}`} icon={<CheckCircle2 size={20} />} color="#10b981" />
          </div>
          ) : null}

          {result ? (
          regressionInfo?.regressed ? (
          <div style={{ padding: "14px 16px", borderRadius: 12, border: "1px solid #fecaca", background: "#fff1f2", color: "#9f1239", fontSize: ".84rem" }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>性能回归告警</div>
            <div>{(regressionInfo?.alerts || []).join("；") || "检测到性能指标下降"}</div>
            {regressionInfo?.deltas ? (
              <div style={{ marginTop: 6, color: "#881337" }}>
                ΔTPS {regressionInfo.deltas.tpsDelta ?? 0} | ΔP95 {regressionInfo.deltas.p95DeltaMs ?? 0}ms | ΔErr {(((regressionInfo.deltas.errorRateDelta ?? 0) * 100)).toFixed(2)}%
              </div>
            ) : null}
          </div>
          ) : null
          ) : null}

          {result ? (
          <section className="panel" style={{ padding: 32, display: 'grid', gap: 24 }}>
            <div style={{ height: 300, position: 'relative' }}>
              <svg width="100%" height="100%" viewBox={`0 0 ${chartPaths.width} 120`} preserveAspectRatio="none">
                <path d={chartPaths.areaPath} fill="var(--primary-alpha-10)" />
                <path d={chartPaths.linePath} fill="none" stroke="var(--primary)" strokeWidth="3" />
              </svg>
            </div>
          </section>
          ) : null}
        </div>
      )}
    </div>
  );
}

function ModernMetricCard({ title, value, sub, icon, trend, color }: any) {
  return (
    <div className="metric-card metric-card-emphasis" style={{ borderTop: `4px solid ${color}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ background: `${color}15`, color, padding: 8, borderRadius: 10 }}>{icon}</div>
        {trend && <div style={{ fontSize: '.7rem', color: '#10b981' }}>{trend}</div>}
      </div>
      <div style={{ fontSize: '.8rem', color: 'var(--ink-soft)' }}>{title}</div>
      <div style={{ fontSize: '1.5rem', fontWeight: 800 }}>{value}</div>
      <div style={{ fontSize: '.7rem', color: 'var(--ink-soft)' }}>{sub}</div>
    </div>
  );
}

const mappingRow = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '.75rem', padding: '4px 0' };
const inlineFormRow = {
  display: "grid",
  gridTemplateColumns: "130px minmax(0, 1fr)",
  alignItems: "center",
  gap: 10,
};
const subLabelStyle = {
  fontSize: ".8rem",
  color: "var(--ink-soft)",
  whiteSpace: "nowrap" as const,
};
const compactInputStyle = { width: "100%", minWidth: 0, height: 32, textAlign: 'left' as const, fontSize: '.85rem' };
const formGroupStyle = { display: 'grid', gap: 8 };
const labelStyle = { fontSize: '.85rem', fontWeight: 600, color: 'var(--ink)' };
const refinedSelectStyle = { width: '100%', height: 40, background: 'white', borderRadius: 10, padding: '0 12px', border: '1px solid var(--line-strong)' };
const smallActionBtnStyle = { height: 30, fontSize: ".74rem" };
const requestRowStyle = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  border: "1px solid var(--line)",
  borderRadius: 8,
  padding: "6px 8px",
  background: "white",
};
const requestMethodBadgeStyle = {
  fontSize: ".68rem",
  fontWeight: 700,
  color: "var(--primary)",
  background: "var(--primary-alpha-10)",
  borderRadius: 999,
  padding: "2px 8px",
  minWidth: 46,
  textAlign: "center" as const,
};
