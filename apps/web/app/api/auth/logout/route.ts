import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get("ai_test_token")?.value;
  const requestUrl = new URL(request.url);
  const shouldUseSecureCookie =
    process.env.AUTH_COOKIE_SECURE === "true" ||
    requestUrl.protocol === "https:" ||
    request.headers.get("x-forwarded-proto") === "https";

  if (token) {
    try {
      await fetch(`${PLATFORM_API_URL}/auth/logout`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        cache: "no-store",
      });
    } catch {
      // Ignore backend availability issues for logout and clear cookie anyway.
    }
  }

  const response = NextResponse.json({ code: 0, message: "退出成功" });
  response.cookies.set("ai_test_token", "", {
    httpOnly: true,
    sameSite: "lax",
    secure: shouldUseSecureCookie,
    path: "/",
    maxAge: 0,
  });
  return response;
}
