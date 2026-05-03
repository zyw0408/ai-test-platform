import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL = process.env.PLATFORM_API_URL || "http://localhost:8000";

async function getToken() {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value;
}

function authHeaders(token?: string) {
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function POST(req: Request) {
  const token = await getToken();
  try {
    const body = await req.json().catch(() => ({}));
    const res = await fetch(`${PLATFORM_API_URL}/settings/test-model`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({ ok: false, message: "模型测试返回非 JSON 响应" }));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ ok: false, message: "模型连接测试失败（网关异常）" }, { status: 500 });
  }
}

