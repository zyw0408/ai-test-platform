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

export async function GET(req: Request) {
  const token = await getToken();
  const search = new URL(req.url).searchParams.toString();
  const qs = search ? `?${search}` : "";
  try {
    const res = await fetch(`${PLATFORM_API_URL}/reports/execution-summary${qs}`, {
      cache: "no-store",
      headers: authHeaders(token),
    });
    if (!res.ok) {
      return NextResponse.json(
        { totalRuns: 0, passRate: 0, statusBreakdown: {}, runnerBreakdown: {}, topFailedCases: [], trends: [] },
        { status: res.status },
      );
    }
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json(
      { totalRuns: 0, passRate: 0, statusBreakdown: {}, runnerBreakdown: {}, topFailedCases: [], trends: [] },
      { status: 500 },
    );
  }
}
