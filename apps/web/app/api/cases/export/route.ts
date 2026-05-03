import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authJsonHeaders,
  getAuthToken,
  unauthorizedResponse,
} from "../proxy";

export async function GET(request: Request) {
  const token = await getAuthToken();
  if (!token) {
    return unauthorizedResponse();
  }
  const search = new URL(request.url).searchParams.toString();
  const path = `${PLATFORM_API_URL}/cases/export${search ? `?${search}` : ""}`;
  try {
    const backendRes = await fetch(path, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    const contentType = backendRes.headers.get("content-type") || "application/octet-stream";
    const disposition = backendRes.headers.get("content-disposition") || "";
    const body = await backendRes.arrayBuffer();
    const headers = new Headers();
    headers.set("content-type", contentType);
    if (disposition) headers.set("content-disposition", disposition);
    return new NextResponse(body, { status: backendRes.status, headers });
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 测试用例导出服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
