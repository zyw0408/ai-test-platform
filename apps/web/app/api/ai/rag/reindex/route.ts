import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

async function getToken() {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value;
}

export async function POST(req: Request) {
  const token = await getToken();
  if (!token) {
    return NextResponse.json({ error: "未登录或登录已过期" }, { status: 401 });
  }
  const body = await req.json().catch(() => ({}));
  try {
    const res = await fetch(`${PLATFORM_API_URL}/ai/rag/reindex`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error("AI RAG reindex proxy error:", error);
    return NextResponse.json({ error: "RAG 索引重建请求失败" }, { status: 500 });
  }
}

