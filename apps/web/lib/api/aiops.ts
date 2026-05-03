import { fetchJson } from "./client";

export async function getAiOperationStatus(operationId: string): Promise<any> {
    return fetchJson(`/ai/operations/${operationId}`);
}

export async function retryAiOperation(operationId: string): Promise<any> {
    return fetchJson(`/ai/operations/${operationId}/retry`, {
        method: "POST",
    });
}

export async function cancelAiOperation(operationId: string): Promise<any> {
    return fetchJson(`/ai/operations/${operationId}`, {
        method: "DELETE",
    });
}
