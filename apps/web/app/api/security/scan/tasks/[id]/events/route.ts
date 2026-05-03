import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

export async function GET(_: Request, context: { params: Promise<{ id: string }> }) {
  const cookieStore = await cookies();
  const token = cookieStore.get("ai_test_token")?.value ?? null;
  if (!token) {
    return NextResponse.json({ code: 40100, message: "未登录或登录已过期" }, { status: 401 });
  }

  const { id } = await context.params;
  const backendRes = await fetch(`${PLATFORM_API_URL}/security/scan/tasks/${encodeURIComponent(id)}/events`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    cache: "no-store",
  });

  if (!backendRes.ok || !backendRes.body) {
    let payload: unknown = null;
    try {
      payload = await backendRes.json();
    } catch {
      payload = { code: 50001, message: "安全扫描事件流服务返回异常" };
    }
    return NextResponse.json(payload, { status: backendRes.status || 500 });
  }

  return new NextResponse(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
