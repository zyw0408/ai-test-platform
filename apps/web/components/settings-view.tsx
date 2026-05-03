"use client";

import { useState, useEffect, Suspense, type ChangeEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Settings, BrainCircuit, Users, Save, Plus, Trash2, CheckCircle2,
  Loader2, User as UserIcon, Building2, ShieldCheck, Mail, Phone, Clock, FileText, Lock, Search, Download, Upload
} from "lucide-react";
import { PageHeader } from "./page-header";
import { fetchJsonWithClientCache, invalidateClientRequestCache } from "../lib/client-request-cache";

interface UserProfile {
  id: string;
  username: string;
  nickname: string;
  name: string;
  avatarUrl: string;
  role: string;
  createdAt: string;
}

interface McpConfig {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  builtIn?: boolean;
  source?: string;
  tools?: string[];
}

interface UserAISettings {
  modelBaseUrl: string;
  modelApiKey: string;
  modelName: string;
  maxTokens: number;
  temperature: number;
  systemPrompt?: string;
  mcpServers: McpConfig[];
  customRules: string[];
  customRulesText?: string;
  skillSearchPaths: string[];
}

interface TeamInfo {
  id: string;
  orgId: string;
  name: string;
  createdAt: string;
  memberCount: number;
}

interface TeamMember {
  id: string;
  userId: string;
  username: string;
  name: string;
  role: string;
  createdAt: string;
}

interface TeamAuditLog {
  id: string;
  actorId?: string | null;
  action: string;
  targetType: string;
  targetId: string;
  payload?: Record<string, unknown> | null;
  createdAt: string;
}

interface McpSearchItem {
  name: string;
  qualifiedName: string;
  description: string;
  useCount?: number;
  connectionUrl?: string;
  packageName?: string;
  presetTools?: string[];
}

interface ParsedRule {
  raw: string;
  priority: string;
  scope: string;
  content: string;
}

interface McpInstallVerification {
  ok: boolean;
  toolCount: number;
  message: string;
}

const MCP_CATALOG: McpSearchItem[] = [
  { name: "Filesystem", qualifiedName: "filesystem", packageName: "@modelcontextprotocol/server-filesystem", description: "本地文件读写能力", presetTools: ["read_file", "write_file", "list_directory"] },
  { name: "Fetch", qualifiedName: "fetch", packageName: "@modelcontextprotocol/server-fetch", description: "网页抓取与文档获取能力", presetTools: ["fetch"] },
  { name: "Playwright", qualifiedName: "playwright", packageName: "@playwright/mcp", description: "浏览器自动化能力", presetTools: ["browser_navigate", "browser_click", "browser_snapshot"] },
  { name: "GitHub", qualifiedName: "github", packageName: "github-mcp-server", description: "仓库、Issue、PR 协作能力", presetTools: ["list_repos", "create_issue", "list_prs"] },
  { name: "Notion", qualifiedName: "notion", packageName: "@notionhq/notion-mcp-server", description: "知识库与文档协作能力", presetTools: ["search_pages", "read_page", "create_page"] },
  { name: "Jira", qualifiedName: "jira", packageName: "jira-mcp", description: "项目任务与工单管理能力", presetTools: ["search_issues", "create_issue", "transition_issue"] },
];

const defaultToolsForServer = (serverName: string): string[] => {
  const key = String(serverName || "").trim().toLowerCase();
  const fromCatalog = MCP_CATALOG.find((item) => item.qualifiedName.toLowerCase() === key)?.presetTools;
  if (fromCatalog && fromCatalog.length > 0) return fromCatalog;
  if (key === "filesystem") return ["read_file", "write_file", "list_directory"];
  if (key === "fetch") return ["fetch"];
  if (key === "playwright") return ["browser_navigate", "browser_click", "browser_snapshot"];
  return [];
};

export function SettingsView() {
  return (
    <Suspense fallback={<div className="p-8"><Loader2 className="animate-spin" /></div>}>
      <SettingsContent />
    </Suspense>
  );
}

function SettingsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab") as 'personal' | 'ai' | 'team';
  
  const [activeTab, setActiveTab] = useState<'personal' | 'ai' | 'team'>(tabParam || 'personal');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isTestingModel, setIsTestingModel] = useState(false);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [modelTestResult, setModelTestResult] = useState<{
    ok: boolean;
    message: string;
    latencyMs?: number;
    statusCode?: number;
    checkedAt?: string;
    modelFound?: boolean;
  } | null>(null);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [recommendedModels, setRecommendedModels] = useState<string[]>([]);
  const [modelDiscoverResult, setModelDiscoverResult] = useState<{
    ok: boolean;
    message: string;
    statusCode?: number;
    latencyMs?: number;
    baseUrl?: string;
    selectedModelAvailable?: boolean;
  } | null>(null);
  const [mcpSearchQuery, setMcpSearchQuery] = useState("playwright");
  const [mcpSearchResult, setMcpSearchResult] = useState<string>("");
  const [isSearchingMcp, setIsSearchingMcp] = useState(false);
  const [isInstallingMcp, setIsInstallingMcp] = useState<string | null>(null);
  const [mcpSearchItems, setMcpSearchItems] = useState<McpSearchItem[]>([]);
  const [skillImportError, setSkillImportError] = useState<string>("");
  const [mcpSearchPage, setMcpSearchPage] = useState(1);
  const [mcpInstallVerification, setMcpInstallVerification] = useState<Record<string, McpInstallVerification>>({});
  const [mcpToolsByServer, setMcpToolsByServer] = useState<Record<string, string[]>>({});
  const [isLoadingMcpTools, setIsLoadingMcpTools] = useState<string | null>(null);
  const [mcpToolCallPayload, setMcpToolCallPayload] = useState<Record<string, string>>({});
  const [mcpToolCallResult, setMcpToolCallResult] = useState<Record<string, string>>({});
  const [isCallingMcpTool, setIsCallingMcpTool] = useState<string | null>(null);

  // States
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [settings, setSettings] = useState<UserAISettings | null>(null);
  const [teams, setTeams] = useState<TeamInfo[]>([]);
  
  // Custom states for forms
  const [passwords, setPasswords] = useState({ old: "", new: "", confirm: "" });
  const [newTeamName, setNewTeamName] = useState("");
  
  // Member management state
  const [activeTeamId, setActiveTeamId] = useState<string | null>(null);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [teamAuditLogs, setTeamAuditLogs] = useState<TeamAuditLog[]>([]);
  const [auditActorFilter, setAuditActorFilter] = useState("");
  const [auditActionPrefix, setAuditActionPrefix] = useState("team.member.");
  const [auditLimit, setAuditLimit] = useState(50);
  const [newMemberUserId, setNewMemberUserId] = useState("");

  /* eslint-disable react-hooks/exhaustive-deps */
  // Intentionally load once on mount; `loadAllData` reads latest state via setters.
  useEffect(() => {
    loadAllData();
  }, []);

  useEffect(() => {
    if (tabParam && (tabParam === 'personal' || tabParam === 'ai' || tabParam === 'team')) {
      setActiveTab(tabParam);
    }
  }, [tabParam]);

  // Intentionally refresh team audit when filters/team context changes.
  useEffect(() => {
    if (activeTab !== "team" || !activeTeamId) return;
    void loadTeamAuditLogs(activeTeamId);
  }, [activeTab, activeTeamId, auditActorFilter, auditActionPrefix, auditLimit]);
  /* eslint-enable react-hooks/exhaustive-deps */

  async function loadAllData() {
    setIsLoading(true);
    try {
      const [profileResult, settingsResult, teamsResult] = await Promise.allSettled([
        fetchJsonWithClientCache<Record<string, unknown>>("/api/auth/me", {
          ttlMs: 15_000,
          key: "GET:/api/auth/me",
        }),
        fetchJsonWithClientCache<Record<string, unknown>>("/api/settings", {
          ttlMs: 15_000,
          key: "GET:/api/settings",
        }),
        fetchJsonWithClientCache<TeamInfo[]>("/api/teams", {
          ttlMs: 15_000,
          key: "GET:/api/teams",
        }),
      ]);

      const profileData = profileResult.status === "fulfilled" ? profileResult.value : null;
      const settingsData = settingsResult.status === "fulfilled" ? settingsResult.value : null;
      const teamsData = teamsResult.status === "fulfilled" ? teamsResult.value : null;

      if (profileData) {
        setProfile(profileData as unknown as UserProfile);
      } else if (!profile) {
        setProfile({ id: "", username: "Guest", name: "Guest", nickname: "", role: "user", avatarUrl: "", createdAt: "" });
      }

      if (settingsData) {
        const normalized = settingsData as unknown as UserAISettings;
        setSettings({
          ...normalized,
          customRulesText: normalized.customRulesText ?? normalized.customRules.join("\n"),
          skillSearchPaths: Array.isArray(normalized.skillSearchPaths) ? normalized.skillSearchPaths : [],
        });
        const initialTools: Record<string, string[]> = {};
        for (const server of Array.isArray(normalized.mcpServers) ? normalized.mcpServers : []) {
          const tools = Array.isArray(server?.tools) && server.tools.length > 0
            ? server.tools
            : defaultToolsForServer(String(server?.name || ""));
          if (tools.length > 0) {
            initialTools[String(server.name)] = tools;
          }
        }
        setMcpToolsByServer(initialTools);
      } else if (!settings) {
        setSettings({
          modelBaseUrl: "",
          modelApiKey: "",
          modelName: "",
          maxTokens: 4096,
          temperature: 0.7,
          systemPrompt: "",
          mcpServers: [
            { name: "filesystem", command: "", args: [], env: {}, enabled: true, builtIn: true, source: "builtin", tools: defaultToolsForServer("filesystem") },
            { name: "fetch", command: "", args: [], env: {}, enabled: true, builtIn: true, source: "builtin", tools: defaultToolsForServer("fetch") },
            { name: "playwright", command: "", args: [], env: {}, enabled: true, builtIn: true, source: "builtin", tools: defaultToolsForServer("playwright") },
          ],
          customRules: [],
          customRulesText: "",
          skillSearchPaths: [],
        });
        setMcpToolsByServer({
          filesystem: defaultToolsForServer("filesystem"),
          fetch: defaultToolsForServer("fetch"),
          playwright: defaultToolsForServer("playwright"),
        });
      }

      setTeams(Array.isArray(teamsData) ? teamsData : []);

      const errors = [profileResult, settingsResult, teamsResult]
        .filter((item): item is PromiseRejectedResult => item.status === "rejected")
        .map((item) => String(item.reason instanceof Error ? item.reason.message : item.reason || ""));
      const hasAuthExpired = errors.some((msg) => /401|未登录|登录已过期/.test(msg));
      const settingsFailed = settingsResult.status === "rejected";
      if (hasAuthExpired && settingsFailed) {
        await fetch("/api/auth/logout", { method: "POST" });
        router.replace("/login");
        return;
      }
    } catch (e) {
      console.error("Failed to load settings data:", e);
      if (e instanceof Error && /401|未登录|登录已过期/.test(e.message)) {
        await fetch("/api/auth/logout", { method: "POST" });
        router.replace("/login");
        return;
      }
      // Even if it fails, set some defaults to allow rendering
      if (!profile) setProfile({ id: "", username: "Guest", name: "Guest", nickname: "", role: "user", avatarUrl: "", createdAt: "" });
      if (!settings) {
        setSettings({
          modelBaseUrl: "",
          modelApiKey: "",
          modelName: "",
          maxTokens: 4096,
          temperature: 0.7,
          systemPrompt: "",
          mcpServers: [],
          customRules: [],
          customRulesText: "",
          skillSearchPaths: [],
        });
      }
    } finally {
      setIsLoading(false);
    }
  }

  async function loadTeamMembers(teamId: string) {
    try {
      const res = await fetch(`/api/teams/${teamId}/members`);
      if (res.ok) {
        setTeamMembers(await res.json());
        setActiveTeamId(teamId);
        void loadTeamAuditLogs(teamId);
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function loadTeamAuditLogs(teamId: string) {
    try {
      const params = new URLSearchParams();
      params.set("teamId", teamId);
      params.set("limit", String(auditLimit));
      if (auditActorFilter.trim()) params.set("actorId", auditActorFilter.trim());
      if (auditActionPrefix.trim()) params.set("actionPrefix", auditActionPrefix.trim());
      const res = await fetch(`/api/audit/logs?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      setTeamAuditLogs(Array.isArray(data?.items) ? data.items : []);
    } catch (e) {
      console.error(e);
    }
  }

  const exportTeamAuditCsv = () => {
    if (teamAuditLogs.length === 0) return;
    const lines = [
      ["id", "createdAt", "action", "actorId", "targetType", "targetId", "payload"].join(","),
      ...teamAuditLogs.map((log) => {
        const payload = JSON.stringify(log.payload || {}).replace(/"/g, '""');
        return [
          log.id,
          log.createdAt,
          log.action,
          log.actorId || "",
          log.targetType,
          log.targetId,
          `"${payload}"`,
        ]
          .map((item) => `"${String(item).replace(/"/g, '""')}"`)
          .join(",");
      }),
    ];
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `team-audit-${activeTeamId || "unknown"}-${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const handleSaveProfile = async () => {
    if (!profile) return;
    setIsSaving(true);
    try {
      const res = await fetch("/api/auth/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          nickname: profile.nickname, 
          name: profile.name, 
          avatarUrl: profile.avatarUrl
        })
      });
      if (res.ok) {
        invalidateClientRequestCache("GET:/api/auth/me");
        triggerSuccess();
      }
    } finally { setIsSaving(false); }
  };

  const handleChangePassword = async () => {
    if (passwords.new !== passwords.confirm) return alert("两次密码输入不一致");
    if (passwords.new.length < 6) return alert("新密码长度需至少 6 位");
    setIsSaving(true);
    try {
      const res = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ oldPassword: passwords.old, newPassword: passwords.new })
      });
      if (res.ok) {
        triggerSuccess();
        setPasswords({ old: "", new: "", confirm: "" });
        alert("密码修改成功");
      } else {
        const err = await res.json();
        alert(err.detail || "密码修改失败");
      }
    } finally { setIsSaving(false); }
  };

  const parseRulesText = (raw: string): string[] => {
    const text = String(raw || "").trim();
    if (!text) return [];
    if (text.startsWith("[")) {
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) {
          return parsed.map((item) => String(item).trim()).filter(Boolean);
        }
      } catch {
        // fallback to line parsing
      }
    }
    return text
      .split(/\r?\n/g)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#") && !line.startsWith("//"))
      .map((line) => (line.startsWith("- ") ? line.slice(2).trim() : line))
      .filter(Boolean);
  };

  const parseRulesForPreview = (raw: string): ParsedRule[] => {
    return parseRulesText(raw).map((item) => {
      let text = item.trim();
      let priority = "P2";
      let scope = "global";

      const bracketPriority = text.match(/^\[(P[0-3])\]\s*/i);
      if (bracketPriority) {
        priority = bracketPriority[1].toUpperCase();
        text = text.slice(bracketPriority[0].length).trim();
      }

      const bracketScope = text.match(/^\[(global|module:[^\]]+)\]\s*/i);
      if (bracketScope) {
        scope = bracketScope[1];
        text = text.slice(bracketScope[0].length).trim();
      }

      const plainPriority = text.match(/^(P[0-3])\s*[:：-]\s*/i);
      if (plainPriority) {
        priority = plainPriority[1].toUpperCase();
        text = text.slice(plainPriority[0].length).trim();
      }

      const plainScope = text.match(/^(global|module:[^:]+)\s*[:：-]\s*/i);
      if (plainScope) {
        scope = plainScope[1];
        text = text.slice(plainScope[0].length).trim();
      }

      return {
        raw: item,
        priority,
        scope,
        content: text || item,
      };
    });
  };

  const parseSkillLines = (raw: string): string[] => {
    const text = String(raw || "").trim();
    if (!text) return [];
    if (text.startsWith("[")) {
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) {
          return parsed.map((item) => String(item).trim()).filter(Boolean);
        }
      } catch {
        // fall through to line parsing
      }
    }
    return text
      .split(/\r?\n/g)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#") && !line.startsWith("//"));
  };

  const isBuiltinMcp = (name: string) => ["filesystem", "fetch", "playwright"].includes(String(name || "").trim());
  const filterCatalog = (query: string): McpSearchItem[] => {
    const q = query.trim().toLowerCase();
    if (!q) return MCP_CATALOG;
    return MCP_CATALOG.filter((item) => {
      const text = [item.name, item.qualifiedName, item.description, item.packageName].join(" ").toLowerCase();
      return text.includes(q);
    });
  };

  const parseMcpSearchItems = (rawText: string): McpSearchItem[] => {
    const items: McpSearchItem[] = [];
    for (const line of String(rawText || "").split(/\r?\n/g)) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const parsed = JSON.parse(trimmed) as Record<string, unknown>;
        const qualifiedName = String(parsed.qualifiedName ?? parsed.name ?? "").trim();
        const name = String(parsed.name ?? qualifiedName ?? "").trim();
        if (!qualifiedName || !name) continue;
        items.push({
          name,
          qualifiedName,
          description: String(parsed.description ?? "").trim(),
          useCount: Number.isFinite(Number(parsed.useCount)) ? Number(parsed.useCount) : undefined,
          connectionUrl: String(parsed.connectionUrl ?? "").trim() || undefined,
          packageName: String(parsed.packageName ?? "").trim() || undefined,
        });
      } catch {
        // ignore non-JSON lines
      }
    }
    return items;
  };

  const handleSaveAI = async () => {
    if (!settings) return;
    setIsSaving(true);
    try {
      const parsedRules = parseRulesText(settings.customRulesText ?? "");
      const payloadSettings = {
        ...settings,
        customRules: parsedRules.length > 0 ? parsedRules : settings.customRules,
        customRulesText: (settings.customRulesText ?? "").trim(),
        mcpServers: settings.mcpServers.map((server) => ({
          ...server,
          builtIn: server.builtIn ?? isBuiltinMcp(server.name),
          source: server.source ?? (isBuiltinMcp(server.name) ? "builtin" : "custom"),
        })),
      };
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: payloadSettings })
      });
      if (res.ok) {
        invalidateClientRequestCache("GET:/api/settings");
        setSettings((prev) => prev ? ({ ...prev, customRules: payloadSettings.customRules }) : prev);
        triggerSuccess();
      }
    } finally { setIsSaving(false); }
  };

  const handleSearchMcp = async () => {
    const q = mcpSearchQuery.trim();
    if (!q) return;
    setIsSearchingMcp(true);
    setMcpSearchResult("");
    setMcpSearchItems([]);
    setMcpSearchPage(1);
    const localItems = filterCatalog(q);
    try {
      const res = await fetch(`/api/integrations/smithery/search?q=${encodeURIComponent(q)}`, {
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      const text =
        String(data?.result?.stdout || data?.stdout || "") ||
        String(data?.result?.stderr || data?.stderr || "") ||
        JSON.stringify(data, null, 2);
      const onlineItems = parseMcpSearchItems(text);
      const merged = Array.from(
        new Map(
          [...localItems, ...onlineItems].map((item) => [
            item.qualifiedName.toLowerCase(),
            item,
          ]),
        ).values(),
      );
      setMcpSearchResult(
        merged.length > 0
          ? `搜索完成：本地候选 ${localItems.length}，在线候选 ${onlineItems.length}。`
          : (text || "未检索到 MCP，请尝试输入更完整的 npm 包名。"),
      );
      setMcpSearchItems(merged);
    } catch (error) {
      setMcpSearchResult(`在线搜索失败，已回退本地目录：${error instanceof Error ? error.message : "未知错误"}`);
      setMcpSearchItems(localItems);
    } finally {
      setIsSearchingMcp(false);
    }
  };

  const handleInstallMcp = async (serverName: string, connectionId?: string) => {
    if (!settings) return;
    const installId = connectionId || serverName;
    setIsInstallingMcp(installId);
    try {
      const normalizedConnectionId = installId.replace(/[\/\s]+/g, "-");
      const matched = MCP_CATALOG.find(
        (item) =>
          item.qualifiedName.toLowerCase() === serverName.toLowerCase()
          || item.name.toLowerCase() === serverName.toLowerCase(),
      );
      const packageName = matched?.packageName
        || (serverName.includes("/") || serverName.startsWith("@") ? serverName : undefined);
      const res = await fetch("/api/integrations/smithery/connections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          server: serverName,
          connectionId: normalizedConnectionId,
          metadata: {
            packageName,
          },
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.ok === false) {
        const rawError = String(data?.stderr || data?.error || "安装失败");
        if (/npm error 404/i.test(rawError)) {
          const fallbackPkg = packageName || "请改用可用 npm 包名";
          alert(
            `安装失败：npm 包不存在。\n` +
            `当前尝试：${fallbackPkg}\n` +
            `建议：jira 使用 jira-mcp，notion 使用 @notionhq/notion-mcp-server，github 使用 github-mcp-server。`,
          );
        } else {
          alert(rawError);
        }
        return;
      }
      let verifyMessage = "已安装，未执行验证";
      let verifyOk = true;
      let verifyToolCount = 0;
      let serverConfig: Partial<McpConfig> = {};
      try {
        const result = data?.result || data || {};
        const parsedStdout = JSON.parse(String(result?.stdout || "{}")) as Record<string, unknown>;
        const tools = Array.isArray(parsedStdout?.tools) ? parsedStdout.tools.map((item) => String(item)) : [];
        verifyToolCount = tools.length;
        verifyMessage = String(parsedStdout?.note || "安装成功");
        setMcpToolsByServer((prev) => ({ ...prev, [normalizedConnectionId]: tools }));
        serverConfig = (parsedStdout?.config as Partial<McpConfig> | undefined) || {};
      } catch (error) {
        verifyMessage = `验证异常：${error instanceof Error ? error.message : "未知错误"}`;
        verifyOk = false;
      }
      setMcpInstallVerification((prev) => ({
        ...prev,
        [normalizedConnectionId]: {
          ok: verifyOk,
          toolCount: verifyToolCount,
          message: verifyMessage,
        },
      }));
      setSettings((prev) => {
        if (!prev) return prev;
        const exists = prev.mcpServers.find((item) => item.name === normalizedConnectionId);
        const mergedServer = {
          name: normalizedConnectionId,
          command: String(serverConfig.command || ""),
          args: Array.isArray(serverConfig.args) ? serverConfig.args : [],
          env: (serverConfig.env && typeof serverConfig.env === "object") ? serverConfig.env as Record<string, string> : {},
          enabled: true,
          builtIn: isBuiltinMcp(normalizedConnectionId),
          source: String(serverConfig.source || "installed"),
          tools: Array.isArray(serverConfig.tools) ? serverConfig.tools : (matched?.presetTools || []),
        };
        if (exists) {
          return {
            ...prev,
            mcpServers: prev.mcpServers.map((item) =>
              item.name === normalizedConnectionId ? { ...item, ...mergedServer } : item,
            ),
          };
        }
        return {
          ...prev,
          mcpServers: [
            ...prev.mcpServers,
            mergedServer,
          ],
        };
      });
      alert(`已安装 MCP：${installId}\n${verifyMessage}`);
    } catch (error) {
      alert(`安装失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setIsInstallingMcp(null);
    }
  };

  const parseToolNames = (stdout: string): string[] => {
    const lines = String(stdout || "")
      .split(/\r?\n/g)
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) return [];
    const names: string[] = [];
    for (const line of lines) {
      try {
        const parsed = JSON.parse(line) as Record<string, unknown>;
        const n = String(parsed.name ?? parsed.tool ?? "").trim();
        if (n) names.push(n);
        continue;
      } catch {
        // fallback plain text
      }
      if (line.startsWith("- ")) {
        names.push(line.slice(2).trim());
      } else {
        names.push(line);
      }
    }
    return Array.from(new Set(names.filter(Boolean)));
  };

  const handleLoadMcpTools = async (serverName: string) => {
    setIsLoadingMcpTools(serverName);
    try {
      const localFallback = defaultToolsForServer(serverName);
      if (localFallback.length > 0) {
        setMcpToolsByServer((prev) => ({ ...prev, [serverName]: localFallback }));
      }
      const res = await fetch(
        `/api/integrations/smithery/connections/${encodeURIComponent(serverName)}/tools`,
        { cache: "no-store" },
      );
      const data = await res.json().catch(() => ({}));
      const result = data?.result || {};
      const stdout = String(result?.stdout || data?.stdout || "");
      const stderr = String(result?.stderr || data?.stderr || "");
      const tools = parseToolNames(stdout);
      const mergedTools = Array.from(new Set([...(tools || []), ...localFallback]));
      setMcpToolsByServer((prev) => ({ ...prev, [serverName]: mergedTools }));
      setSettings((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          mcpServers: prev.mcpServers.map((item) =>
            item.name === serverName ? { ...item, tools: mergedTools } : item,
          ),
        };
      });
      if (!mcpToolCallPayload[serverName]) {
        setMcpToolCallPayload((prev) => ({ ...prev, [serverName]: "{}" }));
      }
      if (!res.ok || /command not found/i.test(stderr)) {
        setMcpToolCallResult((prev) => ({
          ...prev,
          [serverName]: mergedTools.length > 0
            ? "已使用本地预置工具列表（当前环境未启用 smithery CLI）。"
            : "未读取到工具列表，请检查 MCP 配置。",
        }));
      }
    } catch (error) {
      const localFallback = defaultToolsForServer(serverName);
      if (localFallback.length > 0) {
        setMcpToolsByServer((prev) => ({ ...prev, [serverName]: localFallback }));
        setMcpToolCallResult((prev) => ({
          ...prev,
          [serverName]: `在线加载失败，已回退预置工具：${error instanceof Error ? error.message : "未知错误"}`,
        }));
      } else {
        setMcpToolCallResult((prev) => ({
          ...prev,
          [serverName]: `加载工具失败：${error instanceof Error ? error.message : "未知错误"}`,
        }));
      }
    } finally {
      setIsLoadingMcpTools(null);
    }
  };

  const handleToggleMcpServer = (serverName: string, nextEnabled: boolean) => {
    if (!settings) return;
    setSettings({
      ...settings,
      mcpServers: settings.mcpServers.map((item) =>
        item.name === serverName ? { ...item, enabled: nextEnabled } : item,
      ),
    });
  };

  const handleCallMcpTool = async (serverName: string, toolName: string) => {
    const callKey = `${serverName}:${toolName}`;
    setIsCallingMcpTool(callKey);
    try {
      const payloadText = (mcpToolCallPayload[serverName] || "{}").trim() || "{}";
      let payload: Record<string, unknown> = {};
      try {
        payload = JSON.parse(payloadText) as Record<string, unknown>;
      } catch {
        alert("调用参数必须是合法 JSON");
        return;
      }
      const res = await fetch(
        `/api/integrations/smithery/connections/${encodeURIComponent(serverName)}/tools/${encodeURIComponent(toolName)}/call`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ payload }),
        },
      );
      const data = await res.json().catch(() => ({}));
      const result = data?.result || data;
      const stdout = String(result?.stdout || data?.stdout || "");
      const stderr = String(result?.stderr || data?.stderr || "");
      const msg = stdout || stderr || JSON.stringify(data, null, 2);
      setMcpToolCallResult((prev) => ({ ...prev, [serverName]: `[${toolName}]\n${msg}` }));
    } catch (error) {
      setMcpToolCallResult((prev) => ({
        ...prev,
        [serverName]: `调用失败：${error instanceof Error ? error.message : "未知错误"}`,
      }));
    } finally {
      setIsCallingMcpTool(null);
    }
  };

  const handleImportSkillsFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !settings) return;
    setSkillImportError("");
    try {
      const text = await file.text();
      const lines = parseSkillLines(text);
      if (lines.length === 0) {
        setSkillImportError("文件内容为空，或未解析出有效 skill 路径。");
        return;
      }
      const merged = Array.from(new Set([...(settings.skillSearchPaths || []), ...lines]));
      setSettings({ ...settings, skillSearchPaths: merged });
    } catch (error) {
      setSkillImportError(`导入失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      event.target.value = "";
    }
  };

  const handleTestModelConnection = async () => {
    if (!settings) return;
    setIsTestingModel(true);
    setModelTestResult(null);
    try {
      const res = await fetch("/api/settings/test-model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
      });
      const data = await res.json().catch(() => ({ ok: false, message: "测试返回非 JSON 响应" }));
      setModelTestResult({
        ok: Boolean(data?.ok),
        message: String(data?.message || (data?.ok ? "连接成功" : "连接失败")),
        latencyMs: Number.isFinite(Number(data?.latencyMs)) ? Number(data?.latencyMs) : undefined,
        statusCode: Number.isFinite(Number(data?.statusCode)) ? Number(data?.statusCode) : undefined,
        checkedAt: typeof data?.checkedAt === "string" ? data.checkedAt : undefined,
        modelFound: typeof data?.modelFound === "boolean" ? data.modelFound : undefined,
      });
    } catch (error) {
      setModelTestResult({ ok: false, message: `测试失败：${error instanceof Error ? error.message : "未知错误"}` });
    } finally {
      setIsTestingModel(false);
    }
  };

  const handleDiscoverModels = async () => {
    if (!settings) return;
    setIsLoadingModels(true);
    setModelDiscoverResult(null);
    try {
      const res = await fetch("/api/settings/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
      });
      const data = await res.json().catch(() => ({ ok: false, message: "模型列表返回非 JSON 响应", models: [] }));
      const models = Array.isArray(data?.models)
        ? data.models.map((v: unknown) => String(v)).filter(Boolean)
        : [];
      const recs = Array.isArray(data?.recommendedModels)
        ? data.recommendedModels.map((v: unknown) => String(v)).filter(Boolean)
        : [];
      setModelOptions(models);
      setRecommendedModels(recs);
      setModelDiscoverResult({
        ok: Boolean(data?.ok),
        message: String(data?.message || (data?.ok ? "模型列表获取成功" : "模型列表获取失败")),
        statusCode: Number.isFinite(Number(data?.statusCode)) ? Number(data?.statusCode) : undefined,
        latencyMs: Number.isFinite(Number(data?.latencyMs)) ? Number(data?.latencyMs) : undefined,
        baseUrl: typeof data?.baseUrl === "string" ? data.baseUrl : undefined,
        selectedModelAvailable: typeof data?.selectedModelAvailable === "boolean" ? data.selectedModelAvailable : undefined,
      });

      if (models.length > 0 && !models.includes(settings.modelName)) {
        const pick = recs[0] || models[0];
        setSettings({ ...settings, modelName: pick });
      }
    } catch (error) {
      setModelDiscoverResult({
        ok: false,
        message: `获取模型列表失败：${error instanceof Error ? error.message : "未知错误"}`,
      });
      setModelOptions([]);
      setRecommendedModels([]);
    } finally {
      setIsLoadingModels(false);
    }
  };
  
  const handleCreateTeam = async () => {
    if (!newTeamName.trim()) return;
    try {
      const res = await fetch("/api/teams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orgId: "DEFAULT_ORG", name: newTeamName })
      });
      if (res.ok) {
        invalidateClientRequestCache("GET:/api/teams");
        setNewTeamName("");
        loadAllData();
      }
    } catch (e) { console.error(e); }
  };

  const handleAddMember = async () => {
    if (!activeTeamId || !newMemberUserId.trim()) return;
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: newMemberUserId.trim(), role: "member" })
      });
        if (res.ok) {
          invalidateClientRequestCache("GET:/api/teams");
          setNewMemberUserId("");
          loadTeamMembers(activeTeamId);
          void loadTeamAuditLogs(activeTeamId);
        } else {
        const err = await res.json();
        alert(err.detail || "添加失败");
      }
    } catch (e) { console.error(e); }
  };

  const handleRemoveMember = async (memberId: string) => {
    if (!activeTeamId) return;
    if (!confirm("确定移除该成员吗？")) return;
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/members?memberId=${encodeURIComponent(memberId)}`, { method: "DELETE" });
        if (res.ok) {
          invalidateClientRequestCache("GET:/api/teams");
          loadTeamMembers(activeTeamId);
          loadAllData();
          void loadTeamAuditLogs(activeTeamId);
        }
    } catch (e) { console.error(e); }
  };

  const handleUpdateMemberRole = async (memberId: string, role: string) => {
    if (!activeTeamId) return;
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/members`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memberId, role }),
      });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert(err.detail || "角色更新失败");
          return;
        }
        loadTeamMembers(activeTeamId);
        void loadTeamAuditLogs(activeTeamId);
      } catch (e) {
      console.error(e);
      alert("角色更新失败");
    }
  };

  const triggerSuccess = () => {
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  if (isLoading || !profile || !settings) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Loader2 className="animate-spin" size={32} color="var(--primary)" />
      </div>
    );
  }

  // Common styles
  const inputTheme = {
    background: 'var(--panel-strong)', color: 'var(--ink)', 
    border: '1px solid var(--line)', padding: '10px 14px',
    borderRadius: '10px', fontSize: '0.95rem', width: '100%',
    outline: 'none', transition: 'border-color 0.2s'
  };
  const labelStyle = { display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--ink-soft)', fontWeight: 500 };
  const cardStyle = { background: 'var(--bg-main)', border: '1px solid var(--line)', borderRadius: '16px', padding: '24px' };
  const MCP_SEARCH_PAGE_SIZE = 6;
  const mcpSearchTotalPages = Math.max(1, Math.ceil(mcpSearchItems.length / MCP_SEARCH_PAGE_SIZE));
  const safeMcpSearchPage = Math.min(mcpSearchPage, mcpSearchTotalPages);
  const pagedMcpSearchItems = mcpSearchItems.slice(
    (safeMcpSearchPage - 1) * MCP_SEARCH_PAGE_SIZE,
    safeMcpSearchPage * MCP_SEARCH_PAGE_SIZE,
  );

  return (
    <div style={{ padding: '32px', display: 'flex', flexDirection: 'column', height: '100%', boxSizing: 'border-box' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14, marginBottom: '26px', flexWrap: 'wrap' }}>
        <PageHeader
          icon={<Settings size={18} />}
          title="设置中心"
          subtitle="管理个人资料、团队组织与 AI 配置。"
          tags={["个人资料", "团队组织", "AI 配置"]}
          style={{ marginBottom: 0 }}
        />
        
        <div style={{ display: 'flex', background: 'var(--panel)', padding: '4px', borderRadius: '12px', border: '1px solid var(--line)'}}>
          <TabBtn active={activeTab === 'personal'} onClick={() => setActiveTab('personal')} icon={<UserIcon size={16}/>} label="个人资料" />
          <TabBtn active={activeTab === 'team'} onClick={() => { setActiveTab('team'); setActiveTeamId(null); }} icon={<Building2 size={16}/>} label="团队组织" />
          <TabBtn active={activeTab === 'ai'} onClick={() => setActiveTab('ai')} icon={<BrainCircuit size={16}/>} label="AI 模型配置" />
        </div>

        <div>
          {activeTab !== 'team' && (
            <button 
              className="btn-primary" 
              onClick={activeTab === 'ai' ? handleSaveAI : handleSaveProfile}
              disabled={isSaving}
              style={{ padding: '8px 20px', borderRadius: '10px', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, background: 'var(--primary)', color: 'white' }}
            >
              {isSaving ? <Loader2 size={16} className="animate-spin" /> : saveSuccess ? <CheckCircle2 size={16} /> : <Save size={16} />}
              {saveSuccess ? "已保存" : "保存修改"}
            </button>
          )}
        </div>
      </header>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {/* ================= PERSONAL TAB ================= */}
        {activeTab === 'personal' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '800px', margin: '0 auto' }}>
            <div style={cardStyle}>
              <h2 style={{ margin: '0 0 24px 0', fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <UserIcon size={20} color="var(--primary)" /> 基本信息
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                <div><label style={labelStyle}>账号 (Username)</label><input style={{...inputTheme, opacity: 0.7}} value={profile.username} disabled /></div>
                <div><label style={labelStyle}>角色 (Role)</label><input style={{...inputTheme, opacity: 0.7}} value={profile.role} disabled /></div>
                <div><label style={labelStyle}>真实姓名</label><input style={inputTheme} value={profile.name} onChange={e => setProfile({...profile, name: e.target.value})} /></div>
                <div><label style={labelStyle}>花名 / 昵称</label><input style={inputTheme} value={profile.nickname || ''} onChange={e => setProfile({...profile, nickname: e.target.value})} /></div>
                <div style={{ gridColumn: '1 / -1' }}><label style={labelStyle}>头像链接</label><input style={inputTheme} value={profile.avatarUrl || ''} onChange={e => setProfile({...profile, avatarUrl: e.target.value})} placeholder="https://..." /></div>
              </div>
            </div>

            <div style={cardStyle}>
              <h2 style={{ margin: '0 0 24px 0', fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Lock size={20} color="var(--primary)" /> 安全设置
              </h2>
              <form onSubmit={(e) => { e.preventDefault(); handleChangePassword(); }}>
                {/* Hidden username field for accessibility and password managers */}
                <input type="text" name="username" value={profile.username} autoComplete="username" style={{ display: 'none' }} readOnly />
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                  <div style={{ gridColumn: '1 / -1' }}>
                    <label style={labelStyle} htmlFor="old-password">当前密码</label>
                    <input 
                      id="old-password"
                      type="password" 
                      name="current-password"
                      autoComplete="current-password"
                      style={inputTheme} 
                      value={passwords.old} 
                      onChange={e => setPasswords({...passwords, old: e.target.value})} 
                    />
                  </div>
                  <div>
                    <label style={labelStyle} htmlFor="new-password">新密码</label>
                    <input 
                      id="new-password"
                      type="password" 
                      name="new-password"
                      autoComplete="new-password"
                      style={inputTheme} 
                      value={passwords.new} 
                      onChange={e => setPasswords({...passwords, new: e.target.value})} 
                    />
                  </div>
                  <div>
                    <label style={labelStyle} htmlFor="confirm-password">确认新密码</label>
                    <input 
                      id="confirm-password"
                      type="password" 
                      name="confirm-password"
                      autoComplete="new-password"
                      style={inputTheme} 
                      value={passwords.confirm} 
                      onChange={e => setPasswords({...passwords, confirm: e.target.value})} 
                    />
                  </div>
                </div>
                <button 
                  type="submit"
                  disabled={isSaving || !passwords.old || !passwords.new || passwords.new !== passwords.confirm}
                  style={{ marginTop: '24px', padding: '10px 24px', borderRadius: '10px', background: 'var(--panel-strong)', border: '1px solid var(--line)', color: 'var(--ink)', cursor: 'pointer', fontWeight: 500 }}
                >
                  更改密码
                </button>
              </form>
            </div>
          </div>
        )}

        {/* ================= AI TAB ================= */}
        {activeTab === 'ai' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '800px', margin: '0 auto' }}>
            <div style={cardStyle}>
              <h2 style={{ margin: '0 0 24px 0', fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <BrainCircuit size={20} color="var(--primary)" /> LLM API 配置
              </h2>
              <form onSubmit={(e) => { e.preventDefault(); handleSaveAI(); }}>
                {/* Hidden username field for accessibility */}
                <input type="text" name="username" value="llm-api" autoComplete="username" style={{ display: 'none' }} readOnly />
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div>
                    <label style={labelStyle}>快捷预设 (Provider)</label>
                    <select 
                      style={inputTheme}
                      onChange={e => {
                        const val = e.target.value;
                        if (val === "custom") return;
                        const [url, model] = val.split("|");
                        setSettings({...settings, modelBaseUrl: url, modelName: model});
                      }}
                      defaultValue="custom"
                    >
                      <option value="custom">自定义 (Custom) / 保持当前配置</option>
                      <option value="https://api.deepseek.com/v1|deepseek-chat">⚡ DeepSeek (推荐: deepseek-chat)</option>
                      <option value="https://api.openai.com/v1|gpt-4o">🌐 OpenAI (gpt-4o)</option>
                      <option value="https://dashscope.aliyuncs.com/compatible-mode/v1|qwen-plus">☁️ 阿里通义千问 (qwen-plus)</option>
                      <option value="http://127.0.0.1:11434/v1|llama3">🖥️ 本地部署 Ollama (llama3)</option>
                    </select>
                  </div>
                  <div><label style={labelStyle}>API Base URL</label><input style={inputTheme} value={settings.modelBaseUrl} onChange={e => setSettings({...settings, modelBaseUrl: e.target.value})} placeholder="https://api.openai.com/v1" /></div>
                  <div>
                    <label style={labelStyle} htmlFor="api-key">API Key (Bearer Token)</label>
                    <input 
                      id="api-key"
                      type="password" 
                      name="api-key"
                      autoComplete="current-password"
                      style={inputTheme} 
                      value={settings.modelApiKey} 
                      onChange={e => setSettings({...settings, modelApiKey: e.target.value})} 
                      placeholder="sk-..." 
                    />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                    <div>
                      <label style={labelStyle}>模型名称</label>
                      <div style={{ display: "flex", gap: 8 }}>
                        <select
                          style={{ ...inputTheme, flex: "1 1 auto", minWidth: 0 }}
                          value={modelOptions.includes(settings.modelName) ? settings.modelName : ""}
                          onChange={e => {
                            if (!e.target.value) return;
                            setSettings({ ...settings, modelName: e.target.value });
                          }}
                        >
                          <option value="">从已发现模型中选择...</option>
                          {modelOptions.map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={handleDiscoverModels}
                          disabled={isLoadingModels || !settings.modelBaseUrl.trim() || !settings.modelApiKey.trim()}
                          style={{
                            border: "1px solid var(--line-strong)",
                            background: "var(--panel)",
                            color: "var(--ink)",
                            padding: "8px 12px",
                            borderRadius: "10px",
                            cursor: isLoadingModels ? "not-allowed" : "pointer",
                            fontWeight: 600,
                            whiteSpace: "nowrap",
                            opacity: isLoadingModels ? 0.8 : 1,
                          }}
                        >
                          {isLoadingModels ? "检测中..." : "检测模型"}
                        </button>
                      </div>
                      <input
                        style={{ ...inputTheme, marginTop: 8 }}
                        value={settings.modelName}
                        onChange={e => setSettings({ ...settings, modelName: e.target.value })}
                        placeholder="也可手动输入模型名"
                      />
                    </div>
                    <div><label style={labelStyle}>温度 (Temperature: {settings.temperature})</label><input type="range" min="0" max="2" step="0.1" value={settings.temperature} onChange={e => setSettings({...settings, temperature: parseFloat(e.target.value)})} style={{ width: '100%', marginTop: '10px' }} /></div>
                  </div>
                  {recommendedModels.length > 0 ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>推荐模型：</span>
                      {recommendedModels.map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() => setSettings({ ...settings, modelName: m })}
                          style={{
                            border: "1px solid var(--line-strong)",
                            background: settings.modelName === m ? "var(--primary-alpha-10)" : "var(--panel)",
                            color: settings.modelName === m ? "var(--primary)" : "var(--ink)",
                            padding: "4px 10px",
                            borderRadius: 999,
                            cursor: "pointer",
                            fontSize: "0.8rem",
                            fontWeight: 600,
                          }}
                        >
                          {m}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      onClick={handleTestModelConnection}
                      disabled={isTestingModel || !settings.modelBaseUrl.trim() || !settings.modelName.trim()}
                      style={{
                        border: "1px solid var(--line-strong)",
                        background: "var(--panel)",
                        color: "var(--ink)",
                        padding: "8px 14px",
                        borderRadius: "10px",
                        cursor: isTestingModel ? "not-allowed" : "pointer",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 8,
                        fontWeight: 600,
                        opacity: isTestingModel ? 0.8 : 1,
                      }}
                    >
                      {isTestingModel ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
                      {isTestingModel ? "测试中..." : "测试模型连接"}
                    </button>
                    {modelTestResult ? (
                      <div
                        style={{
                          fontSize: "0.85rem",
                          color: modelTestResult.ok ? "#15803d" : "#b91c1c",
                          background: modelTestResult.ok ? "rgba(22,163,74,.08)" : "rgba(220,38,38,.08)",
                          border: `1px solid ${modelTestResult.ok ? "rgba(22,163,74,.24)" : "rgba(220,38,38,.24)"}`,
                          borderRadius: 10,
                          padding: "8px 12px",
                        }}
                      >
                        <div>{modelTestResult.message}</div>
                        <div style={{ opacity: 0.85 }}>
                          {modelTestResult.statusCode ? `HTTP ${modelTestResult.statusCode}` : "HTTP -"}
                          {typeof modelTestResult.latencyMs === "number" ? ` · ${modelTestResult.latencyMs}ms` : ""}
                          {typeof modelTestResult.modelFound === "boolean"
                            ? modelTestResult.modelFound
                              ? " · 模型已在 /models 列表中"
                              : " · /models 未发现该模型（可能仍可调用）"
                            : ""}
                        </div>
                      </div>
                    ) : null}
                    {modelDiscoverResult ? (
                      <div
                        style={{
                          fontSize: "0.85rem",
                          color: modelDiscoverResult.ok ? "#0f766e" : "#b91c1c",
                          background: modelDiscoverResult.ok ? "rgba(15,118,110,.08)" : "rgba(220,38,38,.08)",
                          border: `1px solid ${modelDiscoverResult.ok ? "rgba(15,118,110,.24)" : "rgba(220,38,38,.24)"}`,
                          borderRadius: 10,
                          padding: "8px 12px",
                        }}
                      >
                        <div>{modelDiscoverResult.message}</div>
                        <div style={{ opacity: 0.85 }}>
                          {modelDiscoverResult.statusCode ? `HTTP ${modelDiscoverResult.statusCode}` : "HTTP -"}
                          {typeof modelDiscoverResult.latencyMs === "number" ? ` · ${modelDiscoverResult.latencyMs}ms` : ""}
                          {modelDiscoverResult.baseUrl ? ` · ${modelDiscoverResult.baseUrl}` : ""}
                          {typeof modelDiscoverResult.selectedModelAvailable === "boolean"
                            ? modelDiscoverResult.selectedModelAvailable
                              ? " · 当前模型可用"
                              : " · 当前模型不在列表中"
                            : ""}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              </form>
            </div>

            <div style={cardStyle}>
              <h2 style={{ margin: "0 0 12px 0", fontSize: "1.15rem", display: "flex", alignItems: "center", gap: 8 }}>
                <FileText size={18} color="var(--primary)" /> 自定义 Rules（模型记忆规则）
              </h2>
              <div style={{ color: "var(--ink-soft)", fontSize: "0.86rem", marginBottom: 10 }}>
                推荐格式：每行一条，支持注释。系统保存时会映射为底层 `customRules` 数组。
              </div>
              <textarea
                style={{ ...inputTheme, minHeight: 140, fontFamily: "ui-monospace, Menlo, Consolas, monospace" }}
                value={settings.customRulesText ?? settings.customRules.join("\n")}
                onChange={(e) => setSettings({ ...settings, customRulesText: e.target.value })}
                placeholder={"# 注释行会被忽略\n回答自然简洁，像测试同事协作\n信息不足时只问一个关键问题\n生成用例/接口参数时优先输出可落库结构"}
              />
              <div style={{ marginTop: 10, fontSize: "0.82rem", color: "var(--ink-soft)" }}>
                解析预览：
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                {parseRulesForPreview(settings.customRulesText ?? settings.customRules.join("\n")).slice(0, 8).map((item, idx) => (
                  <div key={`${item.raw}-${idx}`} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "6px 10px", background: "var(--panel)" }}>
                    <strong style={{ marginRight: 8 }}>{item.priority}</strong>
                    <span style={{ marginRight: 8, color: "var(--ink-soft)" }}>{item.scope}</span>
                    <span>{item.content}</span>
                  </div>
                ))}
              </div>
            </div>

            <div style={cardStyle}>
              <h2 style={{ margin: "0 0 12px 0", fontSize: "1.15rem", display: "flex", alignItems: "center", gap: 8 }}>
                <Download size={18} color="var(--primary)" /> Skills 导入
              </h2>
              <div style={{ color: "var(--ink-soft)", fontSize: "0.86rem", marginBottom: 10 }}>
                每行一个 skill 名称或路径（例如 `frontend-design` 或 `/opt/skills/qa/SKILL.md`）。
              </div>
              <textarea
                style={{ ...inputTheme, minHeight: 110, fontFamily: "ui-monospace, Menlo, Consolas, monospace" }}
                value={(settings.skillSearchPaths || []).join("\n")}
                onChange={(e) => {
                  const paths = e.target.value
                    .split(/\r?\n/g)
                    .map((line) => line.trim())
                    .filter(Boolean);
                  setSettings({ ...settings, skillSearchPaths: paths });
                }}
                placeholder={"frontend-design\nplaywright\nC:/skills/internal-testing/SKILL.md"}
              />
              <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <label
                  style={{
                    border: "1px solid var(--line)",
                    background: "var(--panel)",
                    borderRadius: 8,
                    padding: "6px 10px",
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  <Upload size={14} />
                  从文件导入
                  <input type="file" accept=".txt,.md,.json" style={{ display: "none" }} onChange={handleImportSkillsFile} />
                </label>
                <div style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>支持 `.txt/.md/.json`，支持每行一个 skill 或 JSON 数组。</div>
              </div>
              {skillImportError ? (
                <div style={{ marginTop: 8, color: "#b91c1c", fontSize: "0.82rem" }}>{skillImportError}</div>
              ) : null}
            </div>

            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, gap: 12 }}>
                <h2 style={{ margin: 0, fontSize: "1.2rem", display: "flex", alignItems: "center", gap: 8 }}>
                  <Settings size={20} color="var(--primary)" /> MCP Servers
                </h2>
                <div style={{ color: "var(--ink-soft)", fontSize: "0.85rem" }}>内置 MCP（filesystem/fetch/playwright）为只读，不可删除</div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, marginBottom: 10 }}>
                <input
                  style={inputTheme}
                  value={mcpSearchQuery}
                  onChange={(e) => setMcpSearchQuery(e.target.value)}
                  placeholder="搜索 MCP 或 npm 包（例如 github / @modelcontextprotocol/server-fetch）"
                />
                <button
                  onClick={handleSearchMcp}
                  disabled={isSearchingMcp || !mcpSearchQuery.trim()}
                  style={{ border: "none", background: "var(--primary)", color: "white", padding: "0 16px", borderRadius: 10, cursor: isSearchingMcp ? "not-allowed" : "pointer" }}
                >
                  {isSearchingMcp ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                </button>
              </div>

              <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                {["filesystem", "fetch", "playwright", "github", "notion", "jira"].map((name) => (
                  <button
                    key={name}
                    onClick={() => void handleInstallMcp(name)}
                    disabled={isInstallingMcp === name}
                    style={{ border: "1px solid var(--line)", background: "var(--panel)", color: "var(--ink)", padding: "6px 12px", borderRadius: 8, cursor: "pointer" }}
                  >
                    {isInstallingMcp === name ? "安装中..." : `安装 ${name}`}
                  </button>
                ))}
              </div>

              {mcpSearchResult ? (
                <pre
                  style={{
                    background: "var(--panel)",
                    border: "1px solid var(--line)",
                    borderRadius: 10,
                    padding: 10,
                    fontSize: "0.8rem",
                    maxHeight: 180,
                    overflow: "auto",
                    marginBottom: 14,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {mcpSearchResult}
                </pre>
              ) : null}

              {mcpSearchItems.length > 0 ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10, marginBottom: 14 }}>
                  {pagedMcpSearchItems.map((item) => (
                    <div key={item.qualifiedName} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 10, background: "var(--panel)" }}>
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>{item.name}</div>
                      <div style={{ fontSize: "0.8rem", color: "var(--ink-soft)", marginBottom: 6 }}>{item.qualifiedName}</div>
                      <div style={{ fontSize: "0.82rem", minHeight: 40 }}>{item.description || "无描述"}</div>
                      <div style={{ marginTop: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontSize: "0.78rem", color: "var(--ink-soft)" }}>useCount: {item.useCount ?? "-"}</span>
                        <button
                          onClick={() => void handleInstallMcp(item.qualifiedName, item.qualifiedName)}
                          disabled={isInstallingMcp === item.qualifiedName}
                          style={{ border: "1px solid var(--line)", background: "var(--bg-main)", padding: "4px 10px", borderRadius: 8, cursor: "pointer" }}
                        >
                          {isInstallingMcp === item.qualifiedName ? "安装中..." : "安装"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {mcpSearchItems.length > MCP_SEARCH_PAGE_SIZE ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: -4, marginBottom: 14 }}>
                  <button
                    onClick={() => setMcpSearchPage((prev) => Math.max(1, prev - 1))}
                    disabled={safeMcpSearchPage <= 1}
                    style={{ border: "1px solid var(--line)", background: "var(--panel)", padding: "4px 10px", borderRadius: 8, cursor: "pointer" }}
                  >
                    上一页
                  </button>
                  <span style={{ fontSize: "0.82rem", color: "var(--ink-soft)" }}>
                    第 {safeMcpSearchPage} / {mcpSearchTotalPages} 页
                  </span>
                  <button
                    onClick={() => setMcpSearchPage((prev) => Math.min(mcpSearchTotalPages, prev + 1))}
                    disabled={safeMcpSearchPage >= mcpSearchTotalPages}
                    style={{ border: "1px solid var(--line)", background: "var(--panel)", padding: "4px 10px", borderRadius: 8, cursor: "pointer" }}
                  >
                    下一页
                  </button>
                </div>
              ) : null}

              {settings.mcpServers.length === 0 ? (
                <div style={{ padding: "22px", textAlign: "center", color: "var(--ink-soft)", border: "1px dashed var(--line)", borderRadius: "12px" }}>
                  暂无 MCP Server 配置
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {settings.mcpServers.map((server, idx) => {
                    const builtIn = !!server.builtIn || isBuiltinMcp(server.name);
                    const verification = mcpInstallVerification[server.name];
                    const tools = mcpToolsByServer[server.name] || [];
                    return (
                      <div key={`${server.name}-${idx}`} style={{ padding: "12px 14px", border: "1px solid var(--line)", borderRadius: 12, background: "var(--panel)" }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center", gap: 8 }}>
                          <div>
                            <div style={{ fontWeight: 600 }}>
                              {server.name}
                              {builtIn ? (
                                <span style={{ marginLeft: 8, fontSize: "0.75rem", color: "var(--primary)", background: "var(--primary-alpha-10)", padding: "2px 6px", borderRadius: 6 }}>内置只读</span>
                              ) : null}
                            </div>
                            <div style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>
                              source: {server.source || (builtIn ? "builtin" : "custom")} · enabled: {server.enabled ? "true" : "false"}
                            </div>
                            {verification ? (
                              <div style={{ fontSize: "0.78rem", marginTop: 4, color: verification.ok ? "#15803d" : "#b91c1c" }}>
                                {verification.message}
                              </div>
                            ) : null}
                          </div>
                          {!builtIn ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <button
                                onClick={() => handleToggleMcpServer(server.name, !server.enabled)}
                                style={{
                                  border: "1px solid var(--line)",
                                  borderRadius: 8,
                                  padding: "4px 10px",
                                  cursor: "pointer",
                                  background: server.enabled ? "#fef2f2" : "#ecfdf5",
                                  color: server.enabled ? "#b91c1c" : "#047857",
                                  fontSize: "0.8rem",
                                }}
                              >
                                {server.enabled ? "停用" : "启用"}
                              </button>
                              <button
                                onClick={() => {
                                  const updated = [...settings.mcpServers];
                                  updated.splice(idx, 1);
                                  setSettings({ ...settings, mcpServers: updated });
                                }}
                                style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px", fontSize: "0.85rem" }}
                              >
                                <Trash2 size={14} /> 删除
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => handleToggleMcpServer(server.name, !server.enabled)}
                              style={{
                                border: "1px solid var(--line)",
                                borderRadius: 8,
                                padding: "4px 10px",
                                cursor: "pointer",
                                background: server.enabled ? "#fef2f2" : "#ecfdf5",
                                color: server.enabled ? "#b91c1c" : "#047857",
                                fontSize: "0.8rem",
                              }}
                            >
                              {server.enabled ? "停用" : "启用"}
                            </button>
                          )}
                        </div>
                        <div style={{ marginTop: 10, borderTop: "1px dashed var(--line)", paddingTop: 10 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                            <button
                              onClick={() => void handleLoadMcpTools(server.name)}
                              disabled={isLoadingMcpTools === server.name}
                              style={{ border: "1px solid var(--line)", background: "var(--bg-main)", padding: "4px 10px", borderRadius: 8, cursor: "pointer" }}
                            >
                              {isLoadingMcpTools === server.name ? "加载中..." : "加载工具列表"}
                            </button>
                            <span style={{ fontSize: "0.78rem", color: "var(--ink-soft)" }}>
                              工具数: {tools.length}
                            </span>
                          </div>
                          <textarea
                            style={{ ...inputTheme, minHeight: 70, fontFamily: "ui-monospace, Menlo, Consolas, monospace", padding: "8px 10px" }}
                            value={mcpToolCallPayload[server.name] ?? "{}"}
                            onChange={(e) => setMcpToolCallPayload((prev) => ({ ...prev, [server.name]: e.target.value }))}
                            placeholder='{"path":"./README.md"}'
                          />
                          {tools.length > 0 ? (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                              {tools.slice(0, 20).map((toolName) => {
                                const callKey = `${server.name}:${toolName}`;
                                return (
                                  <button
                                    key={toolName}
                                    onClick={() => void handleCallMcpTool(server.name, toolName)}
                                    disabled={isCallingMcpTool === callKey || !server.enabled}
                                    style={{ border: "1px solid var(--line)", background: "var(--panel)", padding: "4px 10px", borderRadius: 8, cursor: "pointer", fontSize: "0.8rem" }}
                                  >
                                    {isCallingMcpTool === callKey ? `调用 ${toolName}...` : `调用 ${toolName}`}
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                          {mcpToolCallResult[server.name] ? (
                            <pre
                              style={{
                                marginTop: 8,
                                background: "var(--bg-main)",
                                border: "1px solid var(--line)",
                                borderRadius: 8,
                                padding: 8,
                                fontSize: "0.78rem",
                                maxHeight: 160,
                                overflow: "auto",
                                whiteSpace: "pre-wrap",
                              }}
                            >
                              {mcpToolCallResult[server.name]}
                            </pre>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ================= TEAM TAB ================= */}
        {activeTab === 'team' && (
          <div style={{ display: 'flex', gap: '24px', height: '100%' }}>
            {/* 左侧架构树：组织 -> 团队 */}
            <div style={{ width: '300px', ...cardStyle, display: 'flex', flexDirection: 'column', padding: '20px' }}>
              <h2 style={{ margin: '0 0 20px 0', fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Building2 size={20} color="var(--primary)" /> 团队列表
              </h2>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flex: 1, overflowY: 'auto' }}>
                {teams.map(team => (
                  <div 
                    key={team.id} 
                    onClick={() => loadTeamMembers(team.id)}
                    style={{ 
                      padding: '12px 16px', borderRadius: '10px', cursor: 'pointer', transition: 'all 0.2s',
                      background: activeTeamId === team.id ? 'var(--primary-alpha-10)' : 'transparent',
                      border: activeTeamId === team.id ? '1px solid var(--primary)' : '1px solid transparent',
                    }}
                  >
                    <div style={{ fontWeight: activeTeamId === team.id ? 600 : 500, color: activeTeamId === team.id ? 'var(--primary)' : 'var(--ink)', marginBottom: '4px' }}>{team.name}</div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--ink-soft)' }}>成员: {team.memberCount} 人</div>
                  </div>
                ))}
              </div>

              <div style={{ borderTop: '1px solid var(--line)', paddingTop: '20px', marginTop: '10px' }}>
                <label style={labelStyle}>创建新团队</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input style={inputTheme} placeholder="团队名称..." value={newTeamName} onChange={e => setNewTeamName(e.target.value)} />
                  <button onClick={handleCreateTeam} style={{ background: 'var(--primary)', border: 'none', borderRadius: '8px', width: '40px', color: 'white', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center'}}><Plus size={18} /></button>
                </div>
              </div>
            </div>

            {/* 右侧团队内容：成员管理 */}
            <div style={{ flex: 1, ...cardStyle, display: 'flex', flexDirection: 'column', padding: '24px' }}>
              {activeTeamId ? (
                <>
                  {(() => {
                    const myMember = teamMembers.find((member) => member.userId === profile.id);
                    const myTeamRole = myMember?.role || "member";
                    const canManage = myTeamRole === "owner" || myTeamRole === "admin";
                    return (
                      <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', borderBottom: '1px solid var(--line)', paddingBottom: '16px' }}>
                    <h2 style={{ margin: 0, fontSize: '1.3rem' }}>{teams.find(t => t.id === activeTeamId)?.name} - 成员管理</h2>
                    <div style={{ display: 'flex', gap: '12px' }}>
                      <input style={{...inputTheme, width: '240px'}} placeholder="输入 User ID 邀请..." value={newMemberUserId} onChange={e => setNewMemberUserId(e.target.value)} />
                      <button onClick={handleAddMember} disabled={!canManage} style={{ background: 'var(--ink)', border: 'none', color: 'var(--bg-main)', padding: '0 16px', borderRadius: '10px', cursor: canManage ? 'pointer' : 'not-allowed', fontWeight: 500, opacity: canManage ? 1 : 0.6}}>添加成员</button>
                    </div>
                  </div>

                  <div style={{ flex: 1, overflowY: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--line)', color: 'var(--ink-soft)', fontSize: '0.85rem' }}>
                          <th style={{ padding: '12px 16px', fontWeight: 500 }}>成员</th>
                          <th style={{ padding: '12px 16px', fontWeight: 500 }}>账号 / ID</th>
                          <th style={{ padding: '12px 16px', fontWeight: 500 }}>角色</th>
                          <th style={{ padding: '12px 16px', fontWeight: 500 }}>加入时间</th>
                          <th style={{ padding: '12px 16px', fontWeight: 500, width: '100px', textAlign: 'right' }}>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {teamMembers.map(member => (
                          <tr key={member.id} style={{ borderBottom: '1px solid var(--line)' }}>
                            <td style={{ padding: '16px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'linear-gradient(135deg, var(--primary) 0%, #3b82f6 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 600, fontSize: '0.8rem' }}>
                                  {member.name.charAt(0).toUpperCase() || 'U'}
                                </div>
                                <div style={{ fontWeight: 500 }}>{member.name} {member.name === profile.name && <span style={{ fontSize: '0.75rem', background: 'var(--primary-alpha-10)', color: 'var(--primary)', padding: '2px 6px', borderRadius: '4px', marginLeft: '6px' }}>(我)</span>}</div>
                              </div>
                            </td>
                            <td style={{ padding: '16px', color: 'var(--ink-soft)', fontSize: '0.85rem', fontFamily: 'monospace' }}>{member.username}</td>
                            <td style={{ padding: '16px' }}>
                              <select 
                                value={member.role} 
                                onChange={e => { void handleUpdateMemberRole(member.id, e.target.value); }}
                                style={{ ...inputTheme, padding: '4px 8px', width: 'auto' }}
                                disabled={member.userId === profile.id || !canManage}
                              >
                                <option value="owner">所有者 (Owner)</option>
                                <option value="admin">管理员 (Admin)</option>
                                <option value="member">成员 (Member)</option>
                              </select>
                            </td>
                            <td style={{ padding: '16px', color: 'var(--ink-soft)', fontSize: '0.85rem' }}>{new Date(member.createdAt).toLocaleDateString()}</td>
                            <td style={{ padding: '16px', textAlign: 'right' }}>
                               {member.userId !== profile.id && (
                                 <button disabled={!canManage} onClick={() => handleRemoveMember(member.id)} style={{ background: 'none', border: 'none', color: '#ef4444', cursor: canManage ? 'pointer' : 'not-allowed', padding: '6px', borderRadius: '6px', opacity: canManage ? 1 : 0.6 }}>
                                   <Trash2 size={16} />
                                 </button>
                               )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    </div>
                      <div style={{ marginTop: '16px', borderTop: '1px solid var(--line)', paddingTop: '16px' }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: "10px" }}>
                        <div style={{ fontSize: '0.92rem', fontWeight: 600 }}>最近团队操作日志</div>
                        <div style={{ display: "flex", gap: 8 }}>
                          <button
                            onClick={() => { if (activeTeamId) void loadTeamAuditLogs(activeTeamId); }}
                            style={{ border: "1px solid var(--line)", background: "var(--panel)", borderRadius: 8, padding: "4px 10px", cursor: "pointer", fontSize: "0.8rem" }}
                          >
                            刷新
                          </button>
                          <button
                            onClick={exportTeamAuditCsv}
                            disabled={teamAuditLogs.length === 0}
                            style={{ border: "1px solid var(--line)", background: "var(--panel)", borderRadius: 8, padding: "4px 10px", cursor: teamAuditLogs.length === 0 ? "not-allowed" : "pointer", fontSize: "0.8rem", opacity: teamAuditLogs.length === 0 ? 0.6 : 1 }}
                          >
                            导出 CSV
                          </button>
                        </div>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 120px", gap: 8, marginBottom: 10 }}>
                        <input
                          style={{ ...inputTheme, padding: "6px 10px" }}
                          value={auditActorFilter}
                          onChange={(e) => setAuditActorFilter(e.target.value)}
                          placeholder="按操作者 ID 过滤"
                        />
                        <input
                          style={{ ...inputTheme, padding: "6px 10px" }}
                          value={auditActionPrefix}
                          onChange={(e) => setAuditActionPrefix(e.target.value)}
                          placeholder="动作前缀（如 team.member.）"
                        />
                        <select
                          style={{ ...inputTheme, padding: "6px 10px" }}
                          value={auditLimit}
                          onChange={(e) => setAuditLimit(Number(e.target.value) || 50)}
                        >
                          <option value={20}>最近 20 条</option>
                          <option value={50}>最近 50 条</option>
                          <option value={100}>最近 100 条</option>
                        </select>
                      </div>
                      {teamAuditLogs.length === 0 ? (
                        <div style={{ color: 'var(--ink-soft)', fontSize: '0.86rem' }}>暂无审计记录</div>
                      ) : (
                        <div style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          {teamAuditLogs.map((log) => (
                            <div key={log.id} style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '8px 10px', background: 'var(--panel)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', fontSize: '0.82rem' }}>
                                <strong>{log.action}</strong>
                                <span style={{ color: 'var(--ink-soft)' }}>{new Date(log.createdAt).toLocaleString()}</span>
                              </div>
                              <div style={{ fontSize: '0.8rem', color: 'var(--ink-soft)', marginTop: '4px' }}>
                                操作者: {log.actorId || "unknown"} | 目标: {log.targetType}:{log.targetId}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                        </>
                      );
                    })()}
                </>
              ) : (
                <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-soft)', gap: '16px' }}>
                  <Users size={48} opacity={0.5} />
                  <div>请在左侧选择一个团队以管理成员</div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, icon, label }: { active: boolean, onClick: () => void, icon: React.ReactNode, label: string }) {
  return (
    <button 
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px',
        border: 'none', borderRadius: '8px', cursor: 'pointer', transition: 'all 0.2s',
        fontSize: '0.9rem', fontWeight: active ? 600 : 500,
        background: active ? 'var(--bg-main)' : 'transparent',
        color: active ? 'var(--primary)' : 'var(--ink-soft)',
        boxShadow: active ? '0 2px 8px rgba(0,0,0,0.05)' : 'none'
      }}
    >
      {icon} {label}
    </button>
  );
}
