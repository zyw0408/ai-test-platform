import { fetchJson } from "./client";

export async function listSpecs(projectId?: string): Promise<any> {
    const params = new URLSearchParams();
    if (projectId) params.set("projectId", projectId);
    return fetchJson(`/specs?${params.toString()}`);
}

export async function getSpec(specId: string): Promise<any> {
    return fetchJson(`/specs/${specId}`);
}

export async function uploadSpec(projectId: string, file: File): Promise<any> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("projectId", projectId);
    return fetchJson(`/specs`, {
        method: "POST",
        body: formData,
    });
}
