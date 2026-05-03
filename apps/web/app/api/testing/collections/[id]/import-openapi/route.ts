import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authHeaders,
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
  const formData = await request.formData();
  const file = formData.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ code: 40000, message: "file 字段缺失" }, { status: 400 });
  }
  const payload = new FormData();
  payload.append("file", file);
  const { id } = await params;
  try {
    const backendRes = await fetch(
      `${PLATFORM_API_URL}/api-testing/collections/${id}/import-openapi`,
      {
        method: "POST",
        headers: authHeaders(token),
        body: payload,
        cache: "no-store",
      },
    );
    return toBackendJsonResponse(backendRes, "导入 OpenAPI 服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 导入 OpenAPI 服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
