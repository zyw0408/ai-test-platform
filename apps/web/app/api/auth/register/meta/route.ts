import { NextResponse } from "next/server";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

export async function GET() {
  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/auth/register/meta`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });

    let data: unknown;
    try {
      data = await backendRes.json();
    } catch {
      data = { code: 50001, message: "注册配置服务返回了非 JSON 响应" };
    }
    return NextResponse.json(data, { status: backendRes.status });
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 注册配置服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}

