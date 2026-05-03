"use client";

import { type ChangeEvent, type CSSProperties, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Download, Loader2, Play, Plus, Save, Trash2, Upload, Settings2, X, Pencil } from "lucide-react";
import { 
  listApiCollections, 
  createApiCollection, 
  updateApiCollection, 
  deleteApiCollection,
  listApiCollectionRequests,
  createApiRequest,
  updateApiRequest,
  deleteApiRequest,
  listApiCollectionEnvironments,
  createApiEnvironment,
  updateApiEnvironment,
  deleteApiEnvironment,
  listApiRuns,
  listProjects,
  sendApiRequest,
  sendBatchApiRequest,
  runApiCollection,
  importOpenApi as importOpenApiLib,
  exportPostman as exportPostmanLib,
  fetchJson,
  createCase
} from "../lib/api";
import type { 
  Project, 
  ApiCollection, 
  ApiEnvironment, 
  ApiRequest, 
  ApiRun, 
  AssertionType, 
  AssertionDraft, 
  ApiBatchRunResult 
} from "../lib/api";

type EditableKvRow = {
  id: string;
  key: string;
  value: string;
  enabled: boolean;
  description: string;
};
type ApiKeyValueItem = {
  key: string;
  value: string;
  enabled: boolean;
  description: string;
};
type OpenApiImportResult = {
  collectionId: string;
  created: number;
  requestIds: string[];
  warnings: string[];
};
type PostmanExportResult = {
  collection: Record<string, unknown>;
  environments: Array<Record<string, unknown>>;
};

function parseJsonArray(text: string, fieldName: string): Array<Record<string, unknown>> {
  const value = JSON.parse(text);
  if (!Array.isArray(value)) throw new Error(`${fieldName} 必须是 JSON 数组`);
  return value;
}

function parseJsonObject(text: string, fieldName: string): Record<string, string> {
  const value = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${fieldName} 必须是 JSON 对象`);
  }
  const result: Record<string, string> = {};
  for (const [key, val] of Object.entries(value)) {
    const normalizedKey = String(key).trim();
    if (!normalizedKey) continue;
    result[normalizedKey] = String(val ?? "");
  }
  return result;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function getResponseHeader(headers: Record<string, unknown> | undefined, name: string): string {
  if (!headers) return "";
  const expected = name.toLowerCase();
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === expected) return String(value ?? "");
  }
  return "";
}

function createKvRow(seed?: Partial<EditableKvRow>): EditableKvRow {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    key: seed?.key || "",
    value: seed?.value || "",
    enabled: seed?.enabled ?? true,
    description: seed?.description || "",
  };
}

function toEditableRows(raw: Array<{ key: string; value: string; enabled: boolean; description: string }>): EditableKvRow[] {
  if (!Array.isArray(raw) || raw.length === 0) return [createKvRow()];
  return raw.map((item) =>
    createKvRow({
      key: item.key,
      value: item.value,
      enabled: item.enabled,
      description: item.description,
    }),
  );
}

function fromEditableRows(rows: EditableKvRow[]): ApiKeyValueItem[] {
  return rows
    .map((item) => ({
      key: item.key.trim(),
      value: item.value,
      enabled: item.enabled,
      description: item.description,
    }))
    .filter((item) => item.key || item.value || item.description);
}

function variablesToRows(variables: Record<string, string>): EditableKvRow[] {
  const entries = Object.entries(variables || {});
  if (entries.length === 0) return [createKvRow()];
  return entries.map(([key, value]) =>
    createKvRow({
      key,
      value: String(value ?? ""),
      enabled: true,
      description: "",
    }),
  );
}

function rowsToVariables(rows: EditableKvRow[], fieldName: string): Record<string, string> {
  const normalized = fromEditableRows(rows);
  const result: Record<string, string> = {};
  for (const item of normalized) {
    if (!item.enabled) continue;
    const key = String(item.key || "").trim();
    if (!key) continue;
    if (Object.prototype.hasOwnProperty.call(result, key)) {
      throw new Error(`${fieldName} 存在重复变量名: ${key}`);
    }
    result[key] = String(item.value ?? "");
  }
  return result;
}

function toAssertionDrafts(raw: Array<Record<string, unknown>>): AssertionDraft[] {
  const result: AssertionDraft[] = [];
  for (const item of raw) {
    const type = String(item.type || "").trim() as AssertionType;
    if (
      ![
        "status_eq",
        "status_range",
        "json_path_eq",
        "json_path_exists",
        "json_path_contains",
        "header_contains",
        "header_eq",
        "body_contains",
        "response_time_lt",
      ].includes(type)
    ) {
      continue;
    }
    result.push({
      type,
      name: String(item.name || ""),
      expected:
        typeof item.expected === "number" || typeof item.expected === "string"
          ? item.expected
          : undefined,
      min: typeof item.min === "number" ? item.min : undefined,
      max: typeof item.max === "number" ? item.max : undefined,
      path: typeof item.path === "string" ? item.path : "",
      expectedValue:
        Object.prototype.hasOwnProperty.call(item, "expected")
          ? JSON.stringify(item.expected ?? "", null, 0)
          : "",
      key: typeof item.key === "string" ? item.key : "",
      contains: typeof item.contains === "string" ? item.contains : "",
      expectedMs: typeof item.expectedMs === "number" ? item.expectedMs : undefined,
    });
  }
  return result;
}

function fromAssertionDrafts(items: AssertionDraft[]): Array<Record<string, unknown>> {
  return items.map((item) => {
    if (item.type === "status_eq") {
      return {
        type: "status_eq",
        name: item.name || "状态码断言",
        expected:
          typeof item.expected === "number"
            ? item.expected
            : Number(item.expected || 200),
      };
    }
    if (item.type === "status_range") {
      return {
        type: "status_range",
        name: item.name || "状态码区间断言",
        min: typeof item.min === "number" ? item.min : 200,
        max: typeof item.max === "number" ? item.max : 299,
      };
    }
    if (item.type === "json_path_eq") {
      let expected: unknown = "";
      const rawExpected = String(item.expectedValue || "");
      if (rawExpected.trim()) {
        try {
          expected = JSON.parse(rawExpected);
        } catch {
          expected = rawExpected;
        }
      }
      return {
        type: "json_path_eq",
        name: item.name || "JSON 路径断言",
        path: item.path || "",
        expected,
      };
    }
    if (item.type === "json_path_exists") {
      return {
        type: "json_path_exists",
        name: item.name || "JSON 路径存在断言",
        path: item.path || "",
      };
    }
    if (item.type === "json_path_contains") {
      return {
        type: "json_path_contains",
        name: item.name || "JSON 路径包含断言",
        path: item.path || "",
        contains: item.contains || "",
      };
    }
    if (item.type === "header_contains") {
      return {
        type: "header_contains",
        name: item.name || "Header 包含断言",
        key: item.key || "content-type",
        contains: item.contains || "",
      };
    }
    if (item.type === "header_eq") {
      return {
        type: "header_eq",
        name: item.name || "Header 等于断言",
        key: item.key || "content-type",
        expected: item.expectedValue || "",
      };
    }
    if (item.type === "body_contains") {
      return {
        type: "body_contains",
        name: item.name || "Body 包含断言",
        contains: item.contains || "",
      };
    }
    return {
      type: "response_time_lt",
      name: item.name || "响应时间断言",
      expectedMs: typeof item.expectedMs === "number" ? item.expectedMs : 1000,
    };
  });
}

export function ApiTestView({
  initialProjects = [],
  initialProjectId = "",
  initialCollections = [],
  initialCollectionId = "",
  initialRequests = [],
  initialRequestId = "",
  initialEnvironments = [],
  initialEnvironmentId = "",
}: {
  initialProjects?: Project[];
  initialProjectId?: string;
  initialCollections?: ApiCollection[];
  initialCollectionId?: string;
  initialRequests?: ApiRequest[];
  initialRequestId?: string;
  initialEnvironments?: ApiEnvironment[];
  initialEnvironmentId?: string;
}) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const sendLockRef = useRef(false);
  const batchSendLockRef = useRef(false);
  const groupRunLockRef = useRef(false);
  const initialProjectFetchSkippedRef = useRef(
    initialProjects.length > 0 && initialProjectId.length > 0,
  );
  const initialCollectionFetchSkippedRef = useRef(initialCollectionId.length > 0);
  const [projects, setProjects] = useState<Project[]>(initialProjects);
  const [projectId, setProjectId] = useState(initialProjectId);
  const [collections, setCollections] = useState<ApiCollection[]>(initialCollections);
  const [collectionId, setCollectionId] = useState(initialCollectionId);
  const [requests, setRequests] = useState<ApiRequest[]>(initialRequests);
  const [requestId, setRequestId] = useState(initialRequestId);
  const [environments, setEnvironments] = useState<ApiEnvironment[]>(initialEnvironments);
  const [environmentId, setEnvironmentId] = useState(initialEnvironmentId);
  const [run, setRun] = useState<ApiRun | null>(null);
  const [notice, setNotice] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isBatchSending, setIsBatchSending] = useState(false);
  const [isGroupRunning, setIsGroupRunning] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isSavingCollection, setIsSavingCollection] = useState(false);
  const [isSavingEnvironment, setIsSavingEnvironment] = useState(false);
  const [isDeletingEnvironment, setIsDeletingEnvironment] = useState(false);

  const [showCreateCollectionModal, setShowCreateCollectionModal] = useState(false);
  const [showCreateRequestModal, setShowCreateRequestModal] = useState(false);
  const [showEnvironmentModal, setShowEnvironmentModal] = useState(false);
  const [showDeleteRequestModal, setShowDeleteRequestModal] = useState(false);
  const [showSaveAsCaseModal, setShowSaveAsCaseModal] = useState(false);
  const [saveAsCaseTitle, setSaveAsCaseTitle] = useState("");
  const [isSavingAsCase, setIsSavingAsCase] = useState(false);
  const [showAddToCaseModal, setShowAddToCaseModal] = useState(false);
  const [existingCases, setExistingCases] = useState<Array<{ id: string; title: string; stepsCount: number }>>([]);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [isLoadingCases, setIsLoadingCases] = useState(false);
  const [isAddingToCase, setIsAddingToCase] = useState(false);

  const [collectionCreateName, setCollectionCreateName] = useState("默认集合");
  const [collectionCreateDescription, setCollectionCreateDescription] = useState("");
  const [requestCreateName, setRequestCreateName] = useState("新接口");

  const [envEditingId, setEnvEditingId] = useState<string | null>(null);
  const [envDraftName, setEnvDraftName] = useState("");
  const [envDraftVariablesText, setEnvDraftVariablesText] = useState("{}");
  const [envDraftIsDefault, setEnvDraftIsDefault] = useState(false);

  const [name, setName] = useState("");
  const [method, setMethod] = useState<ApiRequest["method"]>("GET");
  const [url, setUrl] = useState("");
  const [groupName, setGroupName] = useState("default");
  const [tagsText, setTagsText] = useState("");
  const [selectedGroupFilter, setSelectedGroupFilter] = useState("all");
  const [selectedTagFilter, setSelectedTagFilter] = useState("all");
  const [queryRows, setQueryRows] = useState<EditableKvRow[]>([createKvRow()]);
  const [headerRows, setHeaderRows] = useState<EditableKvRow[]>([createKvRow()]);
  const [bodyMode, setBodyMode] = useState<ApiRequest["bodyMode"]>("none");
  const [bodyRaw, setBodyRaw] = useState("");
  const [bodyFormRows, setBodyFormRows] = useState<EditableKvRow[]>([createKvRow()]);
  const [assertions, setAssertions] = useState<AssertionDraft[]>([]);
  const [preScriptText, setPreScriptText] = useState("");
  const [testScriptText, setTestScriptText] = useState("");
  const [activePanel, setActivePanel] = useState<"request" | "assertions" | "scripts" | "variables">("request");
  const [timeoutMs, setTimeoutMs] = useState(5000);
  const [verifySsl, setVerifySsl] = useState(true);
  const [clientCertPem, setClientCertPem] = useState("");
  const [clientKeyPem, setClientKeyPem] = useState("");
  const [clientCertName, setClientCertName] = useState("");
  const [clientKeyName, setClientKeyName] = useState("");
  const [autoSaveBeforeSend, setAutoSaveBeforeSend] = useState(true);
  const [variableSetsText, setVariableSetsText] = useState('[{"name":"默认数据","variables":{}}]');
  const [collectionVarRows, setCollectionVarRows] = useState<EditableKvRow[]>(
    variablesToRows(
      initialCollections.find((item) => item.id === initialCollectionId)?.variables ?? {},
    ),
  );
  const [runtimeVarsText, setRuntimeVarsText] = useState("{}");
  const [isSequential, setIsSequential] = useState(true);
  const [batchResult, setBatchResult] = useState<ApiBatchRunResult | null>(null);
  const certFileInputRef = useRef<HTMLInputElement | null>(null);
  const keyFileInputRef = useRef<HTMLInputElement | null>(null);

  const activeCollection = useMemo(
    () => collections.find((item) => item.id === collectionId) ?? null,
    [collectionId, collections],
  );
  const groupOptions = useMemo(() => {
    const values = new Set<string>();
    for (const item of requests) {
      values.add(item.groupName || "default");
    }
    return ["all", ...Array.from(values).sort()];
  }, [requests]);
  const tagOptions = useMemo(() => {
    const values = new Set<string>();
    for (const item of requests) {
      for (const tag of item.tags || []) {
        const normalized = String(tag || "").trim();
        if (normalized) {
          values.add(normalized);
        }
      }
    }
    return ["all", ...Array.from(values).sort()];
  }, [requests]);
  const filteredRequests = useMemo(() => {
    return requests.filter((item) => {
      if (selectedGroupFilter !== "all" && (item.groupName || "default") !== selectedGroupFilter) {
        return false;
      }
      if (selectedTagFilter !== "all") {
        const tags = (item.tags || []).map((tag) => String(tag || "").trim());
        if (!tags.includes(selectedTagFilter)) {
          return false;
        }
      }
      return true;
    });
  }, [requests, selectedGroupFilter, selectedTagFilter]);
  const selectedEnvironment = useMemo(
    () => environments.find((item) => item.id === environmentId) ?? null,
    [environments, environmentId],
  );
  const selectedRequest = useMemo(
    () => requests.find((item) => item.id === requestId) ?? null,
    [requestId, requests],
  );
  const resolvedVariablesPreview = useMemo(() => {
    let runtime: Record<string, string> = {};
    try {
      runtime = parseJsonObject(runtimeVarsText, "运行时变量");
    } catch {
      runtime = {};
    }
    const merged = {
      ...(activeCollection?.variables || {}),
      ...(selectedEnvironment?.variables || {}),
      ...runtime,
    };
    return JSON.stringify(merged, null, 2);
  }, [activeCollection, runtimeVarsText, selectedEnvironment]);
  const tlsConfig = useMemo(() => {
    const certPem = clientCertPem.trim();
    const keyPem = clientKeyPem.trim();
    if (!certPem && !keyPem) return null;
    return {
      ...(certPem ? { certPem } : {}),
      ...(keyPem ? { keyPem } : {}),
      ...(clientCertName ? { certName: clientCertName } : {}),
      ...(clientKeyName ? { keyName: clientKeyName } : {}),
    };
  }, [clientCertName, clientCertPem, clientKeyName, clientKeyPem]);

  useEffect(() => {
    if (!groupOptions.includes(selectedGroupFilter)) {
      setSelectedGroupFilter("all");
    }
  }, [groupOptions, selectedGroupFilter]);
  useEffect(() => {
    if (!tagOptions.includes(selectedTagFilter)) {
      setSelectedTagFilter("all");
    }
  }, [tagOptions, selectedTagFilter]);

  useEffect(() => {
    if (initialProjects.length > 0) {
      return;
    }
    void (async () => {
      try {
        const rows = await listProjects();
        setProjects(rows);
        setProjectId((current) => current || rows[0]?.id || "");
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "加载项目失败");
      }
    })();
  }, [initialProjects.length]);

  useEffect(() => {
    if (!projectId) {
      setCollections([]);
      setCollectionId("");
      return;
    }
    if (initialProjectFetchSkippedRef.current && projectId === initialProjectId) {
      initialProjectFetchSkippedRef.current = false;
      return;
    }
    void (async () => {
      try {
        const rows = await listApiCollections(projectId);
        setCollections(rows);
        setCollectionId((current) => current || rows[0]?.id || "");
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "加载集合失败");
      }
    })();
  }, [projectId]);

  useEffect(() => {
    if (!collectionId) {
      setRequests([]);
      setRequestId("");
      setEnvironments([]);
      setEnvironmentId("");
      setCollectionVarRows([createKvRow()]);
      return;
    }
    if (initialCollectionFetchSkippedRef.current && collectionId === initialCollectionId) {
      initialCollectionFetchSkippedRef.current = false;
      return;
    }
    void (async () => {
      try {
        const [requestRows, envRows] = await Promise.all([
          listApiCollectionRequests(collectionId),
          listApiCollectionEnvironments(collectionId),
        ]);
        setRequests(requestRows);
        setRequestId((current) => current || requestRows[0]?.id || "");
        setEnvironments(envRows);
        const defaultEnv = envRows.find((item) => item.isDefault) ?? envRows[0];
        setEnvironmentId(defaultEnv?.id ?? "");
        const currentCollection = collections.find((item) => item.id === collectionId);
        setCollectionVarRows(variablesToRows(currentCollection?.variables ?? {}));
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "加载请求列表失败");
      }
    })();
  }, [collectionId, collections]);

  useEffect(() => {
    const current = requests.find((item) => item.id === requestId);
    if (!current) return;
    setName(current.name);
    setGroupName(current.groupName || "default");
    setTagsText((current.tags || []).join(", "));
    setMethod(current.method);
    setUrl(current.url);
    setQueryRows(toEditableRows(current.query));
    setHeaderRows(toEditableRows(current.headers));
    setBodyMode(current.bodyMode);
    setBodyRaw(current.bodyRaw);
    setBodyFormRows(toEditableRows(current.bodyForm));
    setAssertions(toAssertionDrafts(current.tests));
    setPreScriptText(current.preScript || "");
    setTestScriptText(current.testScript || "");
    setVerifySsl(typeof current.verifySsl === "boolean" ? current.verifySsl : true);
    setClientCertPem(current.tls?.certPem || "");
    setClientKeyPem(current.tls?.keyPem || "");
    setClientCertName(current.tls?.certName || "");
    setClientKeyName(current.tls?.keyName || "");
  }, [requestId, requests]);

  const onPemFileChange = async (
    event: ChangeEvent<HTMLInputElement>,
    onContent: (content: string) => void,
    onName: (name: string) => void,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    onContent(text);
    onName(file.name);
    event.target.value = "";
  };

  const refreshCollections = async (targetProjectId: string) => {
    const rows = await listApiCollections(targetProjectId);
    setCollections(rows);
    return rows;
  };

  const refreshRequestsAndEnvironments = async (targetCollectionId: string) => {
    const [requestRows, envRows] = await Promise.all([
      listApiCollectionRequests(targetCollectionId),
      listApiCollectionEnvironments(targetCollectionId),
    ]);
    setRequests(requestRows);
    setRequestId((current) => current || requestRows[0]?.id || "");
    setEnvironments(envRows);
    const defaultEnv = envRows.find((item) => item.isDefault) ?? envRows[0];
    setEnvironmentId(defaultEnv?.id ?? "");
    return { requestRows, envRows };
  };

  const submitCreateCollection = async () => {
    if (!projectId) return;
    const nameText = collectionCreateName.trim();
    if (!nameText) {
      setNotice("集合名称不能为空");
      return;
    }
    try {
      await createApiCollection({
        projectId,
        name: nameText,
        description: collectionCreateDescription.trim(),
        variables: {},
      });
      const rows = await refreshCollections(projectId);
      const created = rows.find((item) => item.name === nameText) ?? rows[0];
      setCollectionId(created?.id ?? "");
      setShowCreateCollectionModal(false);
      setNotice("集合创建成功");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建集合失败");
    }
  };

  const submitCreateRequest = async () => {
    if (!collectionId) return;
    const nameText = requestCreateName.trim();
    if (!nameText) {
      setNotice("请求名称不能为空");
      return;
    }
    try {
      await createApiRequest({
        collectionId,
        name: nameText,
        groupName: "default",
        tags: [],
        method: "GET",
        url: "{{baseUrl}}/health",
        query: [],
        headers: [],
        bodyMode: "none",
        bodyRaw: "",
        bodyForm: [],
        authType: "none",
        auth: {},
        verifySsl: true,
        tls: {},
        tests: [{ type: "status_eq", name: "状态码 200", expected: 200 }],
      });
      const { requestRows } = await refreshRequestsAndEnvironments(collectionId);
      const created = requestRows.find((item) => item.name === nameText) ?? requestRows[0];
      setRequestId(created?.id ?? "");
      setShowCreateRequestModal(false);
      setNotice("请求创建成功");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建请求失败");
    }
  };

  const openEnvironmentModal = () => {
    if (!collectionId) {
      setNotice("请先选择集合");
      return;
    }
    if (environments.length > 0) {
      const current = environments.find((item) => item.id === environmentId) ?? environments[0];
      setEnvEditingId(current.id);
      setEnvDraftName(current.name);
      setEnvDraftVariablesText(JSON.stringify(current.variables, null, 2));
      setEnvDraftIsDefault(current.isDefault);
    } else {
      setEnvEditingId(null);
      setEnvDraftName("Dev");
      setEnvDraftVariablesText("{}");
      setEnvDraftIsDefault(true);
    }
    setShowEnvironmentModal(true);
  };

  const startCreateEnvironment = () => {
    setEnvEditingId(null);
    setEnvDraftName("Dev");
    setEnvDraftVariablesText("{}");
    setEnvDraftIsDefault(environments.length === 0);
  };

  const startEditEnvironment = (env: ApiEnvironment) => {
    setEnvEditingId(env.id);
    setEnvDraftName(env.name);
    setEnvDraftVariablesText(JSON.stringify(env.variables, null, 2));
    setEnvDraftIsDefault(env.isDefault);
  };

  const saveEnvironment = async () => {
    if (!collectionId) return;
    const nameText = envDraftName.trim();
    if (!nameText) {
      setNotice("环境名称不能为空");
      return;
    }
    setIsSavingEnvironment(true);
    try {
      const variables = parseJsonObject(envDraftVariablesText, "环境变量");
      if (envEditingId) {
        await updateApiEnvironment(envEditingId, {
          name: nameText,
          variables,
          isDefault: envDraftIsDefault,
        });
      } else {
        await createApiEnvironment({
          collectionId,
          name: nameText,
          variables,
          isDefault: envDraftIsDefault,
        });
      }
      const { envRows } = await refreshRequestsAndEnvironments(collectionId);
      const selected = envRows.find((item: ApiEnvironment) => item.name === nameText) ?? envRows[0];
      if (selected) {
        setEnvironmentId(selected.id);
        startEditEnvironment(selected);
      }
      setNotice(envEditingId ? "环境已更新" : "环境已创建");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存环境失败");
    } finally {
      setIsSavingEnvironment(false);
    }
  };

  const removeEnvironment = async (envId: string) => {
    if (!collectionId) return;
    setIsDeletingEnvironment(true);
    try {
      await deleteApiEnvironment(envId);
      const { envRows } = await refreshRequestsAndEnvironments(collectionId);
      if (envRows.length > 0) {
        const selected = envRows[0];
        setEnvironmentId(selected.id);
        startEditEnvironment(selected);
      } else {
        startCreateEnvironment();
      }
      setNotice("环境已删除");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除环境失败");
    } finally {
      setIsDeletingEnvironment(false);
    }
  };

  const saveCollectionVariables = async () => {
    if (!collectionId) return;
    setIsSavingCollection(true);
    try {
      const variables = rowsToVariables(collectionVarRows, "集合变量");
      const updated = await updateApiCollection(collectionId, { variables });
      setCollections((prev) => prev.map((item: ApiCollection) => (item.id === collectionId ? updated : item)));
      setCollectionVarRows(variablesToRows(updated.variables));
      setNotice("集合变量已保存");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存集合变量失败");
    } finally {
      setIsSavingCollection(false);
    }
  };

  const buildRequestDraftPayload = () => {
    const query = fromEditableRows(queryRows);
    const headers = fromEditableRows(headerRows);
    const bodyForm = fromEditableRows(bodyFormRows);
    const tests = fromAssertionDrafts(assertions);
    const tags = tagsText
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return {
      name,
      groupName: groupName.trim() || "default",
      tags,
      method,
      url,
      query,
      headers,
      bodyMode,
      bodyRaw,
      bodyForm,
      verifySsl,
      tls: tlsConfig || {},
      tests,
      preScript: preScriptText,
      testScript: testScriptText,
    };
  };

  const isDraftChanged = (draft: ReturnType<typeof buildRequestDraftPayload>) => {
    if (!selectedRequest) return true;
    const current = {
      name: selectedRequest.name,
      groupName: selectedRequest.groupName || "default",
      tags: selectedRequest.tags || [],
      method: selectedRequest.method,
      url: selectedRequest.url,
      query: selectedRequest.query || [],
      headers: selectedRequest.headers || [],
      bodyMode: selectedRequest.bodyMode,
      bodyRaw: selectedRequest.bodyRaw || "",
      bodyForm: selectedRequest.bodyForm || [],
      verifySsl: typeof selectedRequest.verifySsl === "boolean" ? selectedRequest.verifySsl : true,
      tls: selectedRequest.tls || {},
      tests: selectedRequest.tests || [],
      preScript: selectedRequest.preScript || "",
      testScript: selectedRequest.testScript || "",
    };
    return JSON.stringify(current) !== JSON.stringify(draft);
  };

  const persistRequestDraft = async (draft: ReturnType<typeof buildRequestDraftPayload>) => {
    if (!requestId) return null;
    const updated = await updateApiRequest(requestId, draft);
    setRequests((prev) => prev.map((item: ApiRequest) => (item.id === updated.id ? updated : item)));
    return updated;
  };

  const saveRequest = async () => {
    if (!requestId) return;
    setIsSaving(true);
    try {
      const draft = buildRequestDraftPayload();
      await persistRequestDraft(draft);
      setNotice("请求保存成功");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  const openSaveAsCaseModal = () => {
    if (!selectedRequest) return;
    setSaveAsCaseTitle(selectedRequest.name || "API 测试用例");
    setShowSaveAsCaseModal(true);
  };

  const saveAsTestCase = async () => {
    if (!requestId || !projectId) return;
    setIsSavingAsCase(true);
    try {
      const draft = buildRequestDraftPayload();
      const caseData = {
        projectId,
        specId: "",
        kind: "api",
        title: saveAsCaseTitle.trim() || selectedRequest?.name || "API 测试用例",
        objective: `API 测试: ${draft.method} ${draft.url}`,
        steps: [],
        assertionHints: (draft.tests || []).map((t: Record<string, unknown>) => String(t.name || "")),
        payload: {
          requestId,
          method: draft.method,
          url: draft.url,
          query: draft.query,
          headers: draft.headers,
          bodyMode: draft.bodyMode,
          bodyRaw: draft.bodyRaw,
          bodyForm: draft.bodyForm,
          verifySsl: draft.verifySsl,
          tls: draft.tls,
          tests: draft.tests,
          preScript: draft.preScript,
          testScript: draft.testScript,
          environmentId: environmentId || null,
        },
      };
      await createCase(caseData);
      setNotice("已保存为测试用例");
      setShowSaveAsCaseModal(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存为测试用例失败");
    } finally {
      setIsSavingAsCase(false);
    }
  };

  const openAddToCaseModal = async () => {
    if (!projectId) return;
    setIsLoadingCases(true);
    setShowAddToCaseModal(true);
    try {
      const result = await fetchJson<{ items: Array<{ id: string; title: string; payload: Record<string, unknown> }> }>(
        `/cases?projectId=${projectId}&kind=api&pageSize=100`
      );
      const cases = (result.items || []).map((item) => ({
        id: item.id,
        title: item.title,
        stepsCount: Array.isArray(item.payload?.apiSteps) ? item.payload.apiSteps.length : 0,
      }));
      setExistingCases(cases);
      setSelectedCaseId(cases[0]?.id ?? "");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "加载测试用例失败");
    } finally {
      setIsLoadingCases(false);
    }
  };

  const addToExistingCase = async () => {
    if (!selectedCaseId || !requestId) return;
    setIsAddingToCase(true);
    try {
      const draft = buildRequestDraftPayload();
      const caseResult = await fetchJson<{ payload: Record<string, unknown> }>(`/cases/${selectedCaseId}`);
      const existingPayload = caseResult.payload || {};
      const existingSteps: Array<Record<string, unknown>> = Array.isArray(existingPayload.apiSteps)
        ? existingPayload.apiSteps
        : [];
      const newStep = {
        requestId,
        name: draft.name,
        method: draft.method,
        url: draft.url,
        query: draft.query,
        headers: draft.headers,
        bodyMode: draft.bodyMode,
        bodyRaw: draft.bodyRaw,
        bodyForm: draft.bodyForm,
        verifySsl: draft.verifySsl,
        tls: draft.tls,
        tests: draft.tests,
        preScript: draft.preScript,
        testScript: draft.testScript,
        environmentId: environmentId || null,
      };
      const updatedPayload = {
        ...existingPayload,
        apiSteps: [...existingSteps, newStep],
      };
      await fetchJson(`/cases/${selectedCaseId}`, {
        method: "PATCH",
        body: JSON.stringify({ payload: updatedPayload }),
      });
      setNotice("已添加到测试用例");
      setShowAddToCaseModal(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "添加到测试用例失败");
    } finally {
      setIsAddingToCase(false);
    }
  };

  const refreshLatestRunForRequest = async (targetRequestId: string) => {
    const rows = await listApiRuns({ requestId: targetRequestId, limit: 1 });
    if (rows.length > 0) {
      setRun(rows[0]);
    }
  };

  const confirmDeleteRequest = async () => {
    if (!requestId) return;
    setIsDeleting(true);
    try {
      await deleteApiRequest(requestId);
      const rows = await listApiCollectionRequests(collectionId);
      setRequests(rows);
      setRequestId(rows[0]?.id ?? "");
      setShowDeleteRequestModal(false);
      setNotice("请求已删除");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除失败");
    } finally {
      setIsDeleting(false);
    }
  };

  const sendRequest = async () => {
    if (!requestId) return;
    if (sendLockRef.current) return;
    sendLockRef.current = true;
    setIsSending(true);
    setBatchResult(null);
    setRun(null);
    setNotice("请求发送中...");
    try {
      const draft = buildRequestDraftPayload();
      if (autoSaveBeforeSend && isDraftChanged(draft)) {
        await persistRequestDraft(draft);
      }
      const runtimeVariables = parseJsonObject(runtimeVarsText, "运行时变量");
      const data = await sendApiRequest(requestId, {
        environmentId: environmentId || null,
        variables: runtimeVariables,
        timeoutMs,
        verifySsl,
        tls: tlsConfig,
      });
      setRun(data);
      try {
        await refreshLatestRunForRequest(requestId);
      } catch {
        // fall back to immediate run payload
      }
      setNotice(data.success ? "请求执行成功" : "请求执行失败，请查看响应详情");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "发送失败");
    } finally {
      setIsSending(false);
      sendLockRef.current = false;
    }
  };

  const sendBatchRequest = async () => {
    if (!requestId) return;
    if (batchSendLockRef.current) return;
    batchSendLockRef.current = true;
    setIsBatchSending(true);
    setNotice("参数化执行中...");
    try {
      const parsed = JSON.parse(variableSetsText);
      if (!Array.isArray(parsed) || parsed.length === 0) {
        throw new Error("变量数据集必须是非空 JSON 数组");
      }
      const variableSets = parsed.map((item, index) => {
        if (!item || typeof item !== "object") {
          throw new Error(`第 ${index + 1} 个变量集不是对象`);
        }
        const raw = item as { name?: unknown; variables?: unknown };
        const normalizedVariables: Record<string, string> = {};
        if (raw.variables && typeof raw.variables === "object" && !Array.isArray(raw.variables)) {
          for (const [key, value] of Object.entries(raw.variables as Record<string, unknown>)) {
            const normalizedKey = String(key).trim();
            if (!normalizedKey) continue;
            normalizedVariables[normalizedKey] = String(value ?? "");
          }
        }
        return {
          name: typeof raw.name === "string" ? raw.name : `dataset-${index + 1}`,
          variables: normalizedVariables,
        };
      });
      const result = await sendBatchApiRequest(requestId, {
        environmentId: environmentId || null,
        timeoutMs,
        verifySsl,
        tls: tlsConfig,
        variableSets,
      });
      setBatchResult(result);
      setNotice(`参数化执行完成：通过 ${result.passed}/${result.total}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "参数化执行失败");
    } finally {
      setIsBatchSending(false);
      batchSendLockRef.current = false;
    }
  };

  const runSelectedGroup = async () => {
    if (!collectionId) return;
    if (groupRunLockRef.current) return;
    if (filteredRequests.length === 0) {
      setNotice("当前筛选条件下没有可执行的请求");
      return;
    }
    groupRunLockRef.current = true;
    setIsGroupRunning(true);
    setNotice("筛选批跑执行中...");
    try {
      const runtimeVariables = parseJsonObject(runtimeVarsText, "运行时变量");
      const payload: Record<string, unknown> = {
        environmentId: environmentId || null,
        variables: runtimeVariables,
        timeoutMs,
        verifySsl,
        tls: tlsConfig,
        sequential: isSequential,
      };
      if (selectedGroupFilter !== "all") {
        payload.groupName = selectedGroupFilter;
      }
      if (selectedTagFilter !== "all") {
        payload.requestIds = filteredRequests.map((item: ApiRequest) => item.id);
      }
      const result = await runApiCollection(collectionId, payload);
      const scopeLabel =
        selectedGroupFilter === "all" && selectedTagFilter === "all"
          ? "全部请求"
          : `筛选结果（分组=${selectedGroupFilter === "all" ? "全部" : selectedGroupFilter}，标签=${selectedTagFilter === "all" ? "全部" : selectedTagFilter}）`;
      setNotice(`${scopeLabel}批跑完成：共 ${result.total}，通过 ${result.passed}，失败 ${result.failed}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "筛选批跑失败");
    } finally {
      setIsGroupRunning(false);
      groupRunLockRef.current = false;
    }
  };

  const triggerImport = () => {
    if (!collectionId) {
      setNotice("请先选择一个集合");
      return;
    }
    fileRef.current?.click();
  };

  const importOpenApi = async (file: File) => {
    if (!collectionId) return;
    setIsImporting(true);
    try {
      const result = await importOpenApiLib(collectionId, file);
      const rows = await listApiCollectionRequests(collectionId);
      setRequests(rows);
      setRequestId(rows[0]?.id ?? "");
      const warningText = result.warnings.length
        ? `，警告 ${result.warnings.length} 条`
        : "";
      setNotice(`导入完成，新增 ${result.created} 个请求${warningText}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "导入失败");
    } finally {
      setIsImporting(false);
      if (fileRef.current) {
        fileRef.current.value = "";
      }
    }
  };

  const exportPostman = async () => {
    if (!collectionId) return;
    setIsExporting(true);
    try {
      const payload = await exportPostmanLib(collectionId);
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const fileName = `${activeCollection?.name || "api-collection"}-postman.json`;
      const urlObject = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = urlObject;
      anchor.download = fileName;
      anchor.click();
      URL.revokeObjectURL(urlObject);
      setNotice("Postman 导出成功");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "导出失败");
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div style={pageStyle}>
      <input
        ref={fileRef}
        type="file"
        accept=".json,.yaml,.yml"
        style={{ display: "none" }}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void importOpenApi(file);
        }}
      />

      <aside style={sidebarStyle}>
        <div style={panelTitleStyle}>接口集合</div>
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)} style={fieldStyle}>
          <option value="">选择项目</option>
          {projects.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>

        <div style={rowStyle}>
          <button
            style={btnStyle}
            onClick={() => {
              setCollectionCreateName("默认集合");
              setCollectionCreateDescription("");
              setShowCreateCollectionModal(true);
            }}
          >
            <Plus size={14} />
            新建集合
          </button>
          <button style={btnStyle} onClick={triggerImport} disabled={isImporting}>
            {isImporting ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            导入 OpenAPI
          </button>
        </div>

        <div style={rowStyle}>
          <button
            style={btnStyle}
            onClick={() => {
              setRequestCreateName("新接口");
              setShowCreateRequestModal(true);
            }}
            disabled={!collectionId}
          >
            <Plus size={14} />
            新建请求
          </button>
          <button style={btnStyle} onClick={openEnvironmentModal} disabled={!collectionId}>
            <Settings2 size={14} />
            环境管理
          </button>
          <button style={btnStyle} onClick={() => void exportPostman()} disabled={!collectionId || isExporting}>
            {isExporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            导出 Postman
          </button>
        </div>

        <select value={collectionId} onChange={(e) => setCollectionId(e.target.value)} style={fieldStyle}>
          <option value="">选择集合</option>
          {collections.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>

        <KeyValueEditor
          title="集合变量"
          rows={collectionVarRows}
          setRows={setCollectionVarRows}
          keyPlaceholder="变量名，例如 baseUrl"
          valuePlaceholder="变量值，例如 http://127.0.0.1:8000"
        />
        <button style={btnStyle} onClick={() => void saveCollectionVariables()} disabled={!collectionId || isSavingCollection}>
          {isSavingCollection ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          保存集合变量
        </button>

        <div style={subTitleStyle}>请求列表</div>
        <div style={rowStyle}>
          <select
            value={selectedGroupFilter}
            onChange={(e) => setSelectedGroupFilter(e.target.value)}
            style={{ ...fieldStyle, flex: 1, minWidth: 120 }}
          >
            {groupOptions.map((item) => (
              <option key={item} value={item}>
                {item === "all" ? "全部分组" : item}
              </option>
            ))}
          </select>
          <select
            value={selectedTagFilter}
            onChange={(e) => setSelectedTagFilter(e.target.value)}
            style={{ ...fieldStyle, flex: 1, minWidth: 120 }}
          >
            {tagOptions.map((item) => (
              <option key={item} value={item}>
                {item === "all" ? "全部标签" : `#${item}`}
              </option>
            ))}
          </select>
          <button
            style={isGroupRunning ? primaryBtnStyle : btnStyle}
            onClick={() => void runSelectedGroup()}
            disabled={!collectionId || isGroupRunning}
            title={isSequential ? "按顺序执行，并传递变量" : "并行执行，速度快但无法传递变量"}
          >
            {isGroupRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {isSequential ? "顺序批跑" : "并发批跑"}
          </button>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#334155", fontSize: ".82rem", cursor: "pointer", userSelect: "none" }}>
            <input
              type="checkbox"
              checked={isSequential}
              onChange={(e) => setIsSequential(e.target.checked)}
            />
            顺序模式
          </label>
        </div>
        <div style={requestListStyle}>
          {filteredRequests.map((item) => (
            <button
              key={item.id}
              onClick={() => setRequestId(item.id)}
              style={{
                ...requestItemStyle,
                borderColor: item.id === requestId ? "var(--primary)" : "rgba(15,23,42,.1)",
              }}
            >
              <span style={methodBadgeStyle}>{item.method}</span>
              <span style={requestNameStyle}>{item.name}</span>
              <span style={groupBadgeStyle}>{item.groupName || "default"}</span>
              {(item.tags || []).length > 0 ? (
                <span style={tagBadgeStyle}>
                  #{item.tags[0]}
                  {(item.tags || []).length > 1 ? ` +${item.tags.length - 1}` : ""}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </aside>

      <section style={mainStyle}>
        <div style={toolbarStyle}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="请求名称" style={{ ...fieldStyle, width: 220 }} />
          <input
            value={groupName}
            onChange={(e) => setGroupName(e.target.value)}
            placeholder="分组名"
            style={{ ...fieldStyle, width: 130 }}
          />
          <input
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
            placeholder="标签(逗号分隔)"
            style={{ ...fieldStyle, width: 170 }}
          />
          <select value={method} onChange={(e) => setMethod(e.target.value as ApiRequest["method"])} style={{ ...fieldStyle, width: 110 }}>
            {["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="URL（支持 {{var}} 模板）" style={{ ...fieldStyle, flex: 1, fontFamily: "var(--mono)" }} />
          <button
            style={btnStyle}
            onClick={() => setShowDeleteRequestModal(true)}
            disabled={!requestId || isDeleting}
          >
            {isDeleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            删除
          </button>
          <button style={btnStyle} onClick={() => void saveRequest()} disabled={!requestId || isSaving}>
            {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            保存
          </button>
          <button style={btnStyle} onClick={() => void openSaveAsCaseModal()} disabled={!requestId || isSavingAsCase}>
            {isSavingAsCase ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            保存为用例
          </button>
          <button style={btnStyle} onClick={() => void openAddToCaseModal()} disabled={!requestId || !projectId || isAddingToCase}>
            {isAddingToCase ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            添加到用例
          </button>
          <button style={btnStyle} onClick={() => void sendBatchRequest()} disabled={!requestId || isBatchSending}>
            {isBatchSending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            参数化执行
          </button>
          <button style={primaryBtnStyle} onClick={() => void sendRequest()} disabled={!requestId || isSending}>
            {isSending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            发送
          </button>
        </div>

        <div style={envBarStyle}>
          <select value={environmentId} onChange={(e) => setEnvironmentId(e.target.value)} style={{ ...fieldStyle, width: 260 }}>
            <option value="">不使用环境变量</option>
            {environments.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} {item.isDefault ? "(默认)" : ""}
              </option>
            ))}
          </select>
          <div style={tabBarStyle}>
            <button
              style={activePanel === "request" ? activeTabBtnStyle : tabBtnStyle}
              onClick={() => setActivePanel("request")}
            >
              请求配置
            </button>
            <button
              style={activePanel === "assertions" ? activeTabBtnStyle : tabBtnStyle}
              onClick={() => setActivePanel("assertions")}
            >
              断言
            </button>
            <button
              style={activePanel === "scripts" ? activeTabBtnStyle : tabBtnStyle}
              onClick={() => setActivePanel("scripts")}
            >
              前后置脚本
            </button>
            <button
              style={activePanel === "variables" ? activeTabBtnStyle : tabBtnStyle}
              onClick={() => setActivePanel("variables")}
            >
              变量
            </button>
          </div>
          <input
            type="number"
            value={timeoutMs}
            min={500}
            max={60000}
            step={500}
            onChange={(e) => setTimeoutMs(Math.max(500, Math.min(60000, Number(e.target.value) || 5000)))}
            style={{ ...fieldStyle, width: 130 }}
            title="请求超时（毫秒）"
          />
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#334155", fontSize: ".86rem" }}>
            <input
              type="checkbox"
              checked={autoSaveBeforeSend}
              onChange={(e) => setAutoSaveBeforeSend(e.target.checked)}
            />
            发送前自动保存
          </label>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#334155", fontSize: ".86rem" }}>
            <input
              type="checkbox"
              checked={verifySsl}
              onChange={(e) => setVerifySsl(e.target.checked)}
            />
            校验证书 SSL
          </label>
          <input
            ref={certFileInputRef}
            type="file"
            accept=".pem,.crt,.cer,.cert,.txt"
            style={{ display: "none" }}
            onChange={(e) => void onPemFileChange(e, setClientCertPem, setClientCertName)}
          />
          <input
            ref={keyFileInputRef}
            type="file"
            accept=".pem,.key,.txt"
            style={{ display: "none" }}
            onChange={(e) => void onPemFileChange(e, setClientKeyPem, setClientKeyName)}
          />
          <button style={btnStyle} onClick={() => certFileInputRef.current?.click()} title="导入 mTLS 客户端证书 PEM">
            <Upload size={14} />
            {clientCertName ? "更换证书" : "导入证书"}
          </button>
          <button style={btnStyle} onClick={() => keyFileInputRef.current?.click()} title="导入 mTLS 客户端私钥 PEM">
            <Upload size={14} />
            {clientKeyName ? "更换私钥" : "导入私钥"}
          </button>
          {clientCertName || clientKeyName ? (
            <button
              style={ghostBtnStyle}
              onClick={() => {
                setClientCertPem("");
                setClientKeyPem("");
                setClientCertName("");
                setClientKeyName("");
              }}
              title="清除当前证书和私钥"
            >
              <X size={14} />
              清除证书
            </button>
          ) : null}
        </div>
        {clientCertName || clientKeyName ? (
          <div style={tlsInfoStyle}>
            mTLS: {clientCertName || "未导入证书"}{clientKeyName ? ` / ${clientKeyName}` : ""}
          </div>
        ) : null}

        {activePanel === "request" ? (
          <div style={editorGridStyle}>
            <KeyValueEditor
              title="Query 参数"
              rows={queryRows}
              setRows={setQueryRows}
              keyPlaceholder="参数名"
              valuePlaceholder="参数值"
            />
            <KeyValueEditor
              title="Headers 请求头"
              rows={headerRows}
              setRows={setHeaderRows}
              keyPlaceholder="Header 名"
              valuePlaceholder="Header 值"
            />
            <div style={{ ...editorGridStyle, gridColumn: "1 / span 2", padding: 0, border: "none", background: "transparent" }}>
              <select value={bodyMode} onChange={(e) => setBodyMode(e.target.value as ApiRequest["bodyMode"])} style={fieldStyle}>
                <option value="none">Body: none</option>
                <option value="json">Body: json</option>
                <option value="raw">Body: raw</option>
                <option value="form">Body: form</option>
              </select>
              {(bodyMode === "json" || bodyMode === "raw") ? (
                <textarea value={bodyRaw} onChange={(e) => setBodyRaw(e.target.value)} style={{ ...editorAreaStyle, minHeight: 128 }} placeholder="Body Raw" />
              ) : (
                <div style={assertionHintStyle}>当前 Body 模式无需 Raw 内容</div>
              )}
              {bodyMode === "form" ? (
                <div style={{ gridColumn: "1 / span 2" }}>
                  <KeyValueEditor
                    title="Body Form 表单"
                    rows={bodyFormRows}
                    setRows={setBodyFormRows}
                    keyPlaceholder="字段名"
                    valuePlaceholder="字段值"
                  />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {activePanel === "assertions" ? (
          <div style={editorGridStyle}>
            <div style={{ ...assertionPanelStyle, gridColumn: "1 / span 2" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ fontSize: ".88rem", color: "#0f172a" }}>断言设计器</strong>
                <button
                  style={btnStyle}
                  onClick={() =>
                    setAssertions((prev) => [
                      ...prev,
                      { type: "status_eq", name: "状态码断言", expected: 200 },
                    ])
                  }
                >
                  <Plus size={14} />
                  添加断言
                </button>
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                {assertions.length === 0 ? (
                  <div style={assertionHintStyle}>暂无断言，默认按 HTTP 状态 &lt; 400 判定成功</div>
                ) : null}
                {assertions.map((item, index) => (
                  <div key={`${item.type}-${index}`} style={assertionItemStyle}>
                    <select
                      value={item.type}
                      onChange={(e) =>
                        setAssertions((prev) =>
                          prev.map((row, rowIndex) =>
                            rowIndex === index
                              ? { ...row, type: e.target.value as AssertionType }
                              : row,
                          ),
                        )
                      }
                      style={{ ...fieldStyle, width: 170 }}
                    >
                      <option value="status_eq">状态码等于</option>
                      <option value="status_range">状态码区间</option>
                      <option value="response_time_lt">响应时间小于</option>
                      <option value="header_contains">Header 包含</option>
                      <option value="header_eq">Header 等于</option>
                      <option value="body_contains">Body 包含</option>
                      <option value="json_path_eq">JSONPath 等于</option>
                      <option value="json_path_exists">JSONPath 存在</option>
                      <option value="json_path_contains">JSONPath 包含</option>
                    </select>
                    <input
                      value={item.name}
                      onChange={(e) =>
                        setAssertions((prev) =>
                          prev.map((row, rowIndex) =>
                            rowIndex === index ? { ...row, name: e.target.value } : row,
                          ),
                        )
                      }
                      placeholder="断言名称"
                      style={{ ...fieldStyle, width: 170 }}
                    />
                    {item.type === "status_eq" ? (
                      <input
                        type="number"
                        value={Number(item.expected ?? 200)}
                        onChange={(e) =>
                          setAssertions((prev) =>
                            prev.map((row, rowIndex) =>
                              rowIndex === index
                                ? { ...row, expected: Number(e.target.value || 200) }
                                : row,
                            ),
                          )
                        }
                        style={{ ...fieldStyle, width: 120 }}
                        placeholder="状态码"
                      />
                    ) : null}
                    {item.type === "status_range" ? (
                      <>
                        <input
                          type="number"
                          value={item.min ?? 200}
                          onChange={(e) =>
                            setAssertions((prev) =>
                              prev.map((row, rowIndex) =>
                                rowIndex === index ? { ...row, min: Number(e.target.value || 200) } : row,
                              ),
                            )
                          }
                          style={{ ...fieldStyle, width: 100 }}
                          placeholder="min"
                        />
                        <input
                          type="number"
                          value={item.max ?? 299}
                          onChange={(e) =>
                            setAssertions((prev) =>
                              prev.map((row, rowIndex) =>
                                rowIndex === index ? { ...row, max: Number(e.target.value || 299) } : row,
                              ),
                            )
                          }
                          style={{ ...fieldStyle, width: 100 }}
                          placeholder="max"
                        />
                      </>
                    ) : null}
                    {item.type === "response_time_lt" ? (
                      <input
                        type="number"
                        value={item.expectedMs ?? 1000}
                        onChange={(e) =>
                          setAssertions((prev) =>
                            prev.map((row, rowIndex) =>
                              rowIndex === index
                                ? { ...row, expectedMs: Number(e.target.value || 1000) }
                                : row,
                            ),
                          )
                        }
                        style={{ ...fieldStyle, width: 140 }}
                        placeholder="毫秒"
                      />
                    ) : null}
                    {item.type === "header_contains" || item.type === "header_eq" ? (
                      <>
                        <input
                          value={item.key || ""}
                          onChange={(e) =>
                            setAssertions((prev) =>
                              prev.map((row, rowIndex) =>
                                rowIndex === index ? { ...row, key: e.target.value } : row,
                              ),
                            )
                          }
                          placeholder="Header Key"
                          style={{ ...fieldStyle, width: 150 }}
                        />
                        <input
                          value={item.type === "header_eq" ? item.expectedValue || "" : item.contains || ""}
                          onChange={(e) =>
                            setAssertions((prev) =>
                              prev.map((row, rowIndex) =>
                                rowIndex === index
                                  ? item.type === "header_eq"
                                    ? { ...row, expectedValue: e.target.value }
                                    : { ...row, contains: e.target.value }
                                  : row,
                              ),
                            )
                          }
                          placeholder={item.type === "header_eq" ? "等于值" : "包含值"}
                          style={{ ...fieldStyle, width: 170 }}
                        />
                      </>
                    ) : null}
                    {item.type === "body_contains" ? (
                      <input
                        value={item.contains || ""}
                        onChange={(e) =>
                          setAssertions((prev) =>
                            prev.map((row, rowIndex) =>
                              rowIndex === index ? { ...row, contains: e.target.value } : row,
                            ),
                          )
                        }
                        placeholder="Body 包含值"
                        style={{ ...fieldStyle, width: 190 }}
                      />
                    ) : null}
                    {item.type === "json_path_eq" || item.type === "json_path_exists" || item.type === "json_path_contains" ? (
                      <input
                        value={item.path || ""}
                        onChange={(e) =>
                          setAssertions((prev) =>
                            prev.map((row, rowIndex) =>
                              rowIndex === index ? { ...row, path: e.target.value } : row,
                            ),
                          )
                        }
                        placeholder="JSON Path，如 data.id"
                        style={{ ...fieldStyle, width: 170 }}
                      />
                    ) : null}
                    {item.type === "json_path_eq" ? (
                      <input
                        value={item.expectedValue || ""}
                        onChange={(e) =>
                          setAssertions((prev) =>
                            prev.map((row, rowIndex) =>
                              rowIndex === index ? { ...row, expectedValue: e.target.value } : row,
                            ),
                          )
                        }
                        placeholder='期望值(JSON)，如 "ok" 或 1'
                        style={{ ...fieldStyle, width: 180 }}
                      />
                    ) : null}
                    {item.type === "json_path_contains" ? (
                      <input
                        value={item.contains || ""}
                        onChange={(e) =>
                          setAssertions((prev) =>
                            prev.map((row, rowIndex) =>
                              rowIndex === index ? { ...row, contains: e.target.value } : row,
                            ),
                          )
                        }
                        placeholder="包含值"
                        style={{ ...fieldStyle, width: 170 }}
                      />
                    ) : null}
                    <button
                      style={btnStyle}
                      onClick={() =>
                        setAssertions((prev) => prev.filter((_, rowIndex) => rowIndex !== index))
                      }
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {activePanel === "scripts" ? (
          <div style={editorGridStyle}>
            <textarea
              value={preScriptText}
              onChange={(e) => setPreScriptText(e.target.value)}
              style={{ ...editorAreaStyle, minHeight: 160 }}
              placeholder='前置脚本(JSON DSL)，如 {"set":{"traceId":"{{uuid}}","ts":"{{nowTs}}"}}'
            />
            <textarea
              value={testScriptText}
              onChange={(e) => setTestScriptText(e.target.value)}
              style={{ ...editorAreaStyle, minHeight: 160 }}
              placeholder='后置脚本(JSON DSL)，如 {"extract":[{"name":"token","from":"json","path":"data.token"}],"assert":[{"type":"status_eq","expected":200}]}'
            />
            <div style={{ ...assertionHintStyle, gridColumn: "1 / span 2" }}>
              脚本采用安全 JSON DSL，不执行任意 JS。支持 pre `set/unset`，post `extract/assert`。
            </div>
          </div>
        ) : null}

        {activePanel === "variables" ? (
          <div style={editorGridStyle}>
            <textarea
              value={runtimeVarsText}
              onChange={(e) => setRuntimeVarsText(e.target.value)}
              style={{ ...editorAreaStyle, minHeight: 150 }}
              placeholder='运行时变量(JSON)，例如 {"token":"override-token"}'
            />
            <textarea
              value={resolvedVariablesPreview}
              readOnly
              style={{ ...editorAreaStyle, minHeight: 150, background: "#f8fafc" }}
              placeholder="这里会展示合并后的变量快照"
            />
            <textarea
              value={variableSetsText}
              onChange={(e) => setVariableSetsText(e.target.value)}
              style={{ ...editorAreaStyle, gridColumn: "1 / span 2", minHeight: 130 }}
              placeholder='参数化数据集(JSON数组)，例如 [{"name":"case1","variables":{"userId":"1"}}]'
            />
          </div>
        ) : null}

        <div style={responsePanelStyle}>
          {notice ? <div style={noticeStyle}>{notice}</div> : null}
          {run ? (
            <div style={metaStyle}>
              状态: <strong>{run.statusCode ?? "N/A"}</strong> | 耗时: <strong>{run.durationMs} ms</strong> | 结果:{" "}
              <strong style={{ color: run.success ? "#16a34a" : "#dc2626" }}>
                {run.success ? "PASS" : "FAIL"}
              </strong>
            </div>
          ) : null}
          {run && run.statusCode && run.statusCode >= 300 && run.statusCode < 400 ? (
            <div style={redirectHintStyle}>
              重定向到: <strong>{getResponseHeader(run.responseHeaders, "location") || "响应头未返回 Location"}</strong>
            </div>
          ) : null}
          {batchResult ? (
            <div style={metaStyle}>
              参数化结果: <strong>{batchResult.passed}</strong> / {batchResult.total} 通过，
              失败 {batchResult.failed}
            </div>
          ) : null}
          {run?.extractedVariables && Object.keys(run.extractedVariables).length > 0 ? (
            <div style={{ ...metaStyle, color: "#0369a1" }}>
              提取变量: {JSON.stringify(run.extractedVariables)}
            </div>
          ) : null}
          <pre style={preStyle}>
            {run
              ? run.errorMessage
                ? `ERROR: ${run.errorMessage}`
                : asText(run.responseBody)
              : "点击发送后在这里查看响应内容"}
          </pre>
        </div>
      </section>

      <ModalShell
        open={showCreateCollectionModal}
        title="新建接口集合"
        onClose={() => setShowCreateCollectionModal(false)}
      >
        <div style={modalFormStyle}>
          <label style={modalLabelStyle}>集合名称</label>
          <input
            value={collectionCreateName}
            onChange={(e) => setCollectionCreateName(e.target.value)}
            style={fieldStyle}
            placeholder="例如：支付中心 API"
          />
          <label style={modalLabelStyle}>描述</label>
          <textarea
            value={collectionCreateDescription}
            onChange={(e) => setCollectionCreateDescription(e.target.value)}
            style={{ ...editorAreaStyle, minHeight: 96 }}
            placeholder="可选，说明这个集合的用途"
          />
          <div style={modalActionStyle}>
            <button style={btnStyle} onClick={() => setShowCreateCollectionModal(false)}>
              取消
            </button>
            <button style={primaryBtnStyle} onClick={() => void submitCreateCollection()}>
              创建集合
            </button>
          </div>
        </div>
      </ModalShell>

      <ModalShell
        open={showCreateRequestModal}
        title="新建接口请求"
        onClose={() => setShowCreateRequestModal(false)}
      >
        <div style={modalFormStyle}>
          <label style={modalLabelStyle}>请求名称</label>
          <input
            value={requestCreateName}
            onChange={(e) => setRequestCreateName(e.target.value)}
            style={fieldStyle}
            placeholder="例如：创建订单"
          />
          <div style={modalActionStyle}>
            <button style={btnStyle} onClick={() => setShowCreateRequestModal(false)}>
              取消
            </button>
            <button style={primaryBtnStyle} onClick={() => void submitCreateRequest()}>
              创建请求
            </button>
          </div>
        </div>
      </ModalShell>

      <ModalShell
        open={showDeleteRequestModal}
        title="删除请求"
        onClose={() => setShowDeleteRequestModal(false)}
      >
        <div style={modalFormStyle}>
          <div style={modalHintStyle}>确认删除当前请求吗？删除后不可恢复。</div>
          <div style={modalActionStyle}>
            <button style={btnStyle} onClick={() => setShowDeleteRequestModal(false)}>
              取消
            </button>
            <button style={dangerBtnStyle} onClick={() => void confirmDeleteRequest()} disabled={isDeleting}>
              {isDeleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              确认删除
            </button>
          </div>
        </div>
      </ModalShell>

      <ModalShell
        open={showSaveAsCaseModal}
        title="保存为测试用例"
        onClose={() => setShowSaveAsCaseModal(false)}
      >
        <div style={modalFormStyle}>
          <div style={modalHintStyle}>
            将当前 API 请求保存为测试用例，可在测试用例管理中查看和执行。
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", marginBottom: 6, fontWeight: 500 }}>
              用例标题
            </label>
            <input
              type="text"
              value={saveAsCaseTitle}
              onChange={(e) => setSaveAsCaseTitle(e.target.value)}
              placeholder="输入测试用例标题"
              style={{ ...fieldStyle, width: "100%" }}
            />
          </div>
          <div style={modalActionStyle}>
            <button style={btnStyle} onClick={() => setShowSaveAsCaseModal(false)}>
              取消
            </button>
            <button style={primaryBtnStyle} onClick={() => void saveAsTestCase()} disabled={isSavingAsCase}>
              {isSavingAsCase ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              保存
            </button>
          </div>
        </div>
      </ModalShell>

      <ModalShell
        open={showAddToCaseModal}
        title="添加到已有用例"
        onClose={() => setShowAddToCaseModal(false)}
      >
        <div style={modalFormStyle}>
          <div style={modalHintStyle}>
            将当前 API 请求添加到已有的测试用例中，作为自动化测试的一个步骤。
          </div>
          {isLoadingCases ? (
            <div style={{ textAlign: "center", padding: 20 }}>
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : existingCases.length === 0 ? (
            <div style={{ textAlign: "center", padding: 20, color: "var(--ink-soft)" }}>
              当前项目下没有 API 类型的测试用例，请先创建一个。
            </div>
          ) : (
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", marginBottom: 6, fontWeight: 500 }}>
                选择测试用例
              </label>
              <select
                value={selectedCaseId}
                onChange={(e) => setSelectedCaseId(e.target.value)}
                style={{ ...fieldStyle, width: "100%" }}
              >
                {existingCases.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title} ({c.stepsCount} 个步骤)
                  </option>
                ))}
              </select>
            </div>
          )}
          <div style={modalActionStyle}>
            <button style={btnStyle} onClick={() => setShowAddToCaseModal(false)}>
              取消
            </button>
            <button
              style={primaryBtnStyle}
              onClick={() => void addToExistingCase()}
              disabled={isAddingToCase || existingCases.length === 0}
            >
              {isAddingToCase ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              添加
            </button>
          </div>
        </div>
      </ModalShell>

      <ModalShell
        open={showEnvironmentModal}
        title="环境管理"
        onClose={() => setShowEnvironmentModal(false)}
        width={860}
      >
        <div style={envModalLayoutStyle}>
          <aside style={envListPanelStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ color: "#0f172a" }}>环境列表</strong>
              <button style={btnStyle} onClick={startCreateEnvironment}>
                <Plus size={14} />
                新建
              </button>
            </div>
            <div style={{ display: "grid", gap: 8, maxHeight: 360, overflowY: "auto" }}>
              {environments.length === 0 ? <div style={modalHintStyle}>当前集合还没有环境</div> : null}
              {environments.map((env) => (
                <div
                  key={env.id}
                  style={{
                    border: "1px solid rgba(15,23,42,.12)",
                    borderRadius: 10,
                    padding: 10,
                    display: "grid",
                    gap: 8,
                    background: envEditingId === env.id ? "rgba(2,132,199,.08)" : "white",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <strong>{env.name}</strong>
                    {env.isDefault ? <span style={groupBadgeStyle}>默认</span> : null}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button style={btnStyle} onClick={() => startEditEnvironment(env)}>
                      <Pencil size={14} />
                      编辑
                    </button>
                    <button
                      style={dangerGhostBtnStyle}
                      onClick={() => void removeEnvironment(env.id)}
                      disabled={isDeletingEnvironment}
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </aside>

          <section style={envEditorPanelStyle}>
            <label style={modalLabelStyle}>环境名称</label>
            <input
              value={envDraftName}
              onChange={(e) => setEnvDraftName(e.target.value)}
              style={fieldStyle}
              placeholder="例如：Dev / Test / Prod"
            />
            <label style={modalLabelStyle}>变量(JSON)</label>
            <textarea
              value={envDraftVariablesText}
              onChange={(e) => setEnvDraftVariablesText(e.target.value)}
              style={{ ...editorAreaStyle, minHeight: 220 }}
              placeholder='{"baseUrl":"https://api.dev.example.com","token":"{{token}}"}'
            />
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={envDraftIsDefault}
                onChange={(e) => setEnvDraftIsDefault(e.target.checked)}
              />
              设为默认环境
            </label>
            <div style={modalActionStyle}>
              <button style={btnStyle} onClick={() => setShowEnvironmentModal(false)}>
                关闭
              </button>
              <button style={primaryBtnStyle} onClick={() => void saveEnvironment()} disabled={isSavingEnvironment}>
                {isSavingEnvironment ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                保存环境
              </button>
            </div>
          </section>
        </div>
      </ModalShell>
    </div>
  );
}

function ModalShell({
  open,
  title,
  onClose,
  children,
  width = 560,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  width?: number;
}) {
  if (!open) return null;
  return (
    <div style={modalBackdropStyle} role="dialog" aria-modal="true">
      <div style={{ ...modalCardStyle, width }}>
        <div style={modalHeaderStyle}>
          <strong style={{ fontSize: "1rem", color: "#0f172a" }}>{title}</strong>
          <button style={iconBtnStyle} onClick={onClose} aria-label="关闭弹窗">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function KeyValueEditor({
  title,
  rows,
  setRows,
  keyPlaceholder,
  valuePlaceholder,
}: {
  title: string;
  rows: EditableKvRow[];
  setRows: (rows: EditableKvRow[] | ((prev: EditableKvRow[]) => EditableKvRow[])) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
}) {
  return (
    <div style={kvPanelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ fontSize: ".88rem", color: "#0f172a" }}>{title}</strong>
        <button style={btnStyle} onClick={() => setRows((prev) => [...prev, createKvRow()])}>
          <Plus size={14} />
          新增一行
        </button>
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        {rows.map((row) => (
          <div key={row.id} style={kvRowStyle}>
            <input
              value={row.key}
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((item) => (item.id === row.id ? { ...item, key: e.target.value } : item)),
                )
              }
              placeholder={keyPlaceholder}
              style={{ ...fieldStyle, minWidth: 120 }}
            />
            <input
              value={row.value}
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((item) => (item.id === row.id ? { ...item, value: e.target.value } : item)),
                )
              }
              placeholder={valuePlaceholder}
              style={{ ...fieldStyle, flex: 1, minWidth: 160 }}
            />
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#475569" }}>
              <input
                type="checkbox"
                checked={row.enabled}
                onChange={(e) =>
                  setRows((prev) =>
                    prev.map((item) =>
                      item.id === row.id ? { ...item, enabled: e.target.checked } : item,
                    ),
                  )
                }
              />
              启用
            </label>
            <button
              style={dangerGhostBtnStyle}
              onClick={() =>
                setRows((prev) => {
                  const next = prev.filter((item) => item.id !== row.id);
                  return next.length > 0 ? next : [createKvRow()];
                })
              }
            >
              <Trash2 size={14} />
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

const pageStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "340px minmax(0, 1fr)",
  gap: 12,
  height: "100%",
  width: "100%",
  background: "transparent",
};

const sidebarStyle: CSSProperties = {
  display: "grid",
  gridTemplateRows: "auto auto auto auto auto auto auto auto 1fr",
  gap: 10,
  border: "1px solid rgba(15,23,42,.08)",
  borderRadius: 14,
  padding: 12,
  background: "rgba(255,255,255,.88)",
  backdropFilter: "blur(4px)",
  overflow: "hidden",
};

const mainStyle: CSSProperties = {
  display: "grid",
  gridTemplateRows: "auto auto auto 1fr",
  gap: 10,
  minWidth: 0,
};

const toolbarStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  padding: 12,
  borderRadius: 14,
  border: "1px solid rgba(15,23,42,.08)",
  background: "rgba(255,255,255,.9)",
  alignItems: "center",
};

const envBarStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  padding: 12,
  borderRadius: 14,
  border: "1px solid rgba(15,23,42,.08)",
  background: "rgba(255,255,255,.9)",
  alignItems: "stretch",
};

const editorGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 10,
  borderRadius: 14,
  border: "1px solid rgba(15,23,42,.08)",
  padding: 12,
  background: "rgba(255,255,255,.9)",
};

const responsePanelStyle: CSSProperties = {
  borderRadius: 14,
  border: "1px solid rgba(15,23,42,.08)",
  padding: 12,
  background: "rgba(255,255,255,.92)",
  overflow: "hidden",
  display: "grid",
  gridTemplateRows: "auto auto 1fr",
  gap: 8,
};

const fieldStyle: CSSProperties = {
  height: 38,
  borderRadius: 10,
  border: "1px solid rgba(15,23,42,.12)",
  padding: "0 10px",
  background: "white",
};

const btnStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 6,
  height: 36,
  padding: "0 12px",
  borderRadius: 10,
  border: "1px solid rgba(15,23,42,.12)",
  background: "white",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const primaryBtnStyle: CSSProperties = {
  ...btnStyle,
  border: "none",
  color: "white",
  background: "linear-gradient(120deg, #0284c7, #0ea5e9)",
};

const rowStyle: CSSProperties = { display: "flex", gap: 8, flexWrap: "wrap" };
const modalBackdropStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(2,6,23,.42)",
  display: "grid",
  placeItems: "center",
  zIndex: 1200,
  padding: 16,
};
const modalCardStyle: CSSProperties = {
  maxWidth: "92vw",
  maxHeight: "88vh",
  overflow: "auto",
  borderRadius: 14,
  border: "1px solid rgba(15,23,42,.12)",
  background: "white",
  boxShadow: "0 20px 50px rgba(2,6,23,.25)",
  padding: 14,
  display: "grid",
  gap: 12,
};
const modalHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};
const iconBtnStyle: CSSProperties = {
  ...btnStyle,
  width: 34,
  height: 34,
  padding: 0,
};
const modalFormStyle: CSSProperties = {
  display: "grid",
  gap: 10,
};
const modalLabelStyle: CSSProperties = {
  fontSize: ".84rem",
  fontWeight: 600,
  color: "#334155",
};
const modalHintStyle: CSSProperties = {
  fontSize: ".86rem",
  color: "#475569",
};
const modalActionStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 8,
};
const dangerBtnStyle: CSSProperties = {
  ...btnStyle,
  background: "#dc2626",
  color: "white",
  border: "none",
};
const dangerGhostBtnStyle: CSSProperties = {
  ...btnStyle,
  color: "#b91c1c",
  border: "1px solid rgba(185,28,28,.28)",
  background: "rgba(254,242,242,.8)",
};
const ghostBtnStyle: CSSProperties = {
  ...btnStyle,
  color: "#334155",
  background: "#f8fafc",
};
const tlsInfoStyle: CSSProperties = {
  margin: "-10px 0 14px",
  color: "#475569",
  fontSize: ".8rem",
};
const envModalLayoutStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "280px 1fr",
  gap: 12,
};
const envListPanelStyle: CSSProperties = {
  border: "1px solid rgba(15,23,42,.1)",
  borderRadius: 10,
  padding: 10,
  background: "#f8fafc",
  display: "grid",
  gap: 10,
  alignContent: "start",
};
const envEditorPanelStyle: CSSProperties = {
  border: "1px solid rgba(15,23,42,.1)",
  borderRadius: 10,
  padding: 10,
  background: "white",
  display: "grid",
  gap: 10,
};
const tabBarStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap",
};
const tabBtnStyle: CSSProperties = {
  ...btnStyle,
  height: 34,
  background: "#f8fafc",
  border: "1px solid rgba(15,23,42,.1)",
};
const activeTabBtnStyle: CSSProperties = {
  ...tabBtnStyle,
  background: "rgba(2,132,199,.12)",
  color: "#0369a1",
  border: "1px solid rgba(2,132,199,.35)",
};
const kvPanelStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  border: "1px solid rgba(15,23,42,.12)",
  borderRadius: 10,
  padding: 10,
  background: "white",
};
const kvRowStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap",
  padding: "8px 6px",
  border: "1px dashed rgba(15,23,42,.18)",
  borderRadius: 8,
};

const panelTitleStyle: CSSProperties = { fontWeight: 700, fontSize: "1rem", color: "#0f172a" };
const subTitleStyle: CSSProperties = { fontWeight: 600, fontSize: ".9rem", color: "#334155" };

const miniAreaStyle: CSSProperties = {
  minHeight: 88,
  borderRadius: 10,
  border: "1px solid rgba(15,23,42,.12)",
  padding: "8px 10px",
  fontFamily: "var(--mono)",
  fontSize: ".8rem",
  resize: "vertical",
  background: "white",
};

const requestListStyle: CSSProperties = {
  overflowY: "auto",
  display: "grid",
  gap: 7,
  minHeight: 140,
};

const requestItemStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  borderWidth: 1,
  borderStyle: "solid",
  borderColor: "rgba(15,23,42,.1)",
  borderRadius: 10,
  padding: "8px 10px",
  background: "white",
  cursor: "pointer",
  textAlign: "left",
};

const methodBadgeStyle: CSSProperties = {
  minWidth: 52,
  textAlign: "center",
  fontWeight: 700,
  fontSize: ".75rem",
  color: "#0369a1",
  background: "rgba(2,132,199,.12)",
  borderRadius: 999,
  padding: "3px 8px",
};

const requestNameStyle: CSSProperties = {
  flex: 1,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const groupBadgeStyle: CSSProperties = {
  fontSize: ".72rem",
  color: "#334155",
  background: "rgba(51,65,85,.1)",
  borderRadius: 999,
  padding: "2px 8px",
  whiteSpace: "nowrap",
};
const tagBadgeStyle: CSSProperties = {
  fontSize: ".72rem",
  color: "#0f766e",
  background: "rgba(20,184,166,.14)",
  borderRadius: 999,
  padding: "2px 8px",
  whiteSpace: "nowrap",
};

const assertionPanelStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  border: "1px solid rgba(15,23,42,.12)",
  borderRadius: 10,
  padding: 10,
  background: "white",
};

const assertionItemStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap",
  padding: 8,
  borderRadius: 8,
  border: "1px dashed rgba(15,23,42,.2)",
};

const assertionHintStyle: CSSProperties = {
  color: "#64748b",
  fontSize: ".82rem",
};

const editorAreaStyle: CSSProperties = {
  minHeight: 128,
  borderRadius: 10,
  border: "1px solid rgba(15,23,42,.12)",
  padding: "8px 10px",
  fontFamily: "var(--mono)",
  fontSize: ".82rem",
  resize: "vertical",
  background: "white",
};

const noticeStyle: CSSProperties = {
  color: "#0369a1",
  fontSize: ".85rem",
  background: "rgba(2,132,199,.08)",
  border: "1px solid rgba(2,132,199,.2)",
  borderRadius: 8,
  padding: "6px 10px",
};

const metaStyle: CSSProperties = {
  fontSize: ".86rem",
  color: "#1e293b",
};

const redirectHintStyle: CSSProperties = {
  ...metaStyle,
  color: "#b45309",
  background: "#fffbeb",
  border: "1px solid #fde68a",
  borderRadius: 8,
  padding: "6px 10px",
};

const preStyle: CSSProperties = {
  margin: 0,
  background: "#0f172a",
  color: "#e2e8f0",
  borderRadius: 10,
  padding: "12px",
  fontFamily: "var(--mono)",
  whiteSpace: "pre-wrap",
  overflow: "auto",
};
