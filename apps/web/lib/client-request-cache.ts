type CacheEntry<T> = {
  expiresAt: number;
  data: T;
};

const dataCache = new Map<string, CacheEntry<unknown>>();
const inflightCache = new Map<string, Promise<unknown>>();

export function invalidateClientRequestCache(keyOrPrefix: string) {
  const text = String(keyOrPrefix || "").trim();
  if (!text) return;
  for (const key of Array.from(dataCache.keys())) {
    if (key.startsWith(text)) {
      dataCache.delete(key);
    }
  }
  for (const key of Array.from(inflightCache.keys())) {
    if (key.startsWith(text)) {
      inflightCache.delete(key);
    }
  }
}

export async function fetchJsonWithClientCache<T>(
  url: string,
  options?: {
    ttlMs?: number;
    init?: RequestInit;
    key?: string;
    forceRefresh?: boolean;
  },
): Promise<T> {
  const ttlMs = Math.max(0, Number(options?.ttlMs ?? 10_000));
  const init = options?.init;
  const method = String(init?.method || "GET").toUpperCase();
  const key = options?.key || `${method}:${url}`;
  const now = Date.now();

  if (!options?.forceRefresh && method === "GET") {
    const cached = dataCache.get(key);
    if (cached && cached.expiresAt > now) {
      return cached.data as T;
    }
  }

  const inflight = inflightCache.get(key);
  if (inflight && !options?.forceRefresh) {
    return inflight as Promise<T>;
  }

  const promise = (async () => {
    const response = await fetch(url, { ...init, cache: "no-store" });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const message =
        (payload &&
        typeof payload === "object" &&
        (typeof (payload as { message?: unknown }).message === "string"
          ? String((payload as { message?: unknown }).message)
          : typeof (payload as { detail?: unknown }).detail === "string"
            ? String((payload as { detail?: unknown }).detail)
            : "")) ||
        `请求失败(${response.status})`;
      throw new Error(String(message));
    }
    if (method === "GET" && ttlMs > 0) {
      dataCache.set(key, {
        data: payload,
        expiresAt: Date.now() + ttlMs,
      });
    }
    return payload as T;
  })();

  inflightCache.set(key, promise);
  try {
    return await promise;
  } finally {
    inflightCache.delete(key);
  }
}

