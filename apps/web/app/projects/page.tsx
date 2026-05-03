import { WorkspaceLayout } from "../../components/workspace-layout";
import { ProjectManager } from "../../components/project-manager";
import { searchProjects } from "../../lib/api";
import { dictionaries, getLang } from "../../lib/i18n";

export default async function ProjectsPage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;

  const projectsResult = await searchProjects({
    page: 1,
    pageSize: 20,
    sortBy: "updated_at",
    sortOrder: "desc",
  });

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
          <div
            style={{
              marginBottom: "24px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <h1
              style={{
                fontSize: "1.8rem",
                letterSpacing: "-0.03em",
                margin: 0,
                fontWeight: 700,
              }}
            >
              项目管理
            </h1>
          </div>
          <ProjectManager
            initialProjects={projectsResult.items}
            initialPage={projectsResult.page}
            initialPageSize={projectsResult.pageSize}
            initialTotal={projectsResult.total}
            initialHasNext={projectsResult.hasNext}
          />
        </div>
      </div>
    </WorkspaceLayout>
  );
}
