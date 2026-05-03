import { Settings } from "lucide-react";
import { WorkspaceLayout } from "../../components/workspace-layout";
import { dictionaries, getLang } from "../../lib/i18n";
import { SettingsView } from "../../components/settings-view";

export default async function SettingsPage() {
  const lang = await getLang();
  const dict = dictionaries[lang].home;
  const navDict = dictionaries[lang].nav;

  return (
    <WorkspaceLayout dict={dict} navDict={navDict} lang={lang}>
      <SettingsView />
    </WorkspaceLayout>
  );
}
