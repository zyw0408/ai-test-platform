import { fetchJson } from "./client";

export interface ListRunsParams {
    projectId?: string;
    limit?: number;
}

export async function listRuns(params: ListRunsParams = {}): Promise<any[]> {
    const searchParams = new URLSearchParams();
    if (params.projectId) searchParams.set("projectId", params.projectId);
    if (params.limit) searchParams.set("limit", params.limit.toString());
    return fetchJson(`/testing/runs?${searchParams.toString()}`);
}

export async function getRun(runId: string): Promise<any> {
    const result = await fetchJson(`/testing/runs/${runId}`);
    if (result && typeof result === 'object' && 'run' in result) {
        return result.run;
    }
    return result;
}

export async function getReport(runId: string): Promise<any> {
    return fetchJson(`/testing/runs/${runId}`);
}

export async function listTestRuns(projectId?: string): Promise<any> {
    const params = new URLSearchParams();
    if (projectId) params.set("projectId", projectId);
    return fetchJson(`/runs?${params.toString()}`);
}

export async function getTestRun(runId: string): Promise<any> {
    return fetchJson(`/runs/${runId}`);
}

export async function deleteTestRun(runId: string): Promise<any> {
    return fetchJson(`/runs/${runId}`, {
        method: "DELETE",
    });
}

export async function getCaseRunReport(runId: string, caseId: string): Promise<any> {
    return fetchJson(`/runs/${runId}/cases/${caseId}/report`);
}

export async function getFullRunReport(runId: string): Promise<any> {
    return fetchJson(`/runs/${runId}/report`);
}

export async function stopTestRun(runId: string): Promise<any> {
    return fetchJson(`/runs/${runId}/stop`, {
        method: "POST",
    });
}
