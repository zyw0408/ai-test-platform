import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const PLATFORM_API_URL = process.env.PLATFORM_API_URL || "http://localhost:8000";

async function getToken() {
  const cookieStore = await cookies();
  return cookieStore.get("ai_test_token")?.value;
}

function authHeaders(token?: string) {
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

// GET /api/teams?orgId=xxx
export async function GET(req: Request) {
  const token = await getToken();
  
  try {
    // Backend canonical endpoint for team list is /teams/list.
    const res = await fetch(`${PLATFORM_API_URL}/teams/list`, {
      cache: "no-store",
      headers: authHeaders(token),
    });
    if (!res.ok) return NextResponse.json([], { status: res.status });
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json([], { status: 500 });
  }
}

// POST /api/teams — create team
export async function POST(req: Request) {
  const token = await getToken();
  const body = await req.json();
  
  try {
    const res = await fetch(`${PLATFORM_API_URL}/teams`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(err, { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
