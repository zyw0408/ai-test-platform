import { redirect } from "next/navigation";
import { readBackendErrorPayload, toPlatformApiErrorMessage } from "../error-utils";

const SERVER_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";
const CLIENT_API_BASE_PATH = "/api";

function toFriendlyMessage(status: number, backendMessage?: string): string {
  if (status === 429) return backendMessage || "请求过于频繁，请稍后重试。";
  if (status >= 500) return backendMessage || "服务暂时不可用，请稍后重试。";
  if (status >= 400) return backendMessage || "请求失败，请检查输入后重试。";
  return backendMessage || "请求失败";
}

async function getAuthTokenFromCookie(): Promise<string | null> {
  if (typeof window !== "undefined") {
    // Client-side: Read from document.cookie
    try {
      const match = document.cookie.match(/(^|;)\s*ai_test_token\s*=\s*([^;]+)/);
      return match ? decodeURIComponent(match[2]) : null;
    } catch {
      return null;
    }
  }

  // Server-side: Use next/headers
  try {
    const { cookies } = await import("next/headers");
    const cookieStore = await cookies();
    return cookieStore.get("ai_test_token")?.value ?? null;
  } catch {
    return null;
  }
}

function isServerSide(): boolean {
  return typeof window === "undefined";
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAuthTokenFromCookie();
  const headers = new Headers(init?.headers ?? {});
  
  const isFormDataBody = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (!isFormDataBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const isNextApiRoute = path.startsWith("/api/");
  let fetchUrl: string;
  
  if (isServerSide()) {
    fetchUrl = isNextApiRoute
      ? `${SERVER_API_URL}${path.replace("/api", "")}`
      : `${SERVER_API_URL}${path}`;
  } else {
    fetchUrl = isNextApiRoute ? path : `${CLIENT_API_BASE_PATH}${path}`;
  }

  let response: Response;
  try {
    response = await fetch(fetchUrl, {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new Error(toPlatformApiErrorMessage({
      status: 503,
      path,
      message: "无法连接后端服务，请确认服务已启动。",
    }));
  }

  if (response.status === 401 || response.status === 403) {
    redirect("/login");
  }
  if (!response.ok) {
    let responseData: unknown = null;
    try {
      responseData = await response.json();
    } catch {}
    const backend = readBackendErrorPayload(responseData);
    throw new Error(toPlatformApiErrorMessage({
      status: response.status,
      path,
      code: backend.code,
      requestId: backend.requestId,
      message: toFriendlyMessage(response.status, backend.message),
    }));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
