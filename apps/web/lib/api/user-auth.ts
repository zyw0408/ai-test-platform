import { fetchJson } from "./client";

export async function getCurrentUser(): Promise<any> {
    return fetchJson("/users/me");
}

export async function getSettings(): Promise<any> {
    return fetchJson("/settings");
}

export async function saveSettings(settings: any): Promise<any> {
    return fetchJson("/settings", {
        method: "POST",
        body: JSON.stringify({ settings }),
    });
}

export async function updateProfile(data: any): Promise<any> {
    return fetchJson("/auth/profile", {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function listUsers(): Promise<any> {
    return fetchJson("/users");
}

export async function listTeams(): Promise<any> {
    return fetchJson("/teams");
}

export async function getCurrentTeam(): Promise<any> {
    return fetchJson("/teams/current");
}

export async function switchTeam(teamId: string): Promise<any> {
    return fetchJson(`/teams/switch/${teamId}`, {
        method: "POST",
    });
}
