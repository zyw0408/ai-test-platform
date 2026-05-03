import { WorkspaceLayout } from "../../components/workspace-layout";
import { ApiTestView } from "../../components/api-test-view";
import { PageHeader } from "../../components/page-header";
import {
  listApiCollectionEnvironments,
  listApiCollectionRequests,
  listApiCollections,
  listProjects,
} from "../../lib/api";
import { dictionaries, getLang } from "../../lib/i18n";
import { Network } from "lucide-react";

export default async function ApiTestsPage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;
  const initialProjects = await listProjects();
  const initialProjectId = initialProjects[0]?.id ?? "";
  const initialCollections = initialProjectId
    ? await listApiCollections(initialProjectId)
    : [];
  const initialCollectionId = initialCollections[0]?.id ?? "";
  const [initialRequests, initialEnvironments] = initialCollectionId
    ? await Promise.all([
        listApiCollectionRequests(initialCollectionId),
        listApiCollectionEnvironments(initialCollectionId),
      ])
    : [[], []];
  const initialRequestId = initialRequests[0]?.id ?? "";
  const initialEnvironmentId =
    initialEnvironments.find((item) => item.isDefault)?.id ??
    initialEnvironments[0]?.id ??
    "";

  return (
    <WorkspaceLayout dict={dict} navDict={navDict} lang={lang}>
      <div style={{ padding: "32px", display: "flex", flexDirection: "column", flex: 1, minHeight: 0, boxSizing: "border-box" }}>
        <PageHeader
          icon={<Network size={20} />}
          title="API 测试工作台"
          subtitle="统一管理接口集合、请求编排、变量环境与批量执行。"
          tags={["接口集合", "环境变量", "批量回放"]}
        />
        <div style={{ flex: 1, minHeight: 0 }}>
          <ApiTestView
            initialProjects={initialProjects}
            initialProjectId={initialProjectId}
            initialCollections={initialCollections}
            initialCollectionId={initialCollectionId}
            initialRequests={initialRequests}
            initialRequestId={initialRequestId}
            initialEnvironments={initialEnvironments}
            initialEnvironmentId={initialEnvironmentId}
          />
        </div>
      </div>
    </WorkspaceLayout>
  );
}
