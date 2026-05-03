import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authJsonHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../proxy";

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

  const url = new URL(request.url);
  const hard = url.searchParams.get("hard");
  const queryString = hard ? `?hard=${hard}` : "";

  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/cases/batch-delete${queryString}`, {
      method: "POST",
      headers: authJsonHeaders(token),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "批量删除测试用例服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 批量删除测试用例服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
