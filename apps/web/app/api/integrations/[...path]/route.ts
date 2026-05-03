import { NextRequest, NextResponse } from "next/server";
import {
  PLATFORM_API_URL,
  getAuthToken,
  authJsonHeaders,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../../testing/proxy";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const subPath = path.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${PLATFORM_API_URL}/integrations/${subPath}${search}`;

  try {
    const backendRes = await fetch(targetUrl, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "集成代理 GET 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Proxy Error: Service Unavailable" },
      { status: 500 },
    );
  }
}

export async function POST(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const subPath = path.join("/");
  const targetUrl = `${PLATFORM_API_URL}/integrations/${subPath}`;

  try {
    const body = await request.text();
    const backendRes = await fetch(targetUrl, {
      method: "POST",
      headers: authJsonHeaders(token),
      body,
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "集成代理 POST 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Proxy Error: Service Unavailable" },
      { status: 500 },
    );
  }
}
