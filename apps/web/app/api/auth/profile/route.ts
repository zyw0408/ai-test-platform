import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL ??
  process.env.NEXT_PUBLIC_PLATFORM_API_URL ??
  "http://127.0.0.1:8000";

async function getToken() {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value ?? null;
}

export async function PUT(req: Request) {
  const token = await getToken();
  if (!token) {
    return NextResponse.json({ code: 40100, message: "未登录" }, { status: 401 });
  }

  try {
    const body = await req.json();
    const res = await fetch(`${PLATFORM_API_URL}/auth/profile`, {
      method: "PUT",
      headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) return NextResponse.json({ error: "Failed to update profile" }, { status: res.status });
    const data = await res.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
