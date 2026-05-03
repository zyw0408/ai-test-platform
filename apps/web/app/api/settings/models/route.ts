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
    const res = await fetch(`${PLATFORM_API_URL}/settings/models`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({ ok: false, message: "模型列表接口返回非 JSON 响应", models: [] }));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ ok: false, message: "获取模型列表失败（网关异常）", models: [] }, { status: 500 });
  }
}

