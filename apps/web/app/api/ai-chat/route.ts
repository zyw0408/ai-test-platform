import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";
const AI_PROXY_TIMEOUT_MS = Number(process.env.AI_PROXY_TIMEOUT_MS ?? 90000);

async function getToken() {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value;
}

export async function POST(req: Request) {
  const token = await getToken();
  const body = await req.json();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), AI_PROXY_TIMEOUT_MS);
  
  try {
    const res = await fetch(`${PLATFORM_API_URL}/ai/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!res.ok) {
      const backend = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: backend?.detail || backend?.message || backend?.error || "AI 服务请求失败" },
        { status: res.status },
      );
    }

    // 如果是流式请求，直接转发 SSE 流
    if (body.stream) {
      const stream = res.body;
      if (!stream) {
        return NextResponse.json({ error: "无响应体" }, { status: 500 });
      }
      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
      });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return NextResponse.json({ error: "AI 请求超时，请稍后重试" }, { status: 504 });
    }
    console.error("AI Chat proxy error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  } finally {
    clearTimeout(timeout);
  }
}
