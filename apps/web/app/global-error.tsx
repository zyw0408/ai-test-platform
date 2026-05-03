"use client";

import { AlertOctagon, RefreshCcw } from "lucide-react";
import { getGlobalErrorViewModel } from "../lib/error-utils";

type GlobalErrorPageProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function GlobalErrorPage({ error, reset }: GlobalErrorPageProps) {
  const view = getGlobalErrorViewModel(error);

  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: "24px",
          background:
            "radial-gradient(1200px 600px at 10% -20%, rgba(26, 164, 123, 0.2), transparent 55%), radial-gradient(900px 500px at 100% 120%, rgba(15, 56, 93, 0.2), transparent 50%), #f6f8fb",
          color: "#102a3c",
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, "Segoe UI", "PingFang SC", sans-serif',
        }}
      >
        <section
          style={{
            width: "100%",
            maxWidth: "560px",
            borderRadius: "18px",
            padding: "26px",
            background: "rgba(255,255,255,0.85)",
            boxShadow: "0 20px 50px rgba(15, 56, 93, 0.15)",
            border: "1px solid rgba(15, 56, 93, 0.12)",
            display: "grid",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <AlertOctagon size={20} color="#b91c1c" />
            <strong style={{ fontSize: "1.08rem" }}>{view.title}</strong>
          </div>
          <p style={{ margin: 0, lineHeight: 1.65, color: "#334155" }}>{view.description}</p>
          {view.requestId ? (
            <code
              style={{
                background: "#eef2ff",
                borderRadius: "10px",
                padding: "8px 10px",
                display: "inline-block",
                fontSize: "0.85rem",
              }}
            >
              requestId: {view.requestId}
            </code>
          ) : null}
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "8px",
              width: "fit-content",
              border: "none",
              borderRadius: "12px",
              padding: "10px 14px",
              background: "#0f766e",
              color: "#fff",
              cursor: "pointer",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <RefreshCcw size={16} />
            重新加载
          </button>
        </section>
      </body>
    </html>
  );
}
