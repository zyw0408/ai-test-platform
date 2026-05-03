import { fetchJson } from "./client";

// --- Collections ---

export async function listApiCollections(projectId?: string): Promise<any[]> {
  const params = new URLSearchParams();
  if (projectId) params.set("projectId", projectId);
  return fetchJson<any[]>(`/testing/collections?${params.toString()}`);
}

export async function createApiCollection(payload: any): Promise<any> {
    return fetchJson("/testing/collections", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function getApiCollection(collectionId: string): Promise<any> {
    return fetchJson(`/testing/collections/${collectionId}`);
}

export async function updateApiCollection(collectionId: string, updates: any): Promise<any> {
    return fetchJson(`/testing/collections/${collectionId}`, {
        method: "PATCH",
        body: JSON.stringify(updates),
    });
}

export async function deleteApiCollection(collectionId: string): Promise<void> {
    return fetchJson(`/testing/collections/${collectionId}`, {
        method: "DELETE",
    });
}

// --- Requests ---

export async function listApiCollectionRequests(collectionId: string): Promise<any[]> {
  return fetchJson<any[]>(`/testing/requests?collectionId=${collectionId}`);
}

export async function createApiRequest(payload: any): Promise<any> {
    return fetchJson("/testing/requests", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function updateApiRequest(requestId: string, updates: any): Promise<any> {
    return fetchJson(`/testing/requests/${requestId}`, {
        method: "PATCH",
        body: JSON.stringify(updates),
    });
}

export async function deleteApiRequest(requestId: string): Promise<void> {
    return fetchJson(`/testing/requests/${requestId}`, {
        method: "DELETE",
    });
}

// --- Environments ---

export async function listApiCollectionEnvironments(collectionId: string): Promise<any[]> {
  return fetchJson<any[]>(`/testing/environments?collectionId=${collectionId}`);
}

export async function createApiEnvironment(payload: any): Promise<any> {
    return fetchJson("/testing/environments", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function updateApiEnvironment(envId: string, updates: any): Promise<any> {
    return fetchJson(`/testing/environments/${envId}`, {
        method: "PATCH",
        body: JSON.stringify(updates),
    });
}

export async function deleteApiEnvironment(envId: string): Promise<void> {
    return fetchJson(`/testing/environments/${envId}`, {
        method: "DELETE",
    });
}

// --- Execution ---

export async function sendApiRequest(requestId: string, payload: any): Promise<any> {
    return fetchJson(`/testing/requests/${requestId}/send`, {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function sendBatchApiRequest(requestId: string, payload: any): Promise<any> {
    return fetchJson(`/testing/requests/${requestId}/send-batch`, {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function runApiCollection(collectionId: string, payload: any): Promise<any> {
    return fetchJson(`/testing/collections/${collectionId}/run`, {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function importOpenApi(collectionId: string, file: File): Promise<any> {
    const formData = new FormData();
    formData.append("file", file);
    return fetchJson(`/testing/collections/${collectionId}/import-openapi`, {
        method: "POST",
        body: formData,
    });
}

export async function exportPostman(collection_id: string): Promise<any> {
    return fetchJson(`/testing/collections/${collection_id}/export-postman`);
}

// --- Runs ---

export async function listApiRuns(params: { collectionId?: string; requestId?: string; limit?: number } = {}): Promise<any[]> {
    const s = new URLSearchParams();
    if (params.collectionId) s.set("collectionId", params.collectionId);
    if (params.requestId) s.set("requestId", params.requestId);
    if (params.limit) s.set("limit", params.limit.toString());
    return fetchJson(`/testing/api-runs?${s.toString()}`);
}

// --- Performance & Stats ---

export async function runApiPerformanceTest(payload: any): Promise<any> {
    return fetchJson("/testing/performance/run", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function startApiPerformanceRun(payload: any): Promise<any> {
    return fetchJson("/testing/performance/runs", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function listApiPerformanceRuns(params: { projectId?: string; limit?: number } = {}): Promise<any[]> {
    const s = new URLSearchParams();
    if (params.projectId) s.set("projectId", params.projectId);
    if (params.limit) s.set("limit", params.limit.toString());
    return fetchJson(`/testing/performance/runs?${s.toString()}`);
}

export async function getApiPerformanceRun(runId: string): Promise<any> {
    return fetchJson(`/testing/performance/runs/${runId}`);
}

export async function stopApiPerformanceRun(runId: string): Promise<any> {
    return fetchJson(`/testing/performance/runs/${runId}`, {
        method: "DELETE",
    });
}

export async function getApiPerformanceCapacity(): Promise<any> {
    return fetchJson("/testing/performance/capacity");
}

export async function getApiPerformanceRegressionConfig(): Promise<any> {
    return fetchJson("/testing/performance/regression-config");
}

export async function updateApiPerformanceRegressionConfig(payload: any): Promise<any> {
    return fetchJson("/testing/performance/regression-config", {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export async function compareApiPerformanceRuns(params: { projectId?: string; collectionId?: string; limit?: number } = {}): Promise<any> {
    const s = new URLSearchParams();
    if (params.projectId) s.set("projectId", params.projectId);
    if (params.collectionId) s.set("collectionId", params.collectionId);
    if (params.limit) s.set("limit", params.limit.toString());
    return fetchJson(`/testing/performance/compare?${s.toString()}`);
}

export async function deleteApiPerformanceRunRecord(runId: string, force = false): Promise<any> {
    const s = new URLSearchParams();
    if (force) s.set("force", "true");
    return fetchJson(`/testing/performance/runs/${runId}/record${s.toString() ? `?${s.toString()}` : ""}`, {
        method: "DELETE",
    });
}

export async function batchDeleteApiPerformanceRunRecords(payload: { runIds: string[]; force?: boolean }): Promise<any> {
    return fetchJson("/testing/performance/runs/batch-delete", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function listTestingStats(projectId: string): Promise<any> {
    return fetchJson(`/testing/stats?projectId=${projectId}`);
}
