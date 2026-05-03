import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

async function getAuthToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value ?? null;
}

async function toBackendJsonResponse(
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

export async function GET(request: Request) {
  const token = await getAuthToken();
  if (!token) {
    return NextResponse.json({ code: 40100, message: "未登录或登录已过期" }, { status: 401 });
  }
  const url = new URL(request.url);
  const projectId = url.searchParams.get("projectId") || "";
  const status = url.searchParams.get("status") || "";
  const severity = url.searchParams.get("severity") || "";
  const limit = url.searchParams.get("limit") || "100";

  try {
    const backendRes = await fetch(
      `${PLATFORM_API_URL}/security/findings?projectId=${encodeURIComponent(projectId)}&status=${encodeURIComponent(status)}&severity=${encodeURIComponent(severity)}&limit=${encodeURIComponent(limit)}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        cache: "no-store",
      },
    );
    return toBackendJsonResponse(backendRes, "安全漏洞列表服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 安全漏洞列表服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
