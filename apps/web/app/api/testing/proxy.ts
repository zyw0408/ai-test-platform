import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

export async function getAuthToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value ?? null;
}

export function unauthorizedResponse() {
  return NextResponse.json({ code: 40100, message: "未登录或登录已过期" }, { status: 401 });
}

export async function toBackendJsonResponse(
  backendRes: Response,
  fallbackMessage: string,
): Promise<NextResponse> {
  let data: unknown;
  try {
    data = await backendRes.json();
  } catch {
    data = { code: 50001, message: fallbackMessage };
  }
  return NextResponse.json(data, { status: backendRes.status });
}

export function authJsonHeaders(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

export function authHeaders(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
  };
}
