import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authJsonHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../../../proxy";

export async function GET(
  _: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = await getAuthToken();
  if (!token) {
    return unauthorizedResponse();
  }
  const { id } = await params;
  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/api-testing/collections/${id}/requests`, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "接口请求列表服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 接口请求列表服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
