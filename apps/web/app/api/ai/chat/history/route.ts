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

export async function GET(req: Request) {
  const token = await getToken();
  const { searchParams } = new URL(req.url);
  const limit = Number(searchParams.get("limit") ?? 80);
  try {
    const res = await fetch(`${PLATFORM_API_URL}/ai/chat/history?limit=${Math.max(1, Math.min(limit, 500))}`, {
      cache: "no-store",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ items: [] }, { status: 500 });
  }
}

export async function DELETE() {
  const token = await getToken();
  try {
    const res = await fetch(`${PLATFORM_API_URL}/ai/chat/history`, {
      method: "DELETE",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ deleted: 0 }, { status: 500 });
  }
}
