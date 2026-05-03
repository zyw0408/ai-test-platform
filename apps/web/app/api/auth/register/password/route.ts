import { NextResponse } from "next/server";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";
const AUTH_COOKIE_MAX_AGE_SECONDS = Number(
  process.env.AUTH_COOKIE_MAX_AGE_SECONDS ?? 60 * 60 * 12,
);

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const requestUrl = new URL(request.url);
    const shouldUseSecureCookie =
      process.env.AUTH_COOKIE_SECURE === "true" ||
      requestUrl.protocol === "https:" ||
      request.headers.get("x-forwarded-proto") === "https";

    const backendRes = await fetch(`${PLATFORM_API_URL}/auth/register/password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    let data: unknown;
    try {
      data = await backendRes.json();
    } catch {
      data = { code: 50001, message: "注册服务返回了非 JSON 响应" };
    }
    const response = NextResponse.json(data, { status: backendRes.status });

    const parsed = data as { code?: number; data?: { token?: string } };
    if (backendRes.ok && parsed?.code === 0 && parsed?.data?.token) {
      response.cookies.set("ai_test_token", parsed.data.token, {
        httpOnly: true,
        sameSite: "lax",
        secure: shouldUseSecureCookie,
        path: "/",
        maxAge: AUTH_COOKIE_MAX_AGE_SECONDS,
      });
    } else {
      response.cookies.set("ai_test_token", "", {
        httpOnly: true,
        sameSite: "lax",
        secure: shouldUseSecureCookie,
        path: "/",
        maxAge: 0,
      });
    }

    return response;
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 注册服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
