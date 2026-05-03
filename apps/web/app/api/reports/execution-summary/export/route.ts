import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL = process.env.PLATFORM_API_URL || "http://localhost:8000";

async function getToken() {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value;
}

function authHeaders(token?: string) {
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function GET(req: Request) {
  const token = await getToken();
  const search = new URL(req.url).searchParams.toString();
  const qs = search ? `?${search}` : "";
  try {
    const res = await fetch(`${PLATFORM_API_URL}/reports/execution-summary/export${qs}`, {
      cache: "no-store",
      headers: authHeaders(token),
    });
    const contentType = res.headers.get("content-type") || "application/octet-stream";
    const disposition = res.headers.get("content-disposition") || "";
    const body = await res.arrayBuffer();
    const headers = new Headers();
    headers.set("content-type", contentType);
    if (disposition) headers.set("content-disposition", disposition);
    return new NextResponse(body, { status: res.status, headers });
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 报告导出服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
