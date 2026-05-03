import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authJsonHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../proxy";

export async function GET(request: Request) {
  const token = await getAuthToken();
  if (!token) {
    return unauthorizedResponse();
  }
  const search = new URL(request.url).searchParams.toString();
  const path = `${PLATFORM_API_URL}/testing/collections${search ? `?${search}` : ""}`;
  try {
    const backendRes = await fetch(path, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "接口集合列表服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 接口集合列表服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}

export async function POST(request: Request) {
  const token = await getAuthToken();
  if (!token) {
    return unauthorizedResponse();
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ code: 40000, message: "请求体必须是 JSON" }, { status: 400 });
  }
  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/testing/collections`, {
      method: "POST",
      headers: authJsonHeaders(token),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "创建接口集合服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 创建接口集合服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
