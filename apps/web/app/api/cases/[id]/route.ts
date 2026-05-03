import { NextResponse } from "next/server";

import {
  PLATFORM_API_URL,
  authHeaders,
  authJsonHeaders,
  getAuthToken,
  toBackendJsonResponse,
  unauthorizedResponse,
} from "../proxy";

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
    const backendRes = await fetch(`${PLATFORM_API_URL}/cases/${id}`, {
      method: "GET",
      headers: authJsonHeaders(token),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "测试用例详情服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 测试用例详情服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}

export async function PATCH(
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
    const backendRes = await fetch(`${PLATFORM_API_URL}/cases/${id}`, {
      method: "PATCH",
      headers: authJsonHeaders(token),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return toBackendJsonResponse(backendRes, "更新测试用例服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 更新测试用例服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = await getAuthToken();
  if (!token) {
    return unauthorizedResponse();
  }

  const { id } = await params;
  const url = new URL(request.url);
  const hard = url.searchParams.get("hard");
  const queryString = hard ? `?hard=${hard}` : "";
  try {
    const backendRes = await fetch(`${PLATFORM_API_URL}/cases/${id}${queryString}`, {
      method: "DELETE",
      headers: authHeaders(token),
      cache: "no-store",
    });
    if (backendRes.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    return toBackendJsonResponse(backendRes, "删除测试用例服务返回了非 JSON 响应");
  } catch {
    return NextResponse.json(
      { code: 50000, message: "API Gateway: 删除测试用例服务不可用或网络受阻" },
      { status: 500 },
    );
  }
}
