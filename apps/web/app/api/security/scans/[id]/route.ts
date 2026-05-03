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

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function DELETE(_: Request, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) {
    return NextResponse.json({ code: 40100, message: "未登录或登录已过期" }, { status: 401 });
  }

  const { id } = await context.params;
  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/security/scans/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      cache: "no-store",
    });
    if (backendRes.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    let data: unknown;
    try {
      data = await backendRes.json();
    } catch {
      data = { code: 50001, message: "安全报告删除服务返回了非 JSON 响应" };
    }
    return NextResponse.json(data, { status: backendRes.status });
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 安全报告删除服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
