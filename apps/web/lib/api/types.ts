export interface SearchResult<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  hasNext: boolean;
}

export interface Project {
  id: string;
  name: string;
}

export interface ApiCollection {
  id: string;
  projectId: string;
  name: string;
  description: string;
  variables: Record<string, string>;
}

export interface ApiEnvironment {
  id: string;
  collectionId: string;
  name: string;
  variables: Record<string, string>;
  isDefault: boolean;
}

export interface ApiKeyValue {
  key: string;
  value: string;
  enabled: boolean;
  description: string;
}

export interface ApiRequest {
  id: string;
  collectionId: string;
  parentId?: string;
  name: string;
  groupName: string;
  tags: string[];
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD" | "OPTIONS";
  url: string;
  query: ApiKeyValue[];
  headers: ApiKeyValue[];
  bodyMode: "none" | "raw" | "json" | "form";
  bodyRaw: string;
  bodyForm: ApiKeyValue[];
  authType: "none" | "bearer" | "basic" | "apiKey";
  auth: Record<string, string>;
  verifySsl: boolean;
  tls?: {
    certPem?: string;
    keyPem?: string;
    certName?: string;
    keyName?: string;
  };
  tests: Array<Record<string, any>>;
  preScript: string;
  testScript: string;
  sortOrder: number;
  isFolder: boolean;
}

export interface ApiRun {
  id: string;
  requestId: string;
  collectionId: string;
  method: string;
  url: string;
  statusCode: number | null;
  durationMs: number;
  success: boolean;
  responseHeaders: Record<string, string>;
  responseBody: string;
  responseSize: number;
  errorMessage: string | null;
  assertions: any[];
  extractedVariables: Record<string, string>;
  createdAt: string;
}

export interface ApiBatchRunResult {
  requestId: string;
  total: number;
  passed: number;
  failed: number;
  items: Array<{
    name: string;
    variables: Record<string, string>;
    run: ApiRun;
  }>;
}

export type AssertionType =
  | "status_eq"
  | "status_range"
  | "json_path_eq"
  | "json_path_exists"
  | "json_path_contains"
  | "header_contains"
  | "header_eq"
  | "body_contains"
  | "response_time_lt";

export interface AssertionDraft {
  type: AssertionType;
  name: string;
  expected?: number | string;
  min?: number;
  max?: number;
  path?: string;
  expectedValue?: string;
  key?: string;
  contains?: string;
  expectedMs?: number;
}
