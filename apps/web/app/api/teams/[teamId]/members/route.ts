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

// GET /api/teams/[teamId]/members
export async function GET(
  req: Request,
  { params }: { params: Promise<{ teamId: string }> }
) {
  const token = await getToken();
  const { teamId } = await params;
  
  try {
    const res = await fetch(`${PLATFORM_API_URL}/teams/${teamId}/members`, {
      cache: "no-store",
      headers: authHeaders(token),
    });
    if (!res.ok) return NextResponse.json([], { status: res.status });
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json([], { status: 500 });
  }
}

// POST /api/teams/[teamId]/members — add member
export async function POST(
  req: Request,
  { params }: { params: Promise<{ teamId: string }> }
) {
  const token = await getToken();
  const { teamId } = await params;
  const body = await req.json();
  
  try {
    const res = await fetch(`${PLATFORM_API_URL}/teams/${teamId}/members`, {
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

// PATCH /api/teams/[teamId]/members/[memberId] — update role
export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ teamId: string }> }
) {
  const token = await getToken();
  const { teamId } = await params;
  const body = await req.json();
  const memberId = String(body?.memberId || "").trim();
  const role = String(body?.role || "").trim();
  if (!memberId || !role) {
    return NextResponse.json({ detail: "memberId 和 role 为必填项" }, { status: 400 });
  }

  try {
    const res = await fetch(`${PLATFORM_API_URL}/teams/${teamId}/members/${memberId}`, {
      method: "PATCH",
      headers: authHeaders(token),
      body: JSON.stringify({ role }),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}

// DELETE /api/teams/[teamId]/members/[memberId] — remove member
export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ teamId: string }> }
) {
  const token = await getToken();
  const { teamId } = await params;
  const { searchParams } = new URL(req.url);
  const memberId = searchParams.get("memberId") || "";
  if (!memberId) {
    return NextResponse.json({ detail: "memberId 为必填项" }, { status: 400 });
  }
  try {
    const res = await fetch(`${PLATFORM_API_URL}/teams/${teamId}/members/${memberId}`, {
      method: "DELETE",
      headers: authHeaders(token),
    });
    if (res.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
