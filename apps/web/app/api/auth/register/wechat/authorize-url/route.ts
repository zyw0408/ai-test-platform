import { NextResponse } from "next/server";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const redirectUri = url.searchParams.get("redirectUri");
    const scope = url.searchParams.get("scope");

    if (!redirectUri) {
      return NextResponse.json(
        { code: 40007, message: "缺少 redirectUri" },
        { status: 400 },
      );
    }

    const backendUrl = new URL(`${PLATFORM_API_URL}/auth/register/wechat/authorize-url`);
    backendUrl.searchParams.set("redirectUri", redirectUri);
    if (scope) {
      backendUrl.searchParams.set("scope", scope);
    }
    const backendRes = await fetch(backendUrl, {
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
      data = { code: 50001, message: "微信授权地址服务返回了非 JSON 响应" };
    }
    return NextResponse.json(data, { status: backendRes.status });
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 微信授权地址服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}

