"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { 
  ShieldAlert, 
  ShieldCheck, 
  ShieldQuestion, 
  Search, 
  AlertTriangle, 
  Zap, 
  ChevronRight, 
  Download,
  Code2,
} from "lucide-react";
import type { Project } from "@ai-test-platform/shared-schema";
import { createCase, listApiCollections } from "../lib/api";
import { computeVirtualWindow } from "../lib/virtual-list";

type ScanType =
  | "owasp_api"
  | "pii_scan"
  | "auth_bypass"
  | "security_headers"
  | "cors_misconfig"
  | "xss_reflection"
  | "error_leak"
  | "insecure_transport"
  | "idor_enumeration"
  | "path_traversal"
  | "ssrf_probe"
  | "file_upload_security"
  | "command_template_injection"
  | "jwt_session_security"
  | "rate_limit_bruteforce";

type ScanPreset = "lite" | "standard" | "deep";
type ScanTargetMode = "project" | "url";

const SCAN_PRESETS: Record<ScanPreset, { label: string; scanTypes: ScanType[]; deepScan: boolean }> = {
  lite: {
    label: "轻量",
    scanTypes: ["auth_bypass", "security_headers", "insecure_transport"],
    deepScan: false,
  },
  standard: {
    label: "标准",
    scanTypes: ["owasp_api", "pii_scan", "auth_bypass", "security_headers", "cors_misconfig", "error_leak", "insecure_transport", "idor_enumeration", "path_traversal", "file_upload_security", "jwt_session_security", "rate_limit_bruteforce"],
    deepScan: true,
  },
  deep: {
    label: "深度",
    scanTypes: ["owasp_api", "pii_scan", "auth_bypass", "security_headers", "cors_misconfig", "xss_reflection", "error_leak", "insecure_transport", "idor_enumeration", "path_traversal", "ssrf_probe", "file_upload_security", "command_template_injection", "jwt_session_security", "rate_limit_bruteforce"],
    deepScan: true,
  },
};

interface Vulnerability {
  id: string;
  findingId?: string | null;
  type: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  endpoint: string;
  method: string;
  description: string;
  evidence: string | null;
  remediation: string | null;
}

interface SecurityScanResult {
  scanId: string;
  status: string;
  totalIssues: number;
  criticalCount: number;
  highCount: number;
  mediumCount: number;
  lowCount: number;
  vulnerabilities: Vulnerability[];
  startTime: string;
  endTime: string | null;
}

interface SecurityScanTask {
  taskId: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progressPct: number;
  processedRequests: number;
  totalRequests: number;
  result?: SecurityScanResult | null;
  error?: string | null;
}

interface SecurityScanHistoryItem {
  id: string;
  projectId: string;
  scanId: string;
  targetUrl?: string | null;
  targetMode?: "project" | "url";
  totalIssues: number;
  criticalCount: number;
  highCount: number;
  mediumCount: number;
  lowCount: number;
  requestCount: number;
  scanTypes: string[];
  deepScan: boolean;
  createdAt: string;
}

interface SecurityFindingItem {
  id: string;
  status: "open" | "fixed" | "retest";
}

export function SecurityTestView({ projects }: { projects: Project[] }) {
  const taskEventSourceRef = useRef<EventSource | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [scanTargetMode, setScanTargetMode] = useState<ScanTargetMode>("project");
  const [targetUrl, setTargetUrl] = useState("");
  const [collections, setCollections] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>([]);
  const [scanTypes, setScanTypes] = useState<ScanType[]>([
    "owasp_api",
    "pii_scan",
    "auth_bypass",
    "security_headers",
    "cors_misconfig",
    "xss_reflection",
    "error_leak",
    "insecure_transport",
    "idor_enumeration",
    "path_traversal",
    "ssrf_probe",
    "file_upload_security",
    "command_template_injection",
    "jwt_session_security",
    "rate_limit_bruteforce",
  ]);
  const [deepScan, setDeepScan] = useState(true);
  const [scanPreset, setScanPreset] = useState<ScanPreset>("deep");
  const [isScanning, setIsScanning] = useState(false);
  const [scanTask, setScanTask] = useState<SecurityScanTask | null>(null);
  const [result, setResult] = useState<SecurityScanResult | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<Vulnerability | null>(null);
  const [severityFilter, setSeverityFilter] = useState<"all" | Vulnerability["severity"]>("all");
  const [scanHistory, setScanHistory] = useState<SecurityScanHistoryItem[]>([]);
  const [findingStatusMap, setFindingStatusMap] = useState<Record<string, "open" | "fixed" | "retest">>({});
  const [isNotifying, setIsNotifying] = useState(false);
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const [vulnScrollTop, setVulnScrollTop] = useState(0);

  const closeTaskEventSource = () => {
    if (taskEventSourceRef.current) {
      taskEventSourceRef.current.close();
      taskEventSourceRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      closeTaskEventSource();
    };
  }, []);

  const latestDelta = useMemo(() => {
    if (scanHistory.length < 2) return null;
    const latest = scanHistory[0];
    const prev = scanHistory[1];
    return {
      total: latest.totalIssues - prev.totalIssues,
      critical: latest.criticalCount - prev.criticalCount,
      high: latest.highCount - prev.highCount,
      latestId: latest.scanId || latest.id,
      prevId: prev.scanId || prev.id,
    };
  }, [scanHistory]);

  useEffect(() => {
    if (projects.length > 0 && !selectedProjectId) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      setCollections([]);
      setSelectedCollectionIds([]);
      setScanHistory([]);
      setFindingStatusMap({});
      return;
    }
    void (async () => {
      try {
        const rows = await listApiCollections(selectedProjectId);
        const normalized = (Array.isArray(rows) ? rows : [])
          .map((item: any) => ({ id: String(item?.id || ""), name: String(item?.name || "") }))
          .filter((item) => item.id);
        setCollections(normalized);
        setSelectedCollectionIds(normalized.map((item) => item.id));
      } catch {
        setCollections([]);
        setSelectedCollectionIds([]);
      }
    })();
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) return;
    void refreshScanHistory(selectedProjectId);
    void refreshFindingStatuses(selectedProjectId);
  }, [selectedProjectId]);

  const filteredVulnerabilities = useMemo(() => {
    const rows = result?.vulnerabilities || [];
    if (severityFilter === "all") return rows;
    return rows.filter((item) => item.severity === severityFilter);
  }, [result?.vulnerabilities, severityFilter]);
  const vulnerabilityWindow = useMemo(
    () => computeVirtualWindow(filteredVulnerabilities.length, vulnScrollTop, 126, 620, 4),
    [filteredVulnerabilities.length, vulnScrollTop],
  );

  const exportJson = () => {
    if (!result) return;
    const blob = new Blob([JSON.stringify({ ...result, vulnerabilities: filteredVulnerabilities }, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `security-scan-${result.scanId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportCsv = () => {
    if (!result) return;
    const escapeCell = (value: unknown) => `"${String(value ?? "").replace(/"/g, "\"\"")}"`;
    const headers = ["id", "severity", "type", "method", "endpoint", "description", "evidence", "remediation"];
    const lines = [
      headers.join(","),
      ...filteredVulnerabilities.map((item) =>
        [
          item.id,
          item.severity,
          item.type,
          item.method,
          item.endpoint,
          item.description,
          item.evidence || "",
          item.remediation || "",
        ]
          .map(escapeCell)
          .join(","),
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `security-scan-${result.scanId}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const refreshScanHistory = async (projectId: string) => {
    try {
      const resp = await fetch(`/api/security/scans?projectId=${encodeURIComponent(projectId)}&limit=20`, {
        cache: "no-store",
      });
      if (!resp.ok) return;
      const data = await resp.json();
      setScanHistory(Array.isArray(data?.items) ? data.items : []);
    } catch {
      setScanHistory([]);
    }
  };

  const refreshFindingStatuses = async (projectId: string) => {
    try {
      const resp = await fetch(`/api/security/findings?projectId=${encodeURIComponent(projectId)}&limit=500`, {
        cache: "no-store",
      });
      if (!resp.ok) return;
      const data = await resp.json();
      const items = Array.isArray(data?.items) ? (data.items as SecurityFindingItem[]) : [];
      const next: Record<string, "open" | "fixed" | "retest"> = {};
      for (const item of items) {
        if (!item?.id) continue;
        if (item.status === "fixed" || item.status === "retest" || item.status === "open") {
          next[item.id] = item.status;
        }
      }
      setFindingStatusMap(next);
    } catch {
      setFindingStatusMap({});
    }
  };

  const handleStartScan = async () => {
    closeTaskEventSource();
    setIsScanning(true);
    setScanTask(null);
    setResult(null);
    setSelectedIssue(null);

    try {
      const resp = await fetch("/api/security/scan/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: selectedProjectId,
          collectionIds: scanTargetMode === "project" ? selectedCollectionIds : [],
          targetUrl: scanTargetMode === "url" ? targetUrl.trim() : null,
          maxDiscoveredUrls: 8,
          scanTypes,
          deepScan,
        })
      });

      if (!resp.ok) {
        throw new Error("安全审计任务启动失败");
      }

      const data = await resp.json();
      const taskId = String(data?.taskId || "");
      if (!taskId) {
        throw new Error("任务启动成功但未返回 taskId");
      }
      setScanTask({
        taskId,
        status: "queued",
        progressPct: 0,
        processedRequests: 0,
        totalRequests: Number(data?.totalRequests || 0),
      });
      const source = new EventSource(`/api/security/scan/tasks/${encodeURIComponent(taskId)}/events`);
      taskEventSourceRef.current = source;
      const onStatus = (event: MessageEvent<string>) => {
        let taskData: SecurityScanTask;
        try {
          taskData = JSON.parse(event.data) as SecurityScanTask;
        } catch {
          return;
        }
        setScanTask(taskData);
        const status = String(taskData?.status || "");
        if (status === "completed") {
          closeTaskEventSource();
          setResult(taskData?.result || null);
          setIsScanning(false);
          void refreshScanHistory(selectedProjectId);
          void refreshFindingStatuses(selectedProjectId);
          return;
        }
        if (status === "failed" || status === "cancelled") {
          closeTaskEventSource();
          setIsScanning(false);
          if (taskData?.error) {
            alert(String(taskData.error));
          }
          void refreshScanHistory(selectedProjectId);
        }
      };
      source.addEventListener("status", onStatus as EventListener);
      source.onerror = () => {
        closeTaskEventSource();
        setIsScanning(false);
        alert("扫描进度连接已中断，请刷新后重试。");
      };
    } catch (e: any) {
      console.error(e);
      alert(e.message || "安全审计失败，请检查 AI 服务状态");
      setIsScanning(false);
    }
  };

  const handleCancelScanTask = async () => {
    if (!scanTask?.taskId) return;
    try {
      const resp = await fetch(`/api/security/scan/tasks/${encodeURIComponent(scanTask.taskId)}/cancel`, {
        method: "POST",
      });
      if (!resp.ok) {
        throw new Error("取消扫描失败");
      }
      const data = await resp.json();
      setScanTask(data);
      closeTaskEventSource();
      setIsScanning(false);
    } catch (error: any) {
      alert(error?.message || "取消扫描失败");
    }
  };

  const updateFindingStatus = async (status: "open" | "fixed" | "retest") => {
    if (!selectedIssue?.findingId || !selectedProjectId) return;
    setIsUpdatingStatus(true);
    try {
      const resp = await fetch(`/api/security/findings/${selectedIssue.findingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || "更新漏洞状态失败");
      }
      await refreshFindingStatuses(selectedProjectId);
    } catch (error: any) {
      alert(error?.message || "更新漏洞状态失败");
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const applyScanPreset = (preset: ScanPreset) => {
    const config = SCAN_PRESETS[preset];
    setScanPreset(preset);
    setScanTypes(config.scanTypes);
    setDeepScan(config.deepScan);
  };

  const notifyFixToDev = async () => {
    if (!selectedIssue || !selectedProjectId || !result) return;
    setIsNotifying(true);
    try {
      const title = `[安全修复] ${selectedIssue.type} ${selectedIssue.method} ${selectedIssue.endpoint}`;
      await createCase({
        projectId: selectedProjectId,
        specId: "",
        kind: "api",
        title,
        objective: `修复 ${selectedIssue.severity.toUpperCase()} 风险：${selectedIssue.description}`,
        steps: [
          `定位接口：${selectedIssue.method} ${selectedIssue.endpoint}`,
          "复现漏洞并确认触发条件",
          "实施修复并补充防护逻辑",
          "回归验证并更新测试断言",
        ],
        assertionHints: [
          "漏洞复现用例应失败",
          "修复后接口应拒绝恶意输入/无权限请求",
          "响应中不应出现敏感信息明文",
        ],
        payload: {
          source: "security_scan",
          scanId: result.scanId,
          finding: selectedIssue,
        },
      });
      alert("已创建修复任务（测试用例）并通知开发处理。");
    } catch (error: any) {
      alert(error?.message || "创建修复任务失败");
    } finally {
      setIsNotifying(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* 扫控顶部配置 */}
      <section className="stat-card" style={{ padding: '24px 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'var(--panel-strong)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
          <div>
            <div className="kicker" style={{ color: '#ef4444' }}>Security Audit</div>
            <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 800 }}>AI 全自动安全渗透</h2>
          </div>
          <div style={{ height: 40, width: 2, background: 'var(--line)' }} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
            {['OWASP Top 10', 'PII 数据扫描', '越权探测', '安全响应头', 'CORS 策略', 'XSS 反射', '错误泄露', '传输安全', 'IDOR 枚举', '路径穿越', 'SSRF 探测', '文件上传安全', '命令/模板注入', 'JWT/会话安全', '防爆破与限流'].map(tag => (
              <div key={tag} className="badge" style={{ padding: '6px 12px' }}>{tag}</div>
            ))}
          </div>
        </div>

        <div style={{ display: 'grid', gap: 10, justifyItems: 'end' }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: ".84rem", color: "var(--ink-soft)", fontWeight: 600 }}>项目</span>
            <select
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              style={{ minWidth: 200, height: 38, borderRadius: 10, border: "1px solid var(--line-strong)", padding: "0 10px", background: "white" }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: ".84rem", color: "var(--ink-soft)", fontWeight: 600 }}>目标</span>
            <select
              value={scanTargetMode}
              onChange={(e) => setScanTargetMode(e.target.value as ScanTargetMode)}
              style={{ minWidth: 120, height: 38, borderRadius: 10, border: "1px solid var(--line-strong)", padding: "0 10px", background: "white" }}
            >
              <option value="project">项目集合</option>
              <option value="url">目标网址</option>
            </select>
          </div>
          {scanTargetMode === "url" ? (
            <div style={{ display: "grid", gap: 6, justifyItems: "end", maxWidth: 520 }}>
              <div style={{ fontSize: ".8rem", color: "var(--ink-soft)", fontWeight: 600 }}>目标网址</div>
              <input
                value={targetUrl}
                onChange={(e) => setTargetUrl(e.target.value)}
                placeholder="例如 https://example.com"
                style={{
                  width: 360,
                  maxWidth: "100%",
                  height: 38,
                  borderRadius: 10,
                  border: "1px solid var(--line-strong)",
                  padding: "0 10px",
                  background: "white",
                  fontSize: ".85rem",
                }}
              />
            </div>
          ) : null}
          {scanTargetMode === "project" ? (
            <div style={{ display: "grid", gap: 6, justifyItems: "end", maxWidth: 520 }}>
              <div style={{ fontSize: ".8rem", color: "var(--ink-soft)", fontWeight: 600 }}>扫描集合</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {collections.map((item) => {
                  const checked = selectedCollectionIds.includes(item.id);
                  return (
                    <label key={item.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: ".78rem", color: "var(--ink-soft)" }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setSelectedCollectionIds((prev) => {
                            if (e.target.checked) return prev.includes(item.id) ? prev : [...prev, item.id];
                            return prev.filter((x) => x !== item.id);
                          });
                        }}
                      />
                      {item.name}
                    </label>
                  );
                })}
              </div>
            </div>
          ) : null}
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <div style={{ display: "inline-flex", gap: 6, alignItems: "center", marginRight: 8 }}>
              <span style={{ fontSize: ".8rem", color: "var(--ink-soft)", fontWeight: 600 }}>策略</span>
              {(["lite", "standard", "deep"] as const).map((preset) => (
                <button
                  key={preset}
                  className="ui-btn ui-btn-muted"
                  style={{
                    height: 30,
                    padding: "0 10px",
                    borderColor: scanPreset === preset ? "var(--primary)" : undefined,
                    color: scanPreset === preset ? "var(--primary)" : undefined,
                  }}
                  onClick={() => applyScanPreset(preset)}
                >
                  {SCAN_PRESETS[preset].label}
                </button>
              ))}
            </div>
            {[
              { key: "owasp_api", label: "OWASP API" },
              { key: "pii_scan", label: "PII 扫描" },
              { key: "auth_bypass", label: "越权探测" },
              { key: "security_headers", label: "安全头" },
              { key: "cors_misconfig", label: "CORS 配置" },
              { key: "xss_reflection", label: "XSS 反射" },
              { key: "error_leak", label: "错误泄露" },
              { key: "insecure_transport", label: "传输安全" },
              { key: "idor_enumeration", label: "IDOR 枚举" },
              { key: "path_traversal", label: "路径穿越" },
              { key: "ssrf_probe", label: "SSRF 探测" },
              { key: "file_upload_security", label: "文件上传安全" },
              { key: "command_template_injection", label: "命令/模板注入" },
              { key: "jwt_session_security", label: "JWT/会话安全" },
              { key: "rate_limit_bruteforce", label: "防爆破与限流" },
            ].map((item) => (
              <label key={item.key} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: ".82rem", color: "var(--ink-soft)" }}>
                <input
                  type="checkbox"
                  checked={scanTypes.includes(item.key as ScanType)}
                  onChange={(e) => {
                    const key = item.key as ScanType;
                    setScanTypes((prev) => {
                      if (e.target.checked) {
                        return prev.includes(key) ? prev : [...prev, key];
                      }
                      const next = prev.filter((x) => x !== key);
                      return next;
                    });
                  }}
                />
                {item.label}
              </label>
            ))}
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: ".82rem", color: "var(--ink-soft)" }}>
              <input
                type="checkbox"
                checked={deepScan}
                onChange={(e) => setDeepScan(e.target.checked)}
              />
              深度扫描
            </label>
          </div>
          <div style={{ display: 'flex', gap: 16 }}>
          <button 
            onClick={handleStartScan}
            disabled={
              isScanning ||
              !selectedProjectId ||
              scanTypes.length === 0 ||
              (scanTargetMode === "project" ? selectedCollectionIds.length === 0 : !targetUrl.trim())
            }
            className="ui-btn ui-btn-danger"
            style={{ 
              padding: '0 24px', 
              height: 48, borderRadius: 14, fontSize: '1rem', fontWeight: 600,
              boxShadow: '0 4px 15px rgba(239, 68, 68, 0.3)',
              opacity: isScanning ? 0.6 : 1,
              transition: 'all 0.2s'
            }}
          >
            {isScanning ? <ShieldAlert size={20} className="animate-spin" /> : <ShieldAlert size={20} />}
            <span>{isScanning ? "深度资产扫描中..." : "开启全量安全测试"}</span>
          </button>
          {isScanning && scanTask ? (
            <button
              onClick={handleCancelScanTask}
              className="ui-btn ui-btn-muted"
              style={{ height: 48 }}
            >
              取消任务
            </button>
          ) : null}
          </div>
          {scanTask ? (
            <div style={{ width: 320, display: "grid", gap: 6, justifyItems: "end" }}>
              <div style={{ fontSize: ".78rem", color: "var(--ink-soft)" }}>
                任务 {scanTask.taskId} · {scanTask.status} · {scanTask.processedRequests}/{scanTask.totalRequests}
              </div>
              <div style={{ width: "100%", height: 8, borderRadius: 999, background: "var(--line)" }}>
                <div style={{ width: `${Math.max(0, Math.min(100, scanTask.progressPct || 0))}%`, height: "100%", borderRadius: 999, background: "linear-gradient(90deg,#ef4444,#f97316)" }} />
              </div>
            </div>
          ) : null}
        </div>
      </section>

      <section className="stat-card" style={{ padding: "16px 20px", display: "grid", gap: 10, background: "white" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 700, color: "var(--ink)" }}>最近扫描历史</div>
          <button className="ui-btn ui-btn-muted" style={{ height: 32, padding: "0 10px" }} onClick={() => void refreshScanHistory(selectedProjectId)} disabled={!selectedProjectId}>
            刷新
          </button>
        </div>
        {latestDelta ? (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <span className="badge" style={{ borderColor: "var(--line-strong)", background: "white" }}>
              对比 {latestDelta.prevId} → {latestDelta.latestId}
            </span>
            <span className="badge" style={{ borderColor: "var(--line-strong)", background: "white", color: latestDelta.total > 0 ? "#b91c1c" : latestDelta.total < 0 ? "#047857" : "var(--ink-soft)" }}>
              总问题 {latestDelta.total >= 0 ? `+${latestDelta.total}` : latestDelta.total}
            </span>
            <span className="badge" style={{ borderColor: "var(--line-strong)", background: "white", color: latestDelta.critical > 0 ? "#b91c1c" : latestDelta.critical < 0 ? "#047857" : "var(--ink-soft)" }}>
              Critical {latestDelta.critical >= 0 ? `+${latestDelta.critical}` : latestDelta.critical}
            </span>
            <span className="badge" style={{ borderColor: "var(--line-strong)", background: "white", color: latestDelta.high > 0 ? "#c2410c" : latestDelta.high < 0 ? "#047857" : "var(--ink-soft)" }}>
              High {latestDelta.high >= 0 ? `+${latestDelta.high}` : latestDelta.high}
            </span>
          </div>
        ) : null}
        {scanHistory.length === 0 ? (
          <div style={{ color: "var(--ink-soft)", fontSize: ".86rem" }}>暂无扫描记录</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {scanHistory.map((item) => (
              <div
                key={item.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
                  gap: 8,
                  alignItems: "center",
                  border: "1px solid var(--line)",
                  borderRadius: 10,
                  padding: "10px 12px",
                  background: "var(--panel)",
                }}
              >
                <div style={{ fontSize: ".82rem", color: "var(--ink-soft)" }}>
                  <div style={{ fontWeight: 700, color: "var(--ink)" }}>{item.scanId || item.id}</div>
                  <div>{item.createdAt}</div>
                  {item.targetMode === "url" && item.targetUrl ? (
                    <div style={{ marginTop: 2 }}>URL: {item.targetUrl}</div>
                  ) : null}
                </div>
                <div className="badge">{item.totalIssues} 问题</div>
                <div className="badge" style={{ background: "#fee2e2", borderColor: "#fecaca", color: "#b91c1c" }}>C:{item.criticalCount}</div>
                <div className="badge" style={{ background: "#ffedd5", borderColor: "#fed7aa", color: "#c2410c" }}>H:{item.highCount}</div>
                <div style={{ fontSize: ".78rem", color: "var(--ink-soft)" }}>请求数 {item.requestCount}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 结果主面板 */}
      {result ? (
        <div className="security-layout">
          {/* 左侧：风险列表 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 8px' }}>
              <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>风险发现项目 ({filteredVulnerabilities.length}/{result.vulnerabilities.length})</div>
              <div style={{ display: 'flex', gap: 8, alignItems: "center" }}>
                <select
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value as "all" | Vulnerability["severity"])}
                  style={{ height: 32, borderRadius: 8, border: "1px solid var(--line-strong)", padding: "0 8px", background: "white", fontSize: ".8rem" }}
                >
                  <option value="all">全部等级</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                  <option value="info">Info</option>
                </select>
                <button className="ui-btn ui-btn-muted" style={{ height: 32, padding: "0 10px" }} onClick={exportJson}>
                  <Download size={14} />
                  JSON
                </button>
                <button className="ui-btn ui-btn-muted" style={{ height: 32, padding: "0 10px" }} onClick={exportCsv}>
                  <Download size={14} />
                  CSV
                </button>
                <span className="badge" style={{ background: '#ef4444', color: 'white', border: 'none' }}>{result.criticalCount} Critical</span>
                <span className="badge" style={{ background: '#f97316', color: 'white', border: 'none' }}>{result.highCount} High</span>
              </div>
            </div>

            <div
              style={{ overflowY: "auto", maxHeight: 620 }}
              onScroll={(event) => setVulnScrollTop(event.currentTarget.scrollTop)}
            >
              <div style={{ height: vulnerabilityWindow.totalHeight, position: "relative" }}>
                <div style={{ transform: `translateY(${vulnerabilityWindow.offsetTop}px)` }}>
                  {filteredVulnerabilities.slice(vulnerabilityWindow.start, vulnerabilityWindow.end).map(v => (
                    <div key={v.id} style={{ height: 126, paddingBottom: 12, boxSizing: "border-box" }}>
                      <div
                        onClick={() => setSelectedIssue(v)}
                        style={{
                          padding: 20,
                          background: selectedIssue?.id === v.id ? 'var(--primary-alpha-5)' : 'white',
                          border: selectedIssue?.id === v.id ? '2px solid var(--primary)' : '1px solid var(--line-strong)',
                          borderRadius: 16,
                          cursor: 'pointer',
                          transition: 'all 0.1s linear'
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <SeverityBadge severity={v.severity} />
                            <span style={{ fontWeight: 700, fontSize: '1rem' }}>{v.type}</span>
                            {v.findingId ? (
                              <span className="badge" style={{ border: "1px solid var(--line-strong)", background: "white", color: "var(--ink-soft)" }}>
                                {findingStatusMap[v.findingId] || "open"}
                              </span>
                            ) : null}
                          </div>
                          <ChevronRight size={16} style={{ color: 'var(--ink-soft)' }} />
                        </div>
                        <div style={{ fontSize: '.85rem', color: 'var(--ink-soft)', marginBottom: 8, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          <code style={{ background: 'var(--panel)', padding: '2px 6px', borderRadius: 6, fontWeight: 600, color: 'var(--primary)' }}>{v.method}</code> {v.endpoint}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {filteredVulnerabilities.length === 0 ? (
                <div style={{ color: "var(--ink-soft)", padding: "12px 8px" }}>当前筛选条件下暂无风险项</div>
              ) : null}
            </div>
          </div>

          {/* 右侧：风险详情 & AI 修复建议 */}
          <div style={{ position: 'sticky', top: 24 }}>
            {selectedIssue ? (
              <div className="stat-card" style={{ padding: 32, border: '1px solid var(--line-strong)', background: 'white' }}>
                <div style={{ marginBottom: 24, paddingBottom: 24, borderBottom: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                    <AlertTriangle size={24} style={{ color: getSeverityColor(selectedIssue.severity) }} />
                    <h3 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 800 }}>详细漏洞评估</h3>
                  </div>
                  <p style={{ margin: 0, fontSize: '.9rem', color: 'var(--ink-soft)', lineHeight: 1.6 }}>{selectedIssue.description}</p>
                  {selectedIssue.findingId ? (
                    <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                      {(["open", "retest", "fixed"] as const).map((statusItem) => (
                        <button
                          key={statusItem}
                          className="ui-btn ui-btn-muted"
                          style={{ height: 32, padding: "0 10px" }}
                          disabled={isUpdatingStatus}
                          onClick={() => void updateFindingStatus(statusItem)}
                        >
                          标记 {statusItem}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div style={{ display: 'grid', gap: 24 }}>
                  <div style={infoGroup}>
                    <label style={infoLabel}><Code2 size={16} /> 探测路径</label>
                    <div style={infoValue}>{selectedIssue.endpoint}</div>
                  </div>

                  <div style={infoGroup}>
                    <label style={infoLabel}><Search size={16} /> 攻击存证 (Evidence)</label>
                    <pre style={codeBlock}>{selectedIssue.evidence}</pre>
                  </div>

                  <div style={{ padding: 20, background: '#f8fafc', borderRadius: 16, borderLeft: '4px solid #6366f1' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, color: '#6366f1', fontWeight: 700 }}>
                      <Zap size={18} fill="#6366f1" /> AI 专家加固建议
                    </div>
                    <p style={{ margin: 0, fontSize: '.88rem', color: '#1e293b', lineHeight: 1.6 }}>{selectedIssue.remediation}</p>
                    <button className="ui-btn ui-btn-primary ui-btn-block" style={{ marginTop: 16 }} onClick={notifyFixToDev} disabled={isNotifying}>
                      {isNotifying ? "创建修复任务中..." : "一键通知开发修复"}
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ height: 400, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-soft)', background: 'var(--panel)', borderRadius: 24, border: '2px dashed var(--line)' }}>
                <ShieldQuestion size={48} style={{ marginBottom: 16, opacity: 0.3 }} />
                <p>点击左侧风险项查看评估详情</p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div style={{ padding: '80px 0', textAlign: 'center' }}>
          {!isScanning && (
            <div style={{ maxWidth: 400, margin: '0 auto' }}>
              <div style={{ background: 'var(--panel)', padding: 32, borderRadius: 24, marginBottom: 24 }}>
                <ShieldCheck size={48} style={{ color: '#10b981', marginBottom: 16 }} />
                <h3>尚未发起全量审计</h3>
                <p style={{ color: 'var(--ink-soft)', fontSize: '.9rem' }}>对您的 API 进行 360 度无死角安全扫描，识别 SQL 注入、权限绕过与隐私泄露。</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = getSeverityColor(severity);
  return (
    <div style={{ 
      background: `${color}15`, color: color, 
      padding: '4px 10px', borderRadius: 8, fontSize: '.7rem', fontWeight: 800, textTransform: 'uppercase' 
    }}>
      {severity}
    </div>
  );
}

const getSeverityColor = (s: string) => {
  switch (s) {
    case 'critical': return '#ef4444';
    case 'high': return '#f97316';
    case 'medium': return '#f59e0b';
    case 'low': return '#3b82f6';
    default: return '#6b7280';
  }
};

const infoGroup = { display: 'grid', gap: 8 };
const infoLabel = { fontSize: '.8rem', fontWeight: 700, color: 'var(--ink-soft)', display: 'flex', alignItems: 'center', gap: 6 };
const infoValue = { padding: '12px 16px', background: 'var(--panel)', borderRadius: 10, fontSize: '.9rem', fontWeight: 600, color: 'var(--ink)' };
const codeBlock = { padding: 16, background: '#1e293b', color: '#f8fafc', borderRadius: 10, fontSize: '.85rem', margin: 0, overflowX: 'auto' as const };
