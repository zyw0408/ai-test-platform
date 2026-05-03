import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

export async function GET() {
  const cookieStore = await cookies();
  const token = cookieStore.get("ai_test_token")?.value;

  if (!token) {
    return NextResponse.json({ code: 40100, message: "未登录" }, { status: 401 });
  }

  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/auth/me`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
      cache: "no-store",
    });

    let data: unknown;
    try {
      data = await backendRes.json();
    } catch {
      data = { code: 50001, message: "认证服务返回了非 JSON 响应" };
    }

    return NextResponse.json(data, { status: backendRes.status });
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 认证服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
