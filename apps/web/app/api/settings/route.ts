import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL = process.env.PLATFORM_API_URL || "http://localhost:8000";
const BUILTIN_MCP_NAMES = ["filesystem", "fetch", "playwright"] as const;

function normalizeMcpServers(raw: unknown): Array<Record<string, unknown>> {
  const input = Array.isArray(raw) ? raw : [];
  const normalized = input
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item) => {
      const name = String(item.name ?? item.id ?? "").trim();
      const command = String(item.command ?? "").trim();
      const args = Array.isArray(item.args) ? item.args.map((arg) => String(arg)) : [];
      const env = item.env && typeof item.env === "object" ? (item.env as Record<string, unknown>) : {};
      const enabled = typeof item.enabled === "boolean" ? item.enabled : true;
      const builtIn = BUILTIN_MCP_NAMES.includes(name as (typeof BUILTIN_MCP_NAMES)[number]);
      return {
        ...item,
        name,
        command,
        args,
        env,
        enabled,
        builtIn,
        source: builtIn ? "builtin" : String(item.source ?? "custom"),
      };
    })
    .filter((item) => item.name);

  for (const builtinName of BUILTIN_MCP_NAMES) {
    if (!normalized.find((item) => item.name === builtinName)) {
      normalized.unshift({
        name: builtinName,
        command: "",
        args: [],
        env: {},
        enabled: true,
        builtIn: true,
        source: "builtin",
      });
    }
  }
  return normalized;
}

async function getToken() {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value;
}

function authHeaders(token?: string) {
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function toFrontendSettings(raw: Record<string, unknown>) {
  const modelBaseUrl = String(raw.modelBaseUrl ?? raw.aiEndpoint ?? raw.ai_endpoint ?? "");
  const modelApiKey = String(raw.modelApiKey ?? raw.aiKey ?? raw.ai_key ?? "");
  const modelName = String(raw.modelName ?? raw.aiModel ?? raw.ai_model ?? "gpt-4o");
  const maxTokens = Number(raw.maxTokens ?? raw.aiMaxTokens ?? raw.ai_max_tokens ?? 4096);
  const temperature = Number(raw.temperature ?? raw.aiTemperature ?? raw.ai_temperature ?? 0.7);
  const mcpServers = Array.isArray(raw.mcpServers)
    ? raw.mcpServers
    : Array.isArray(raw.mcp_servers)
      ? raw.mcp_servers
      : [];
  const customRules = Array.isArray(raw.customRules)
    ? raw.customRules
    : Array.isArray(raw.custom_rules)
      ? raw.custom_rules
      : [];
  const systemPrompt = String(raw.systemPrompt ?? raw.aiSystemPrompt ?? raw.ai_system_prompt ?? "");
  const skillSearchPaths = Array.isArray(raw.skillSearchPaths)
    ? raw.skillSearchPaths
    : Array.isArray(raw.skill_search_paths)
      ? raw.skill_search_paths
      : [];
  const theme = String(raw.theme ?? "light");
  const normalizedRules = customRules.map((rule) => String(rule).trim()).filter(Boolean);

  return {
    theme,
    modelBaseUrl,
    modelApiKey,
    modelName,
    maxTokens: Number.isFinite(maxTokens) ? maxTokens : 4096,
    temperature: Number.isFinite(temperature) ? temperature : 0.7,
    systemPrompt,
    mcpServers: normalizeMcpServers(mcpServers),
    customRules: normalizedRules,
    customRulesText: normalizedRules.join("\n"),
    skillSearchPaths: skillSearchPaths.map((item) => String(item).trim()).filter(Boolean),
    // Keep legacy keys so existing backend consumers remain compatible.
    aiModel: modelName,
    aiEndpoint: modelBaseUrl,
    aiKey: modelApiKey,
    aiTemperature: Number.isFinite(temperature) ? temperature : 0.7,
    aiMaxTokens: Number.isFinite(maxTokens) ? maxTokens : 4096,
    aiSystemPrompt: systemPrompt,
  };
}

function toBackendSettings(raw: Record<string, unknown>) {
  const normalized = toFrontendSettings(raw);
  const parsedRules = String(raw.customRulesText ?? "")
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#") && !line.startsWith("//"))
    .map((line) => (line.startsWith("- ") ? line.slice(2).trim() : line))
    .filter(Boolean);
  const customRules = parsedRules.length > 0 ? parsedRules : normalized.customRules;
  return {
    theme: normalized.theme,
    modelBaseUrl: normalized.modelBaseUrl,
    modelApiKey: normalized.modelApiKey,
    modelName: normalized.modelName,
    maxTokens: normalized.maxTokens,
    temperature: normalized.temperature,
    systemPrompt: normalized.systemPrompt,
    mcpServers: normalized.mcpServers.map((server) => {
      const builtIn = !!server.builtIn || BUILTIN_MCP_NAMES.includes(String(server.name) as (typeof BUILTIN_MCP_NAMES)[number]);
      return {
        name: server.name,
        command: builtIn ? "" : server.command,
        args: builtIn ? [] : (Array.isArray(server.args) ? server.args : []),
        env: builtIn ? {} : (server.env && typeof server.env === "object" ? server.env : {}),
        enabled: typeof server.enabled === "boolean" ? server.enabled : true,
        builtIn,
        source: server.source ?? (builtIn ? "builtin" : "custom"),
        tools: Array.isArray((server as Record<string, unknown>).tools)
          ? ((server as Record<string, unknown>).tools as unknown[]).map((tool) => String(tool)).filter(Boolean)
          : [],
      };
    }),
    customRules,
    skillSearchPaths: normalized.skillSearchPaths,
    aiModel: normalized.aiModel,
    aiEndpoint: normalized.aiEndpoint,
    aiKey: normalized.aiKey,
    aiTemperature: normalized.aiTemperature,
    aiMaxTokens: normalized.aiMaxTokens,
    aiSystemPrompt: normalized.aiSystemPrompt,
    skill_search_paths: normalized.skillSearchPaths,
  };
}

export async function GET() {
  const token = await getToken();
  try {
    const res = await fetch(`${PLATFORM_API_URL}/settings`, {
      cache: "no-store",
      headers: authHeaders(token),
    });
    if (!res.ok) return NextResponse.json({ error: "Failed to fetch settings" }, { status: res.status });
    const data = (await res.json()) as Record<string, unknown>;
    return NextResponse.json(toFrontendSettings(data));
  } catch (error) {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}

export async function POST(req: Request) {
  const token = await getToken();
  try {
    const body = (await req.json()) as { settings?: Record<string, unknown> };
    const settings = toBackendSettings(body?.settings ?? {});
    const res = await fetch(`${PLATFORM_API_URL}/settings`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ settings }),
    });
    if (!res.ok) return NextResponse.json({ error: "Failed to update settings" }, { status: res.status });
    const data = (await res.json()) as Record<string, unknown>;
    return NextResponse.json(toFrontendSettings(data));
  } catch (error) {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
