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

// GET /api/reports/dashboard?projectId=xxx
export async function GET(req: Request) {
  const token = await getToken();
  const { searchParams } = new URL(req.url);
  const projectId = searchParams.get("projectId") || "";
  
  const qs = projectId ? `?projectId=${projectId}` : "";
  
  try {
    const url = `${PLATFORM_API_URL}/reports/dashboard${qs}`;
    console.log(`[Proxy] GET ${url}`);
    const res = await fetch(url, {
      cache: "no-store",
      headers: authHeaders(token),
    });
    console.log(`[Proxy] Response: ${res.status} ${res.statusText}`);
    if (!res.ok) {
      if (res.status === 404) {
        // Log additional info for 404
        console.error(`[Proxy] 404 Not Found from Backend at ${url}`);
      }
      return NextResponse.json({
        totalRuns: 0, passedRuns: 0, failedRuns: 0, passRate: 0,
        totalCases: 0, totalProjects: 0, recentRuns: [], moduleCoverage: [],
      }, { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch (err: any) {
    console.error(`[Proxy] Error fetching from backend: ${err.message}`);
    return NextResponse.json({
      totalRuns: 0, passedRuns: 0, failedRuns: 0, passRate: 0,
      totalCases: 0, totalProjects: 0, recentRuns: [], moduleCoverage: [],
    }, { status: 500 });
  }
}
