export const API_ERROR_PREFIX = "__PLATFORM_API_ERROR__";

export type PlatformApiErrorPayload = {
  status: number;
  path: string;
  code?: number;
  message: string;
  requestId?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function toPlatformApiErrorMessage(payload: PlatformApiErrorPayload): string {
  return `${API_ERROR_PREFIX}${JSON.stringify(payload)}`;
}

export function parsePlatformApiErrorPayload(
  error: unknown,
): PlatformApiErrorPayload | null {
  if (!(error instanceof Error)) {
    return null;
  }
  if (!error.message.startsWith(API_ERROR_PREFIX)) {
    return null;
  }
  const payloadRaw = error.message.slice(API_ERROR_PREFIX.length);
  try {
    const parsed = JSON.parse(payloadRaw) as unknown;
    if (!isRecord(parsed)) {
      return null;
    }
    if (typeof parsed.message !== "string" || typeof parsed.path !== "string") {
      return null;
    }
    return {
      status: typeof parsed.status === "number" ? parsed.status : 500,
      path: parsed.path,
      code: typeof parsed.code === "number" ? parsed.code : undefined,
      message: parsed.message,
      requestId: typeof parsed.requestId === "string" ? parsed.requestId : undefined,
    };
  } catch {
    return null;
  }
}

export function getGlobalErrorViewModel(error: unknown): {
  title: string;
  description: string;
  requestId?: string;
} {
  const parsed = parsePlatformApiErrorPayload(error);
  if (!parsed) {
    return {
      title: "页面加载异常",
      description: "请求处理中断，请刷新重试。如果持续出现，请联系管理员。",
    };
  }
  if (parsed.status === 429) {
    return {
      title: "请求过于频繁",
      description: parsed.message,
      requestId: parsed.requestId,
    };
  }
  if (parsed.status >= 500) {
    return {
      title: "后端服务暂不可用",
      description: parsed.message,
      requestId: parsed.requestId,
    };
  }
  return {
    title: "请求失败",
    description: parsed.message,
    requestId: parsed.requestId,
  };
}

export function readBackendErrorPayload(value: unknown): {
  code?: number;
  message?: string;
  requestId?: string;
} {
  if (!isRecord(value)) {
    return {};
  }
  const code = typeof value.code === "number" ? value.code : undefined;
  const message = typeof value.message === "string" ? value.message : undefined;
  const requestId =
    typeof value.requestId === "string" ? value.requestId : undefined;
  return { code, message, requestId };
}
