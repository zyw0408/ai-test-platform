import { WorkspaceLayout } from "../../components/workspace-layout";
import { AutoTestWorkbench } from "../../components/auto-test-workbench";
import { PageHeader } from "../../components/page-header";
import { dictionaries, getLang } from "../../lib/i18n";
import { listProjects, listRuns, searchCases } from "../../lib/api";
import { TerminalSquare } from "lucide-react";

type SearchParams = Promise<{ mode?: string }>;

export default async function AutoTestsPage({ searchParams }: { searchParams?: SearchParams }) {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;
  const resolvedSearch = searchParams ? await searchParams : {};
  const initialMode =
    resolvedSearch?.mode === "api-automation" || resolvedSearch?.mode === "ui-locator"
      ? resolvedSearch.mode
      : "ui-automation";

  const [projects, uiCasePage, recentRuns] = await Promise.all([
    listProjects(),
    searchCases({ kind: "ui", page: 1, pageSize: 20, sortBy: "updatedAt", sortOrder: "desc" }),
    listRuns({ limit: 40 }),
  ]);
  const initialRuns = recentRuns.slice(0, 40);

  return (
    <WorkspaceLayout dict={dict} navDict={navDict} lang={lang}>
      <div style={{ padding: "32px", display: "flex", flexDirection: "column", flex: 1, minHeight: 0, boxSizing: "border-box" }}>
        <PageHeader
          icon={<TerminalSquare size={20} />}
          title="自动化测试工作台"
          subtitle="覆盖 UI/API 自动化执行、定位分析与运行流水线追踪。"
          tags={["UI 自动化", "API 自动化", "运行流水线"]}
        />
        <div style={{ flex: 1, minHeight: 0 }}>
          <AutoTestWorkbench
            initialCases={uiCasePage.items}
            initialRuns={initialRuns}
            projects={projects}
            initialMode={initialMode}
          />
        </div>
      </div>
    </WorkspaceLayout>
  );
}
