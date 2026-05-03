import { ShieldCheck } from "lucide-react";
import { WorkspaceLayout } from "../../components/workspace-layout";
import { dictionaries, getLang } from "../../lib/i18n";
import { SecurityTestView } from "../../components/security-test-view";
import { PageHeader } from "../../components/page-header";
import { listProjects } from "../../lib/api";

export default async function SecurityPage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;

  // 获取项目数据 (用于选择压测目标)
  const projects = await listProjects().catch(() => []);

  return (
    <WorkspaceLayout dict={dict} navDict={navDict} lang={lang}>
      <div style={{ padding: "32px", height: "100%", width: '100%', boxSizing: "border-box", overflowY: 'auto' }}>
        <PageHeader
          icon={<ShieldCheck size={20} />}
          title="AI 安全审计工作台"
          subtitle="聚焦高危漏洞发现、证据追踪与修复闭环。"
          tags={["全量审计", "漏洞分级", "修复建议"]}
          style={{ marginBottom: 24 }}
        />
        
        <SecurityTestView projects={projects} />
      </div>
    </WorkspaceLayout>
  );
}
