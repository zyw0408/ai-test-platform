import { NextRequest, NextResponse } from "next/server";
import { 
  PLATFORM_API_URL, 
  getAuthToken, 
  authJsonHeaders, 
  toBackendJsonResponse, 
  unauthorizedResponse 
} from "../proxy";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const subPath = path.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${PLATFORM_API_URL}/testing/${subPath}${search}`;

  try {
    const backendRes = await fetch(targetUrl, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    const contentType = backendRes.headers.get("content-type") || "";
    const disposition = backendRes.headers.get("content-disposition");
    const isDownload = Boolean(disposition);
    if (!isDownload && contentType.includes("application/json")) {
      return toBackendJsonResponse(backendRes, "测试代理 GET 服务返回了非 JSON 响应");
    }
    const body = await backendRes.arrayBuffer();
    const headers = new Headers();
    headers.set("content-type", contentType || "application/octet-stream");
    if (disposition) headers.set("content-disposition", disposition);
    return new NextResponse(body, { status: backendRes.status, headers });
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Proxy Error: Service Unavailable" },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const subPath = path.join("/");
  const targetUrl = `${PLATFORM_API_URL}/testing/${subPath}`;

  // Handle FormData for OpenAPI import
  const contentType = request.headers.get("content-type");
  let body: any;
  let headers = authJsonHeaders(token);

  if (contentType?.includes("multipart/form-data")) {
    body = await request.formData();
    // Fetch will set the boundary automatically if we don't set Content-Type manually
    delete (headers as any)["Content-Type"];
  } else {
    try {
      body = await request.text();
    } catch {
      body = null;
    }
  }

  try {
    const backendRes = await fetch(targetUrl, {
      method: "POST",
      headers: headers,
      body: body,
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "测试代理 POST 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Proxy Error: Service Unavailable" },
      { status: 500 }
    );
  }
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const subPath = path.join("/");
  const targetUrl = `${PLATFORM_API_URL}/testing/${subPath}`;

  try {
    const body = await request.text();
    const backendRes = await fetch(targetUrl, {
      method: "PATCH",
      headers: authJsonHeaders(token),
      body: body,
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "测试代理 PATCH 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Proxy Error: Service Unavailable" },
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const token = await getAuthToken();
  if (!token) return unauthorizedResponse();

  const { path } = await context.params;
  const subPath = path.join("/");
  const targetUrl = `${PLATFORM_API_URL}/testing/${subPath}`;

  try {
    const backendRes = await fetch(targetUrl, {
      method: "DELETE",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    if (backendRes.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    return toBackendJsonResponse(backendRes, "测试代理 DELETE 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Proxy Error: Service Unavailable" },
      { status: 500 }
    );
  }
}
