import { WorkspaceLayout } from "../../components/workspace-layout";
import { TestCaseTable } from "../../components/testcase-table";
import { PageHeader } from "../../components/page-header";
import { dictionaries, getLang } from "../../lib/i18n";
import { listProjects, listSpecs, searchCases } from "../../lib/api";
import { FileCheck2 } from "lucide-react";

export default async function CasesPage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;
  const [projects, initialCaseResult] = await Promise.all([
    listProjects(),
    searchCases({ page: 1, pageSize: 20, sortBy: "updatedAt", sortOrder: "desc" }),
  ]);
  const initialSpecProjectIds = Array.from(
    new Set(initialCaseResult.items.map((item) => item.projectId).filter(Boolean)),
  );
  const initialSpecs = (
    await Promise.all(initialSpecProjectIds.map((projectId) => listSpecs(projectId)))
  ).flat();

  return (
    <WorkspaceLayout dict={dict} navDict={navDict} lang={lang}>
      <div
        style={{
          padding: "32px",
          display: "flex",
          flexDirection: "column",
          flex: 1,
          minHeight: 0,
          boxSizing: "border-box",
        }}
      >
        <div
          className="glassboard"
          style={{
            flex: 1,
            padding: "24px",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            gap: 14,
          }}
        >
          <PageHeader
            icon={<FileCheck2 size={20} />}
            title="测试用例库"
            subtitle="维护 API/UI 用例，统一执行、状态回写与回收管理。"
            tags={["执行趋势", "批量执行", "回收站"]}
            style={{ marginBottom: 2 }}
          />

          <TestCaseTable
            dict={dict}
            initialCases={initialCaseResult.items}
            initialPage={initialCaseResult.page}
            initialPageSize={initialCaseResult.pageSize}
            initialTotal={initialCaseResult.total}
            initialHasNext={initialCaseResult.hasNext}
            projects={projects}
            specs={initialSpecs}
          />
        </div>
      </div>
    </WorkspaceLayout>
  );
}
