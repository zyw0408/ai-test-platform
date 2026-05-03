type WechatErrorPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function WechatRegisterErrorPage({
  searchParams,
}: WechatErrorPageProps) {
  const params = (await searchParams) ?? {};
  const raw = params.message;
  const message = Array.isArray(raw) ? raw[0] : raw;

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "24px",
        background:
          "radial-gradient(1200px 600px at 5% -20%, rgba(220,38,38,0.12), transparent 60%), radial-gradient(900px 500px at 100% 120%, rgba(15,56,93,0.12), transparent 50%), var(--bg-main)",
      }}
    >
      <section
        className="glassboard"
        style={{
          width: "100%",
          maxWidth: "460px",
          padding: "28px",
          borderRadius: "22px",
          display: "grid",
          gap: "14px",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.4rem", color: "var(--ink)" }}>
          微信注册失败
        </h1>
        <p style={{ margin: 0, color: "var(--ink-soft)", lineHeight: 1.6 }}>
          {message || "授权信息已失效或校验失败，请重新发起微信授权。"}
        </p>
        <div style={{ display: "flex", gap: "10px", marginTop: "6px" }}>
          <a
            href="/register"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "12px",
              padding: "11px 14px",
              border: "1px solid var(--line)",
              color: "var(--ink)",
              textDecoration: "none",
              fontWeight: 600,
              flex: 1,
            }}
          >
            返回注册页
          </a>
          <a
            href="/login"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "12px",
              padding: "11px 14px",
              border: "none",
              background: "var(--primary)",
              color: "white",
              textDecoration: "none",
              fontWeight: 700,
              flex: 1,
            }}
          >
            去登录
          </a>
        </div>
      </section>
    </main>
  );
}

