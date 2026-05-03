import { AppWindowMac, ArrowRight, FileSearch2, GalleryVerticalEnd, ShieldCheck } from "lucide-react";
import { readFile } from "fs/promises";
import Link from "next/link";
import { AppNav } from "../../../components/nav";
import { getReport } from "../../../lib/api";
import { parsePlatformApiErrorPayload } from "../../../lib/error-utils";
import { dictionaries, getLang } from "../../../lib/i18n";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function ReportPage({ params }: PageProps) {
  const lang = await getLang();
  const navDict = dictionaries[lang].nav;
  const { id } = await params;
  let report: Record<string, unknown> | null = null;
  let loadError = "";
  try {
    report = await getReport(id);
  } catch (error) {
    const parsed = parsePlatformApiErrorPayload(error);
    loadError = parsed?.message || (error instanceof Error ? error.message : "报告加载失败");
  }
  const run = (report?.run as Record<string, unknown> | undefined) ?? {};
  const artifacts = Array.isArray(report?.artifacts) ? report.artifacts : [];
  const runLogs: string[] = Array.isArray(run.logs) ? run.logs.map((item: unknown) => String(item)) : [];
  const runRunnerType = String(run.runnerType || "unknown").toUpperCase();
  const runRunnerTypeRaw = String(run.runnerType || "").toLowerCase();
  const runStatus = String(run.status || "queued");

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

  const summaryCards = [
    { label: "Run status", value: runStatus, icon: ShieldCheck },
    { label: "Runner", value: runRunnerType, icon: AppWindowMac },
    { label: "Artifacts", value: `${artifacts.length}`, icon: GalleryVerticalEnd },
    { label: "Report ID", value: id, icon: FileSearch2 },
  ];

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
              <div className="eyebrow eyebrow-dark">Report Analysis</div>
              <h1>运行摘要与证据回收</h1>
              <p>{String(run?.summary || "")}</p>
            </div>
            <div className="hero-side-card">
              <div className="kicker">Report status</div>
              <h2>Current signal</h2>
              <div className="chip-row">
                <span className={`status-${runStatus}`}>{runStatus}</span>
                <span className="badge">{runRunnerType}</span>
              </div>
            </div>
          </header>

          {loadError ? (
            <section className="panel" style={{ borderColor: "rgba(239,68,68,.35)", background: "rgba(254,242,242,.72)" }}>
              <div className="panel-head">
                <div>
                  <div className="kicker">Load fallback</div>
                  <h2>报告暂不可用（已降级展示）</h2>
                </div>
              </div>
              <div className="code" style={{ color: "#991b1b" }}>
                {loadError}
              </div>
            </section>
          ) : null}

          <section className="summary-grid">
            {summaryCards.map((card) => {
              const Icon = card.icon;

              return (
                <article key={card.label} className="summary-card summary-card-icon">
                  <span className="summary-icon">
                    <Icon size={18} strokeWidth={1.8} />
                  </span>
                  <span>{card.label}</span>
                  <strong>{card.value}</strong>
                </article>
              );
            })}
          </section>

          <section className="detail-grid">
            <article className="panel">
              <div className="panel-head">
                <div>
                  <div className="kicker">Assertion view</div>
                  <h2>Summary and observations</h2>
                </div>
                <ArrowRight size={16} strokeWidth={1.8} />
              </div>
              <div className="info-stack">
                <div className="info-tile">
                  <span>运行日志</span>
                  <strong>{runLogs.length} entries collected</strong>
                </div>
                <div className="info-tile">
                  <span>产物回收</span>
                  <strong>
                    {artifacts.length > 0 ? "已有证据沉淀" : "当前示例数据还没有实际产物"}
                  </strong>
                </div>
                <div className="info-tile">
                  <span>后续扩展</span>
                  <strong>可继续接 flakiness、失败聚类和回归趋势</strong>
                </div>
              </div>
            </article>

            <article className="panel panel-dark">
              <div className="panel-head">
                <div>
                  <div className="kicker kicker-invert">Run transcript</div>
                  <h2>Collected lines</h2>
                </div>
                <span className="signal-pill signal-pill-dark">evidence</span>
              </div>
              <div className="log-list">
                {runLogs.map((line, index) => (
                  <div key={`${line}-${index}`} className="log-row log-row-dark">
                    <span className="log-index">{`${index + 1}`.padStart(2, "0")}</span>
                    <div className="code code-invert">{line}</div>
                  </div>
                ))}
              </div>
            </article>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <div className="kicker">Artifacts</div>
                <h2>Recovered evidence</h2>
              </div>
              <span className="signal-pill signal-pill-quiet">trace / logs / screenshots</span>
            </div>
            <div className="artifact-grid">
              {artifacts.length > 0 ? (
                artifacts.map((artifact: Record<string, unknown>) => (
                  <article key={String(artifact.id || "")} className="artifact-card">
                    <span className="artifact-label">{String(artifact.label || "")}</span>
                    <strong>{String(artifact.id || "")}</strong>
                    <div className="code">{String(artifact.path || "")}</div>
                  </article>
                ))
              ) : (
                <article className="artifact-card artifact-card-empty">
                  <span className="artifact-label">Artifacts pending</span>
                  <strong>等待真实执行产物</strong>
                  <div className="code">
                    首批真实运行回传后，这里会展示 trace、截图、结构化报告和失败上下文。
                  </div>
                </article>
              )}
            </div>
          </section>

          {apiStepResults.length > 0 ? (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <div className="kicker">API step report</div>
                  <h2>结构化步骤结果</h2>
                </div>
                <span className="signal-pill signal-pill-quiet">assertions</span>
              </div>
              <div className="log-list">
                {apiStepResults.map((step, index) => {
                  const status = String(step.status || "unknown");
                  const assertions = Array.isArray(step.assertions) ? step.assertions : [];
                  return (
                    <article key={`${String(step.step || index)}-${String(step.name || "")}`} className="artifact-card">
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}

          {uiReport ? (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <div className="kicker">UI step report</div>
                  <h2>UI 结构化结果</h2>
                </div>
                <span className="signal-pill signal-pill-quiet">playwright</span>
              </div>
              <div className="info-stack">
                <div className="info-tile">
                  <span>当前页面</span>
                  <strong>{String(uiReport.currentUrl || uiReport.startUrl || "N/A")}</strong>
                </div>
                <div className="info-tile">
                  <span>执行摘要</span>
                  <strong>{String(uiReport.summary || run.summary || "N/A")}</strong>
                </div>
                <div className="info-tile">
                  <span>失败原因</span>
                  <strong>{String(uiReport.error || "无")}</strong>
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
                      <article key={`${index}-${String(step.name || "")}`} className="artifact-card">
                        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <strong>{String(step.name || step.type || `动作 ${index + 1}`)}</strong>
                          <span className={`status-${status === "passed" ? "passed" : "failed"}`}>{status}</span>
                          <span className="badge">{String(step.durationMs ?? 0)}ms</span>
                        </div>
                        {String(step.error || "").trim() ? (
                          <div className="code" style={{ color: "#b91c1c" }}>
                            ERROR: {String(step.error)}
                          </div>
                        ) : null}
                      </article>
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
        </div>
      </section>
    </main>
  );
}
