"use client";

import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import {
  ArrowRight,
  Lock,
  MessageCircle,
  QrCode,
  Smartphone,
  User,
} from "lucide-react";

type RegisterMethod = "phone" | "wechat";
type SmsMode = "test" | "provider" | string;
type RegisterMeta = {
  sms?: {
    mode?: SmsMode;
    provider?: string;
    ttlSeconds?: number;
    cooldownSeconds?: number;
    dailyLimit?: number;
    testCode?: string | null;
  };
  wechat?: {
    oauthEnabled?: boolean;
    stateTtlSeconds?: number;
  };
};
const WECHAT_REGISTER_SCOPE =
  process.env.NEXT_PUBLIC_WECHAT_REGISTER_SCOPE ?? "snsapi_userinfo";

export default function RegisterPage() {
  const [method, setMethod] = useState<RegisterMethod>("phone");
  const [registerMeta, setRegisterMeta] = useState<RegisterMeta | null>(null);
  const [metaLoading, setMetaLoading] = useState(true);

  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");

  const [phoneLoading, setPhoneLoading] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [phoneErrorText, setPhoneErrorText] = useState("");
  const [phoneSuccessText, setPhoneSuccessText] = useState("");

  const [wechatCode, setWechatCode] = useState("");
  const [wechatNickname, setWechatNickname] = useState("");
  const [wechatAvatarUrl, setWechatAvatarUrl] = useState("");
  const [wechatState, setWechatState] = useState("");
  const [wechatLoading, setWechatLoading] = useState(false);
  const [wechatErrorText, setWechatErrorText] = useState("");
  const [wechatHint, setWechatHint] = useState("");
  const [wechatAutoTried, setWechatAutoTried] = useState(false);

  const smsMode = registerMeta?.sms?.mode ?? "test";
  const smsTestCode = registerMeta?.sms?.testCode ?? null;
  const isSmsTestMode = smsMode === "test";
  const wechatOAuthEnabled = Boolean(registerMeta?.wechat?.oauthEnabled);

  const getSafeNextPath = useCallback(() => {
    const raw = new URLSearchParams(window.location.search).get("next");
    if (!raw) {
      return null;
    }
    if (!raw.startsWith("/") || raw.startsWith("//")) {
      return null;
    }
    return raw;
  }, []);

  useEffect(() => {
    if (countdown <= 0) {
      return;
    }
    const timer = window.setTimeout(() => setCountdown((prev) => prev - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown]);

  useEffect(() => {
    const loadMeta = async () => {
      setMetaLoading(true);
      try {
        const res = await fetch("/api/auth/register/meta", { cache: "no-store" });
        const json = await res.json();
        if (json?.code === 0) {
          setRegisterMeta((json?.data ?? null) as RegisterMeta | null);
        }
      } catch {
        // Ignore meta load failure and fallback to default test-mode hints.
      } finally {
        setMetaLoading(false);
      }
    };
    void loadMeta();
  }, []);

  const handleSendCode = async () => {
    if (!phone.trim()) {
      setPhoneErrorText("请先填写手机号");
      return;
    }
    setSendingCode(true);
    setPhoneErrorText("");
    setPhoneSuccessText("");
    try {
      const res = await fetch("/api/auth/register/sms/send-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      const json = await res.json();
      if (json.code === 0) {
        const cooldown = Number(json?.data?.cooldownSeconds ?? 60);
        setCountdown(Number.isFinite(cooldown) && cooldown > 0 ? cooldown : 60);
        if (isSmsTestMode && smsTestCode) {
          setPhoneSuccessText(
            `测试模式已启用，当前固定验证码为 ${smsTestCode}（请勿填写错误码 40105）`,
          );
        } else {
          setPhoneSuccessText(`验证码已发送到 ${json?.data?.phone ?? "你的手机号"}`);
        }
      } else {
        setPhoneErrorText(json.message ?? "发送验证码失败");
      }
    } catch {
      setPhoneErrorText("验证码服务不可用，请稍后重试");
    } finally {
      setSendingCode(false);
    }
  };

  const redirectAfterAuth = useCallback(() => {
    const nextPath = getSafeNextPath();
    window.location.assign(nextPath ?? "/");
  }, [getSafeNextPath]);

  const handlePhoneRegister = async (event: React.FormEvent) => {
    event.preventDefault();
    setPhoneLoading(true);
    setPhoneErrorText("");
    setPhoneSuccessText("");

    try {
      const res = await fetch("/api/auth/register/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone,
          code,
          password,
          nickname: nickname || undefined,
        }),
      });
      const json = await res.json();
      if (json.code === 0) {
        redirectAfterAuth();
        return;
      }
      setPhoneErrorText(json.message ?? "注册失败");
    } catch {
      setPhoneErrorText("注册服务不可用，请稍后重试");
    } finally {
      setPhoneLoading(false);
    }
  };

  const handleWechatRegister = useCallback(async (
    value?: string,
    stateValue?: string,
    fromCallback = false,
  ) => {
    const codeValue = (value ?? wechatCode).trim();
    const stateText = (stateValue ?? wechatState).trim();
    if (!codeValue) {
      setWechatErrorText("缺少微信授权 code");
      return;
    }
    if (!stateText) {
      setWechatErrorText("缺少微信授权 state，请点击“去微信授权注册”重新获取");
      return;
    }
    setWechatLoading(true);
    setWechatErrorText("");
    setWechatHint("");
    try {
      const res = await fetch("/api/auth/register/wechat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          wechatCode: codeValue,
          wechatState: stateText,
          nextPath: getSafeNextPath() ?? undefined,
          wechatNickname: wechatNickname || undefined,
          wechatAvatarUrl: wechatAvatarUrl || undefined,
        }),
      });
      const json = await res.json();
      if (json.code === 0) {
        setWechatHint("微信注册成功，正在进入工作台...");
        redirectAfterAuth();
        return;
      }
      const message = json.message ?? "微信注册失败";
      if (fromCallback) {
        const errorUrl = new URL("/register/wechat-error", window.location.origin);
        errorUrl.searchParams.set("message", message);
        window.location.assign(errorUrl.toString());
        return;
      }
      setWechatErrorText(message);
    } catch {
      if (fromCallback) {
        const errorUrl = new URL("/register/wechat-error", window.location.origin);
        errorUrl.searchParams.set("message", "微信注册服务不可用，请稍后重试");
        window.location.assign(errorUrl.toString());
        return;
      }
      setWechatErrorText("微信注册服务不可用，请稍后重试");
    } finally {
      setWechatLoading(false);
    }
  }, [
    getSafeNextPath,
    redirectAfterAuth,
    wechatAvatarUrl,
    wechatCode,
    wechatNickname,
    wechatState,
  ]);

  const startWechatAuthorize = async () => {
    if (!wechatOAuthEnabled) {
      setWechatErrorText("当前环境未开启微信 OAuth，请联系管理员配置");
      return;
    }

    const callbackUrl = new URL("/register", window.location.origin);
    const nextPath = getSafeNextPath();
    if (nextPath) {
      callbackUrl.searchParams.set("next", nextPath);
    }

    try {
      const authorizeRes = await fetch(
        `/api/auth/register/wechat/authorize-url?redirectUri=${encodeURIComponent(
          callbackUrl.toString(),
        )}&scope=${encodeURIComponent(WECHAT_REGISTER_SCOPE)}`,
        { cache: "no-store" },
      );
      const authorizeJson = await authorizeRes.json();
      if (authorizeJson?.code !== 0) {
        setWechatErrorText(authorizeJson?.message ?? "获取微信授权地址失败");
        return;
      }
      const authorizeUrl = authorizeJson?.data?.authorizeUrl as string | undefined;
      if (!authorizeUrl) {
        setWechatErrorText("微信授权地址为空");
        return;
      }
      window.location.assign(authorizeUrl);
    } catch {
      setWechatErrorText("微信授权地址服务不可用，请稍后重试");
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const callbackCode = params.get("code");
    const callbackState = params.get("state");
    if (callbackCode && !wechatAutoTried) {
      setMethod("wechat");
      setWechatCode(callbackCode);
      if (callbackState) {
        setWechatState(callbackState);
      }
      setWechatHint("检测到微信回调 code，正在尝试注册...");
      setWechatAutoTried(true);
      void handleWechatRegister(callbackCode, callbackState ?? "", true);
    }
  }, [handleWechatRegister, wechatAutoTried]);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "24px",
        background:
          "radial-gradient(1200px 600px at 5% -20%, rgba(26,164,123,0.2), transparent 60%), radial-gradient(900px 500px at 100% 120%, rgba(15,56,93,0.15), transparent 50%), var(--bg-main)",
      }}
    >
      <section
        className="glassboard"
        style={{
          width: "100%",
          maxWidth: "420px",
          padding: "28px",
          borderRadius: "22px",
          display: "grid",
          gap: "14px",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: "8px" }}>
          <div className="brand-mark" style={{ width: "48px", height: "48px", fontSize: "1.1rem", margin: "0 auto 12px" }}>
            AI
          </div>
          <h1 style={{ margin: 0, fontSize: "1.45rem", color: "var(--ink)" }}>创建账号</h1>
          <p style={{ margin: "8px 0 0", color: "var(--ink-soft)", fontSize: "0.9rem" }}>
            注册成功后自动登录进入工作台
          </p>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "8px",
            background: "var(--panel-strong)",
            padding: "4px",
            borderRadius: "12px",
            border: "1px solid var(--line)",
          }}
        >
          <button
            type="button"
            onClick={() => setMethod("phone")}
            style={method === "phone" ? tabButtonActive : tabButtonIdle}
          >
            手机号注册
          </button>
          <button
            type="button"
            onClick={() => setMethod("wechat")}
            style={method === "wechat" ? tabButtonActive : tabButtonIdle}
          >
            微信注册
          </button>
        </div>

        {method === "phone" ? (
          <form onSubmit={handlePhoneRegister} style={{ display: "grid", gap: "12px" }}>
            <div style={{ position: "relative" }}>
              <Smartphone
                size={16}
                style={{
                  position: "absolute",
                  left: "14px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--ink-soft)",
                }}
              />
              <input
                required
                type="text"
                name="username"
                autoComplete="username"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="手机号"
                style={inputStyle}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "10px" }}>
              <input
                required
                type="text"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder={isSmsTestMode ? "测试验证码（例如 123456）" : "短信验证码"}
                style={{ ...inputStyle, paddingLeft: "14px" }}
              />
              <button
                type="button"
                onClick={() => void handleSendCode()}
                disabled={sendingCode || countdown > 0}
                style={{
                  border: "none",
                  borderRadius: "12px",
                  padding: "0 14px",
                  cursor: sendingCode || countdown > 0 ? "not-allowed" : "pointer",
                  background: "var(--primary-alpha-10)",
                  color: "var(--primary)",
                  fontWeight: 600,
                  opacity: sendingCode || countdown > 0 ? 0.7 : 1,
                  whiteSpace: "nowrap",
                }}
              >
                {countdown > 0 ? `${countdown}s` : sendingCode ? "发送中..." : "获取验证码"}
              </button>
            </div>

            <div
              style={{
                borderRadius: "10px",
                padding: "9px 12px",
                fontSize: "0.82rem",
                lineHeight: 1.5,
                background: "var(--primary-alpha-10)",
                color: "var(--ink-soft)",
              }}
            >
              {metaLoading
                ? "正在加载验证码模式..."
                : isSmsTestMode
                  ? `当前为测试模式：验证码使用固定值 ${smsTestCode ?? "123456"}。请不要填写错误码（例如 40105）。`
                  : "当前为生产模式：验证码由短信服务下发，请填写手机收到的 6 位数字。"}
            </div>

            <div style={{ position: "relative" }}>
              <Lock
                size={16}
                style={{
                  position: "absolute",
                  left: "14px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--ink-soft)",
                }}
              />
              <input
                required
                type="password"
                name="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="设置密码（至少 6 位）"
                style={inputStyle}
              />
            </div>

            <div style={{ position: "relative" }}>
              <User
                size={16}
                style={{
                  position: "absolute",
                  left: "14px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--ink-soft)",
                }}
              />
              <input
                type="text"
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                placeholder="昵称（可选）"
                style={inputStyle}
              />
            </div>

            {phoneErrorText ? (
              <div style={{ color: "#dc2626", fontSize: "0.86rem", fontWeight: 600 }}>{phoneErrorText}</div>
            ) : null}
            {phoneSuccessText ? (
              <div style={{ color: "#0f766e", fontSize: "0.86rem", fontWeight: 600 }}>{phoneSuccessText}</div>
            ) : null}

            <button
              type="submit"
              disabled={phoneLoading}
              style={{
                marginTop: "6px",
                width: "100%",
                border: "none",
                borderRadius: "12px",
                padding: "13px 14px",
                fontWeight: 700,
                cursor: phoneLoading ? "not-allowed" : "pointer",
                background: "var(--primary)",
                color: "white",
                opacity: phoneLoading ? 0.7 : 1,
                display: "inline-flex",
                justifyContent: "center",
                alignItems: "center",
                gap: "8px",
              }}
            >
              {phoneLoading ? "注册中..." : "完成注册"}
              {!phoneLoading ? <ArrowRight size={16} /> : null}
            </button>
          </form>
        ) : (
          <section style={{ display: "grid", gap: "12px" }}>
            <button
              type="button"
              onClick={() => void startWechatAuthorize()}
              disabled={!wechatOAuthEnabled}
              style={{
                width: "100%",
                border: "none",
                borderRadius: "12px",
                padding: "12px 14px",
                fontWeight: 700,
                cursor: wechatOAuthEnabled ? "pointer" : "not-allowed",
                background: "#07c160",
                color: "white",
                opacity: wechatOAuthEnabled ? 1 : 0.6,
              }}
            >
              {wechatOAuthEnabled ? "去微信授权注册" : "微信 OAuth 未开启"}
            </button>
            <div
              style={{
                margin: "2px auto 0",
                width: "184px",
                height: "184px",
                borderRadius: "18px",
                border: "1px solid var(--line)",
                background: "white",
                display: "grid",
                placeItems: "center",
              }}
            >
              <QrCode size={132} color="#121826" strokeWidth={1.2} />
            </div>
            <div style={{ textAlign: "center", color: "var(--ink-soft)", fontSize: "0.88rem" }}>
              微信授权后会携带 `code + state` 回调到当前页面自动注册
            </div>

            <div style={{ position: "relative" }}>
              <MessageCircle
                size={16}
                style={{
                  position: "absolute",
                  left: "14px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--ink-soft)",
                }}
              />
              <input
                type="text"
                value={wechatCode}
                onChange={(event) => setWechatCode(event.target.value)}
                placeholder="粘贴微信回调 code（必填）"
                style={inputStyle}
              />
            </div>

            <input
              type="text"
              value={wechatState}
              onChange={(event) => setWechatState(event.target.value)}
              placeholder="微信回调 state（必填，防重放）"
              style={{
                ...inputStyle,
                paddingLeft: "14px",
              }}
            />

            <div style={{ position: "relative" }}>
              <User
                size={16}
                style={{
                  position: "absolute",
                  left: "14px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--ink-soft)",
                }}
              />
              <input
                type="text"
                value={wechatNickname}
                onChange={(event) => setWechatNickname(event.target.value)}
                placeholder="微信昵称（可选）"
                style={inputStyle}
              />
            </div>

            <input
              type="text"
              value={wechatAvatarUrl}
              onChange={(event) => setWechatAvatarUrl(event.target.value)}
              placeholder="微信头像 URL（可选）"
              style={{
                ...inputStyle,
                paddingLeft: "14px",
              }}
            />

            {wechatErrorText ? (
              <div style={{ color: "#dc2626", fontSize: "0.86rem", fontWeight: 600 }}>{wechatErrorText}</div>
            ) : null}
            {wechatHint ? (
              <div style={{ color: "#0f766e", fontSize: "0.86rem", fontWeight: 600 }}>{wechatHint}</div>
            ) : null}

            <button
              type="button"
              onClick={() => void handleWechatRegister()}
              disabled={wechatLoading}
              style={{
                marginTop: "6px",
                width: "100%",
                border: "none",
                borderRadius: "12px",
                padding: "13px 14px",
                fontWeight: 700,
                cursor: wechatLoading ? "not-allowed" : "pointer",
                background: "#07c160",
                color: "white",
                opacity: wechatLoading ? 0.7 : 1,
                display: "inline-flex",
                justifyContent: "center",
                alignItems: "center",
                gap: "8px",
              }}
            >
              {wechatLoading ? "注册中..." : "微信注册并登录"}
              {!wechatLoading ? <ArrowRight size={16} /> : null}
            </button>
          </section>
        )}

        <div style={{ textAlign: "center", color: "var(--ink-soft)", fontSize: "0.9rem" }}>
          已有账号？
          <a href="/login" style={{ marginLeft: "6px", color: "var(--primary)", fontWeight: 600 }}>
            去登录
          </a>
        </div>
      </section>
    </main>
  );
}

const tabButtonIdle: CSSProperties = {
  border: "none",
  borderRadius: "10px",
  padding: "10px 12px",
  cursor: "pointer",
  background: "transparent",
  color: "var(--ink-soft)",
  fontWeight: 600,
};

const tabButtonActive: CSSProperties = {
  ...tabButtonIdle,
  background: "var(--primary-alpha-10)",
  color: "var(--primary)",
};

const inputStyle: CSSProperties = {
  width: "100%",
  padding: "12px 14px 12px 40px",
  borderRadius: "12px",
  border: "1px solid var(--line)",
  background: "var(--panel-strong)",
  color: "var(--ink)",
  outline: "none",
  fontSize: "0.94rem",
};
