import { fetchJson } from "./client";

export async function listProjects(q?: string, status?: string): Promise<any> {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    const rows = await fetchJson<any[]>(`/projects?${params.toString()}`);
    // Defensive filter: never expose recycled projects in active selectors.
    return (Array.isArray(rows) ? rows : []).filter(
        (item) => !item?.deletedAt && !item?.deleted_at,
    );
}

export async function searchProjects(params: {
    q?: string;
    status?: string;
    page?: number;
    pageSize?: number;
    sortBy?: string;
    sortOrder?: "asc" | "desc";
} = {}): Promise<any> {
    const search = new URLSearchParams();
    if (params.q) search.set("q", params.q);
    if (params.status) search.set("status", params.status);
    if (typeof params.page === "number") search.set("page", String(params.page));
    if (typeof params.pageSize === "number") search.set("pageSize", String(params.pageSize));
    if (params.sortBy) search.set("sortBy", params.sortBy);
    if (params.sortOrder) search.set("sortOrder", params.sortOrder);
    return fetchJson(`/projects/search?${search.toString()}`);
}

export async function createProject(data: any): Promise<any> {
    return fetchJson("/projects", {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function getProject(projectId: string): Promise<any> {
    return fetchJson(`/projects/${projectId}`);
}

export async function updateProject(projectId: string, data: any): Promise<any> {
    return fetchJson(`/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
    });
}

export async function deleteProject(projectId: string): Promise<any> {
    return fetchJson(`/projects/${projectId}`, {
        method: "DELETE",
    });
}
