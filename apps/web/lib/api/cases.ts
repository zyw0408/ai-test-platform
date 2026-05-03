import { fetchJson } from "./client";
import { SearchResult } from "./types";

export interface SearchCasesParams {
    projectId?: string;
    requirementId?: string;
    specId?: string;
    kind?: string;
    status?: string;
    q?: string;
    page?: number;
    pageSize?: number;
    sortBy?: string;
    sortOrder?: "asc" | "desc";
}

export async function searchCases(params: SearchCasesParams = {}): Promise<SearchResult<any>> {
    const searchParams = new URLSearchParams();
    if (params.projectId) searchParams.set("projectId", params.projectId);
    if (params.requirementId) searchParams.set("requirementId", params.requirementId);
    if (params.specId) searchParams.set("specId", params.specId);
    if (params.kind) searchParams.set("kind", params.kind);
    if (params.status) searchParams.set("status", params.status);
    if (params.q) searchParams.set("q", params.q);
    if (params.page) searchParams.set("page", params.page.toString());
    if (params.pageSize) searchParams.set("pageSize", params.pageSize.toString());
    if (params.sortBy) searchParams.set("sortBy", params.sortBy);
    if (params.sortOrder) searchParams.set("sortOrder", params.sortOrder);
    return fetchJson(`/cases?${searchParams.toString()}`);
}

export async function listCases(projectId?: string, requirementId?: string, specId?: string, q?: string): Promise<any> {
    const params = new URLSearchParams();
    if (projectId) params.set("projectId", projectId);
    if (requirementId) params.set("requirementId", requirementId);
    if (specId) params.set("specId", specId);
    if (q) params.set("q", q);
    return fetchJson(`/cases?${params.toString()}`);
}

export async function getCase(caseId: string): Promise<any> {
    return fetchJson(`/cases/${caseId}`);
}

export async function createCase(data: any): Promise<any> {
    return fetchJson("/cases", {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateCase(caseId: string, data: any): Promise<any> {
    return fetchJson(`/cases/${caseId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
    });
}

export async function deleteCase(caseId: string): Promise<any> {
    return fetchJson(`/cases/${caseId}`, {
        method: "DELETE",
    });
}

export async function batchDeleteCases(caseIds: string[]): Promise<{ deleted: number }> {
    return fetchJson("/cases/batch-delete", {
        method: "POST",
        body: JSON.stringify({ caseIds }),
    });
}

export async function generateCases(requirementId: string): Promise<any> {
    return fetchJson(`/cases/generate`, {
        method: "POST",
        body: JSON.stringify({ requirementId }),
    });
}
