import { fetchJson } from "./client";
import { SearchResult } from "./types";

export interface SearchRequirementsParams {
    page?: number;
    pageSize?: number;
    sortBy?: string;
    sortOrder?: "asc" | "desc";
    projectId?: string;
    q?: string;
    status?: string;
}

export async function searchRequirements(params: SearchRequirementsParams = {}): Promise<SearchResult<any>> {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.set("page", params.page.toString());
    if (params.pageSize) searchParams.set("pageSize", params.pageSize.toString());
    if (params.sortBy) searchParams.set("sortBy", params.sortBy);
    if (params.sortOrder) searchParams.set("sortOrder", params.sortOrder);
    if (params.projectId) searchParams.set("projectId", params.projectId);
    if (params.q) searchParams.set("q", params.q);
    if (params.status) searchParams.set("status", params.status);
    return fetchJson(`/api/requirements?${searchParams.toString()}`);
}

export async function listRequirements(projectId?: string, q?: string, status?: string): Promise<any> {
    const params = new URLSearchParams();
    if (projectId) params.set("projectId", projectId);
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    return fetchJson(`/requirements?${params.toString()}`);
}

export async function createRequirement(data: any): Promise<any> {
    return fetchJson("/requirements", {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function getRequirement(requirementId: string): Promise<any> {
    return fetchJson(`/requirements/${requirementId}`);
}

export async function updateRequirement(requirementId: string, data: any): Promise<any> {
    return fetchJson(`/requirements/${requirementId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
    });
}

export async function deleteRequirement(requirementId: string): Promise<any> {
    return fetchJson(`/requirements/${requirementId}`, {
        method: "DELETE",
    });
}

export async function batchDeleteRequirements(ids: string[]): Promise<any> {
    return fetchJson("/requirements/batch", {
        method: "DELETE",
        body: JSON.stringify({ ids }),
    });
}

export async function restoreRequirement(requirementId: string): Promise<any> {
    return fetchJson(`/requirements/${requirementId}/restore`, {
        method: "POST",
    });
}

export async function analyzeRequirement(requirementId: string): Promise<any> {
    return fetchJson(`/requirements/${requirementId}/analyze`, {
        method: "POST",
    });
}

export async function getRequirementAnalysis(requirementId: string, version?: number): Promise<any> {
    const params = new URLSearchParams();
    if (version) params.set("version", version.toString());
    return fetchJson(`/requirements/${requirementId}/analysis?${params.toString()}`);
}

export async function importRequirements(projectId: string, file: File, strict: boolean = false): Promise<any> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("projectId", projectId);
    formData.append("strict", strict.toString());
    return fetchJson(`/requirements/import`, {
        method: "POST",
        body: formData,
    });
}
