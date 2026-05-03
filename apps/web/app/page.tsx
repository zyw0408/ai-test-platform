import { WorkspaceLayout } from "../components/workspace-layout";
import { RequirementTable } from "../components/requirement-table";
import { PageHeader } from "../components/page-header";
import { listProjects, searchRequirements } from "../lib/api";
import { dictionaries, getLang } from "../lib/i18n";
import { ClipboardList } from "lucide-react";

export default async function HomePage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;

  const [projectsRaw, requirementsResult] = await Promise.all([
    listProjects(),
    searchRequirements({
      page: 1,
      pageSize: 20,
      sortBy: "updatedAt",
      sortOrder: "desc",
    }),
  ]);
  const projectRows = (projectsRaw as Array<{ id: string; name: string }>) ?? [];
  const defaultProjectId = projectRows[0]?.id;
  const projects = projectRows.map((item) => ({
    id: item.id,
    name: item.name,
  }));

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
            padding: "32px",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <PageHeader
            icon={<ClipboardList size={20} />}
            title={navDict.requirements}
            subtitle="集中管理需求条目、状态与分析历史。"
            tags={["需求池", "批量操作", "分析对比"]}
          />
          <RequirementTable
            dict={dict}
            initialData={requirementsResult.items}
            initialPage={requirementsResult.page}
            initialPageSize={requirementsResult.pageSize}
            initialTotal={requirementsResult.total}
            initialHasNext={requirementsResult.hasNext}
            defaultProjectId={defaultProjectId ?? ""}
            projects={projects}
          />
        </div>
      </div>
    </WorkspaceLayout>
  );
}
