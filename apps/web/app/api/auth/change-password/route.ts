import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get("ai_test_token")?.value;

  if (!token) {
    return NextResponse.json({ detail: "未登录" }, { status: 401 });
  }

  try {
    const body = await request.json();
    const backendRes = await fetch(`${PLATFORM_API_URL}/auth/change-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });

    let data: unknown;
    try {
      data = await backendRes.json();
    } catch {
      data = { detail: "认证服务返回了非 JSON 响应" };
    }

    return NextResponse.json(data, { status: backendRes.status });
  } catch {
    return NextResponse.json({ detail: "修改密码请求失败" }, { status: 500 });
  }
}
