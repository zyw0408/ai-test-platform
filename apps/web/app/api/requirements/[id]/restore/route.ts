import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../../proxy";

export async function POST(
  _: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = await getAuthToken();
  if (!token) {
    return unauthorizedResponse();
  }

  const { id } = await params;
  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/requirements/${id}/restore`, {
      method: "POST",
      headers: authHeaders(token),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "恢复需求服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 恢复需求服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
