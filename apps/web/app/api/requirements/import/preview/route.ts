import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../../proxy";

export async function POST(request: Request) {
  const token = await getAuthToken();
  if (!token) {
    return unauthorizedResponse();
  }

  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json(
      { code: 40000, message: "请求体必须是 multipart/form-data" },
      { status: 400 },
    );
  }

  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/requirements/import/preview`, {
      method: "POST",
      headers: authHeaders(token),
      body: formData,
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "导入预览服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 导入预览服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
