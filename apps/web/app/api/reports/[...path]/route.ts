import { NextRequest, NextResponse } from "next/server";
import {
  PLATFORM_API_URL,
  authJsonHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../proxy";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function buildTargetUrl(request: NextRequest, subPath: string): string {
  const search = request.nextUrl.search;
  return `${PLATFORM_API_URL}/reports/${subPath}${search}`;
}

export async function GET(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const targetUrl = buildTargetUrl(request, path.join("/"));
  try {
    const backendRes = await fetch(targetUrl, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "报告代理 GET 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json({ code: 50000, message: "API Proxy Error: Service Unavailable" }, { status: 500 });
  }
}

export async function POST(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const targetUrl = `${PLATFORM_API_URL}/reports/${path.join("/")}`;
  try {
    const body = await request.text();
    const backendRes = await fetch(targetUrl, {
      method: "POST",
      headers: authJsonHeaders(token),
      body,
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "报告代理 POST 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json({ code: 50000, message: "API Proxy Error: Service Unavailable" }, { status: 500 });
  }
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const targetUrl = `${PLATFORM_API_URL}/reports/${path.join("/")}`;
  try {
    const body = await request.text();
    const backendRes = await fetch(targetUrl, {
      method: "PATCH",
      headers: authJsonHeaders(token),
      body,
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "报告代理 PATCH 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json({ code: 50000, message: "API Proxy Error: Service Unavailable" }, { status: 500 });
  }
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const targetUrl = `${PLATFORM_API_URL}/reports/${path.join("/")}`;
  try {
    const backendRes = await fetch(targetUrl, {
      method: "DELETE",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    if (backendRes.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    return toBackendJsonResponse(backendRes, "报告代理 DELETE 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json({ code: 50000, message: "API Proxy Error: Service Unavailable" }, { status: 500 });
  }
}
