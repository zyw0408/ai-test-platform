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
  const path = `${PLATFORM_API_URL}/requirements/search${search ? `?${search}` : ""}`;
  try {
    const backendRes = await fetch(path, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "需求搜索服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 需求搜索服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
