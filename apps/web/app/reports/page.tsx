import { WorkspaceLayout } from "../../components/workspace-layout";
import { ReportView } from "../../components/report-view";
import { dictionaries, getLang } from "../../lib/i18n";

export default async function ReportsPage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;

  return (
    <WorkspaceLayout dict={dict} navDict={navDict} lang={lang}>
       <ReportView />
    </WorkspaceLayout>
  );
}
