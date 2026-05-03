import { GaugeCircle } from "lucide-react";
import { WorkspaceLayout } from "../../components/workspace-layout";
import { dictionaries, getLang } from "../../lib/i18n";
import { PerformanceTestView } from "../../components/performance-test-view";
import { PageHeader } from "../../components/page-header";
import { listProjects } from "../../lib/api";

export default async function PerformancePage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;

  // 获取项目数据 (用于选择压测目标)
  const projects = await listProjects().catch(() => []);

  return (
    <WorkspaceLayout dict={dict} navDict={navDict} lang={lang}>
      <div style={{ padding: "32px", height: "100%", width: '100%', boxSizing: "border-box", overflowY: 'auto' }}>
        <PageHeader
          icon={<GaugeCircle size={20} />}
          title="现代化性能测试中心"
          subtitle="配置压测策略、实时跟踪结果并完成历史回归对比。"
          tags={["实时吞吐", "SLA 校验", "回归阈值"]}
          style={{ marginBottom: 24 }}
        />
        
        <PerformanceTestView projects={projects} />
      </div>
    </WorkspaceLayout>
  );
}
