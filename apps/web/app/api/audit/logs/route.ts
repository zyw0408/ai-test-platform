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

export async function GET(req: Request) {
  const token = await getToken();
  const { searchParams } = new URL(req.url);
  const qs = searchParams.toString();
  const path = `${PLATFORM_API_URL}/audit/logs${qs ? `?${qs}` : ""}`;
  try {
    const res = await fetch(path, {
      cache: "no-store",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    const data = await res.json().catch(() => ({ items: [] }));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ items: [] }, { status: 500 });
  }
}
