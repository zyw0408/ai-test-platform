"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCcw } from "lucide-react";
import { getGlobalErrorViewModel } from "../lib/error-utils";

type ErrorPageProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function AppErrorPage({ error, reset }: ErrorPageProps) {
  useEffect(() => {
    console.error("App route error:", error);
  }, [error]);

  const view = getGlobalErrorViewModel(error);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "24px",
        background:
          "radial-gradient(1200px 600px at 12% -20%, rgba(26, 164, 123, 0.2), transparent 60%), radial-gradient(900px 500px at 100% 120%, rgba(15, 56, 93, 0.18), transparent 50%), var(--bg-main)",
      }}
    >
      <section
        className="glassboard"
        style={{
          maxWidth: "560px",
          width: "100%",
          padding: "28px",
          borderRadius: "20px",
          display: "grid",
          gap: "14px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <AlertTriangle size={20} color="#dc2626" />
          <strong style={{ fontSize: "1.1rem" }}>{view.title}</strong>
        </div>
        <p style={{ margin: 0, color: "var(--ink-soft)", lineHeight: 1.6 }}>
          {view.description}
        </p>
        {view.requestId ? (
          <div className="code" style={{ overflowX: "auto" }}>
            requestId: {view.requestId}
          </div>
        ) : null}
        <button
          type="button"
          onClick={reset}
          style={{
            marginTop: "8px",
            justifySelf: "start",
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            border: "none",
            cursor: "pointer",
            background: "var(--primary)",
            color: "#fff",
            borderRadius: "12px",
            padding: "10px 14px",
            fontWeight: 600,
          }}
        >
          <RefreshCcw size={16} />
          重试加载
        </button>
      </section>
    </main>
  );
}
