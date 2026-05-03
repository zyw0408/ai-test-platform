import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authJsonHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../../../proxy";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
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
  const { id } = await params;
  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/testing/collections/${id}/run`, {
      method: "POST",
      headers: authJsonHeaders(token),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "批量运行接口集合服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 批量运行接口集合服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
