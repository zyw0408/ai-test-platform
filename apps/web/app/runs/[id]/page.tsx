import { readFile } from "fs/promises";
import Link from "next/link";
import { Activity, ArrowRight, Clock3, FileCode2, Orbit } from "lucide-react";
import type { CSSProperties } from "react";
import { AppNav } from "../../../components/nav";
import { getReport } from "../../../lib/api";
import { parsePlatformApiErrorPayload } from "../../../lib/error-utils";
import { dictionaries, getLang } from "../../../lib/i18n";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function RunDetailPage({ params }: PageProps) {
  const lang = await getLang();
  const navDict = dictionaries[lang].nav;
  const { id } = await params;
  let report: Record<string, unknown> | null = null;
  let loadError = "";
  try {
    report = await getReport(id);
  } catch (error) {
    const parsed = parsePlatformApiErrorPayload(error);
    loadError = parsed?.message || (error instanceof Error ? error.message : "运行报告加载失败");
  }
  const run = (report?.run as Record<string, unknown> | undefined) ?? {};
  const testCase = (report?.case as Record<string, unknown> | null | undefined) ?? null;
  const artifacts = Array.isArray(report?.artifacts) ? report.artifacts : [];
  const runLogs: string[] = Array.isArray(run.logs) ? run.logs.map((item: unknown) => String(item)) : [];
  const runArtifactIds: string[] = Array.isArray(run.artifactIds)
    ? run.artifactIds.map((item: unknown) => String(item))
    : [];
  const runRunnerType = String(run.runnerType || "unknown").toUpperCase();
  const runRunnerTypeRaw = String(run.runnerType || "").toLowerCase();
  const runStatus = String(run.status || "queued");
  const runSummary = String(run.summary || "");
  const testCaseTitle = String(testCase?.title || "未知用例");
  const assertionHints: string[] = Array.isArray(testCase?.assertionHints)
    ? (testCase.assertionHints as unknown[]).map((item: unknown) => String(item)).filter(Boolean)
    : [];

  let apiStepResults: Array<Record<string, unknown>> = [];
  let uiReport: Record<string, unknown> | null = null;
  let uiActionResults: Array<Record<string, unknown>> = [];
  let uiConsoleErrors: Array<Record<string, unknown>> = [];
  let uiFailedRequests: Array<Record<string, unknown>> = [];
  try {
    const candidate = artifacts.find(
      (item: Record<string, unknown>) =>
        String(item?.type || "").toLowerCase() === "json" &&
        String(item?.path || "").toLowerCase().includes("-api-report.json"),
    );
    if (candidate?.path) {
      const raw = await readFile(String(candidate.path), "utf-8");
      const parsed = JSON.parse(raw) as { steps?: Array<Record<string, unknown>> };
      if (Array.isArray(parsed.steps)) {
        apiStepResults = parsed.steps;
      }
    }
  } catch {
    apiStepResults = [];
  }
  try {
    const jsonArtifacts = artifacts.filter(
      (item: Record<string, unknown>) => String(item?.type || "").toLowerCase() === "json",
    );
    for (const item of jsonArtifacts) {
      const raw = await readFile(String(item.path), "utf-8");
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      if (
        String(parsed?.runner || "").toLowerCase() === "ui" ||
        typeof parsed?.currentUrl === "string" ||
        String(item?.path || "").toLowerCase().includes("-ui-runner-error.json")
      ) {
        uiReport = parsed;
        if (Array.isArray(parsed.actionResults)) {
          uiActionResults = parsed.actionResults as Array<Record<string, unknown>>;
        }
        if (Array.isArray(parsed.consoleErrors)) {
          uiConsoleErrors = parsed.consoleErrors as Array<Record<string, unknown>>;
        }
        if (Array.isArray(parsed.failedRequests)) {
          uiFailedRequests = parsed.failedRequests as Array<Record<string, unknown>>;
        }
        break;
      }
    }
  } catch {
    uiReport = null;
  }

  const metaItems = [
    { label: "任务 ID", value: String(run.id || ""), icon: FileCode2 },
    { label: "Runner", value: runRunnerType, icon: Orbit },
    { label: "开始时间", value: String(run.startedAt || "未开始"), icon: Clock3 },
    { label: "结束时间", value: String(run.finishedAt || "执行中"), icon: Activity },
  ];
  const infoTilePairStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "110px minmax(0, 1fr)",
    columnGap: 12,
    alignItems: "start",
  };
  const infoLabelStyle: CSSProperties = {
    color: "#6b7280",
    fontWeight: 600,
    lineHeight: 1.5,
    whiteSpace: "nowrap",
  };
  const infoValueStyle: CSSProperties = {
    lineHeight: 1.5,
    overflowWrap: "anywhere",
    wordBreak: "break-word",
  };

  return (
    <main className="shell">
      <AppNav dict={navDict} lang={lang} />

      <section className="dashboard-stage">
        <div className="glassboard page-stack">
          <div style={{ display: "flex", justifyContent: "flex-start" }}>
            <Link
              href={`/auto-tests?mode=${runRunnerTypeRaw === "ui" ? "ui-automation" : "api-automation"}`}
              className="signal-pill signal-pill-quiet"
              style={{ textDecoration: "none" }}
            >
              ← 返回自动化测试
            </Link>
          </div>
          <header className="page-hero">
              <div>
                <div className="eyebrow eyebrow-dark">Run Detail</div>
              <h1>{testCaseTitle}</h1>
              <p>{runSummary}</p>
              </div>
            <div className="hero-side-card">
              <div className="kicker">Execution state</div>
              <h2>Runner heartbeat</h2>
              <div className="chip-row">
                <span className={`status-${runStatus}`}>{runStatus}</span>
                <span className="badge">{runRunnerType} runner</span>
              </div>
            </div>
          </header>

          {loadError ? (
            <section className="panel" style={{ borderColor: "rgba(239,68,68,.35)", background: "rgba(254,242,242,.72)" }}>
              <div className="panel-head">
                <div>
                  <div className="kicker">Load fallback</div>
                  <h2>运行报告暂不可用（已降级展示）</h2>
                </div>
              </div>
              <div className="code" style={{ color: "#991b1b" }}>
                {loadError}
              </div>
            </section>
          ) : null}

          <section className="summary-grid">
            {metaItems.map((item) => {
              const Icon = item.icon;

              return (
                <article key={item.label} className="summary-card summary-card-icon">
                  <span className="summary-icon">
                    <Icon size={18} strokeWidth={1.8} />
                  </span>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </article>
              );
            })}
          </section>

          <section className="detail-grid">
            <article className="panel">
              <div className="panel-head">
                <div>
                  <div className="kicker">Execution overview</div>
                  <h2>What is happening now</h2>
                </div>
                <ArrowRight size={16} strokeWidth={1.8} />
              </div>
              <div className="info-stack">
                <div className="info-tile" style={infoTilePairStyle}>
                  <span style={infoLabelStyle}>关联用例：</span>
                  <strong style={infoValueStyle}>{testCaseTitle || "未命名用例"}</strong>
                </div>
                <div className="info-tile" style={infoTilePairStyle}>
                  <span style={infoLabelStyle}>断言提示：</span>
                  <strong style={infoValueStyle}>
                    {assertionHints.length > 0 ? assertionHints.join("；") : "等待补充断言"}
                  </strong>
                </div>
                <div className="info-tile" style={infoTilePairStyle}>
                  <span style={infoLabelStyle}>产物数量：</span>
                  <strong style={infoValueStyle}>{runArtifactIds.length}</strong>
                </div>
              </div>
            </article>

            <article className="panel panel-dark">
              <div className="panel-head">
                <div>
                  <div className="kicker kicker-invert">Payload preview</div>
                  <h2>Scenario payload</h2>
                </div>
                <span className="signal-pill signal-pill-dark">structured</span>
              </div>
              <pre className="code code-block">{JSON.stringify(testCase?.payload ?? {}, null, 2)}</pre>
            </article>
          </section>

          {apiStepResults.length > 0 ? (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <div className="kicker">Step results</div>
                  <h2>API 执行结果明细</h2>
                </div>
                <span className="signal-pill signal-pill-quiet">structured</span>
              </div>
              <div className="log-list">
                {apiStepResults.map((step, index) => {
                  const status = String(step.status || "unknown");
                  const assertions = Array.isArray(step.assertions) ? step.assertions : [];
                  return (
                    <div key={`${String(step.step || index)}-${String(step.name || "")}`} className="log-row" style={{ alignItems: "flex-start", flexDirection: "column", gap: 8 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", width: "100%" }}>
                        <span className="log-index">{`${index + 1}`.padStart(2, "0")}</span>
                        <strong>{String(step.name || `步骤 ${index + 1}`)}</strong>
                        <span className={`status-${status === "passed" ? "passed" : "failed"}`}>{status}</span>
                        <span className="badge">HTTP {String(step.statusCode ?? "N/A")}</span>
                        <span className="badge">{String(step.durationMs ?? 0)}ms</span>
                      </div>
                      {String(step.errorMessage || "").trim() ? (
                        <div className="code" style={{ color: "#b91c1c" }}>
                          ERROR: {String(step.errorMessage)}
                        </div>
                      ) : null}
                      {assertions.length > 0 ? (
                        <div className="code" style={{ whiteSpace: "pre-wrap" }}>
                          {assertions
                            .map((item: Record<string, unknown>) => `${item.passed ? "PASS" : "FAIL"} | ${String(item.name || item.type || "")} | ${String(item.message || "")}`)
                            .join("\n")}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          {uiReport ? (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <div className="kicker">Step results</div>
                  <h2>UI 执行结果明细</h2>
                </div>
                <span className="signal-pill signal-pill-quiet">playwright</span>
              </div>
              <div className="info-stack">
                <div className="info-tile" style={infoTilePairStyle}>
                  <span style={infoLabelStyle}>当前页面：</span>
                  <strong style={infoValueStyle}>{String(uiReport.currentUrl || uiReport.startUrl || "N/A")}</strong>
                </div>
                <div className="info-tile" style={infoTilePairStyle}>
                  <span style={infoLabelStyle}>执行摘要：</span>
                  <strong style={infoValueStyle}>{String(uiReport.summary || runSummary || "N/A")}</strong>
                </div>
                <div className="info-tile" style={infoTilePairStyle}>
                  <span style={infoLabelStyle}>失败原因：</span>
                  <strong style={infoValueStyle}>{String(uiReport.error || "无")}</strong>
                </div>
              </div>
              {Array.isArray(uiReport.logs) && uiReport.logs.length > 0 ? (
                <div className="log-list" style={{ marginTop: 12 }}>
                  {uiReport.logs.map((line, index) => (
                    <div key={`${String(line)}-${index}`} className="log-row">
                      <span className="log-index">{`${index + 1}`.padStart(2, "0")}</span>
                      <div className="code">{String(line)}</div>
                    </div>
                  ))}
                </div>
              ) : null}
              {uiActionResults.length > 0 ? (
                <div className="log-list" style={{ marginTop: 12 }}>
                  {uiActionResults.map((step, index) => {
                    const status = String(step.status || "unknown");
                    return (
                      <div key={`${index}-${String(step.name || "")}`} className="log-row" style={{ alignItems: "flex-start", flexDirection: "column", gap: 8 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", width: "100%" }}>
                          <span className="log-index">{`${index + 1}`.padStart(2, "0")}</span>
                          <strong>{String(step.name || step.type || `动作 ${index + 1}`)}</strong>
                          <span className={`status-${status === "passed" ? "passed" : "failed"}`}>{status}</span>
                          <span className="badge">{String(step.durationMs ?? 0)}ms</span>
                        </div>
                        {String(step.error || "").trim() ? (
                          <div className="code" style={{ color: "#b91c1c" }}>
                            ERROR: {String(step.error)}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {uiConsoleErrors.length > 0 ? (
                <div className="code" style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
                  {uiConsoleErrors
                    .slice(0, 20)
                    .map((item) => `CONSOLE ${String(item.type || "error")} | ${String(item.text || "")}`)
                    .join("\n")}
                </div>
              ) : null}
              {uiFailedRequests.length > 0 ? (
                <div className="code" style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
                  {uiFailedRequests
                    .slice(0, 20)
                    .map(
                      (item) =>
                        `REQUEST ${String(item.method || "GET")} ${String(item.status || "")} ${String(item.url || "")}`,
                    )
                    .join("\n")}
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="panel">
            <div className="panel-head">
              <div>
                <div className="kicker">Runner output</div>
                <h2>Execution logs</h2>
              </div>
              <span className="signal-pill signal-pill-quiet">live feed</span>
            </div>
            <div className="log-list">
              {runLogs.map((line, index) => (
                <div key={`${line}-${index}`} className="log-row">
                  <span className="log-index">{`${index + 1}`.padStart(2, "0")}</span>
                  <div className="code">{line}</div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
