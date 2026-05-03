"use client";

import { useCallback, useEffect, useState } from "react";
import { User, Lock, Smartphone, QrCode, ShieldAlert, ArrowRight, RefreshCw, Hexagon } from "lucide-react";

type RegisterMeta = {
  sms?: {
    mode?: string;
    testCode?: string | null;
  };
};

export default function LoginPage() {
  const [method, setMethod] = useState<'password' | 'sms' | 'wechat'>('password');
  const [tab, setTab] = useState<'account' | 'phone'>('phone'); 
  const [loading, setLoading] = useState(false);
  const [registerMeta, setRegisterMeta] = useState<RegisterMeta | null>(null);
  const [metaLoading, setMetaLoading] = useState(true);
  
  // 绑定表单双向数据
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [wechatCode, setWechatCode] = useState("");
  const [errorText, setErrorText] = useState("");
  const [wechatHint, setWechatHint] = useState("");
  const [wechatAutoTried, setWechatAutoTried] = useState(false);
  const smsMode = registerMeta?.sms?.mode ?? "provider";
  const smsTestCode = registerMeta?.sms?.testCode ?? null;
  const isSmsTestMode = smsMode === "test";

  const submitLogin = useCallback(async (body: Record<string, unknown>) => {
    setLoading(true);
    setErrorText("");

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      
      const json = await res.json();
      
      if (json.code === 0) {
        const nextPath = new URLSearchParams(window.location.search).get("next");
        window.location.assign(nextPath && nextPath.startsWith("/") ? nextPath : "/");
      } else {
        setErrorText(json.message);
        setLoading(false);
      }
    } catch {
      setErrorText("登录服务暂时不可用，请稍后重试");
      setLoading(false);
    }
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    await submitLogin({
      method,
      username: tab === 'phone' ? phone : username,
      password,
      phone,
      code,
    });
  };

  const handleWechatCodeLogin = useCallback(async (value?: string) => {
    const codeFromInput = (value ?? wechatCode).trim();
    if (!codeFromInput) {
      setErrorText("缺少微信授权 code");
      return;
    }
    await submitLogin({
      method: "wechat",
      wechatCode: codeFromInput,
    });
  }, [submitLogin, wechatCode]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const callbackCode = params.get("code");
    if (callbackCode && !wechatAutoTried) {
      setMethod("wechat");
      setWechatHint("检测到微信回调 code，正在尝试登录...");
      setWechatCode(callbackCode);
      setWechatAutoTried(true);
      void handleWechatCodeLogin(callbackCode);
    }
  }, [handleWechatCodeLogin, wechatAutoTried]);

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
        // Ignore and fallback to test mode hint.
      } finally {
        setMetaLoading(false);
      }
    };
    void loadMeta();
  }, []);

  return (
    <main style={{ 
      width: '100vw', height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'flex-start',
      paddingLeft: '10vw',
      background: 'var(--bg-main)', // Fallback base color
      overflow: 'hidden', position: 'relative',
      perspective: '1200px'
    }}>
      {/* 动态视频背景 */}
      <video 
        autoPlay loop muted playsInline 
        style={{
          position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0
        }}
        poster="/elaina.png"
        onError={(e) => { e.currentTarget.style.display = 'none'; }}
      >
        <source src="/elaina.mp4" type="video/mp4" />
      </video>

      {/* 回退静态背景（如果视频不存在，则显示原画） */}
      <div style={{
        position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: -1,
        background: 'url("/elaina.png") center/cover no-repeat'
      }} />

      <div className="login-box" style={{
        width: '380px', padding: '40px 36px', borderRadius: '28px', position: 'relative', zIndex: 10,
        background: 'rgba(255,255,255,0.12)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
        boxShadow: '20px 30px 80px rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.25)',
        borderTop: '1px solid rgba(255,255,255,0.5)', borderRight: '1px solid rgba(255,255,255,0.5)',
        transform: 'rotateY(12deg) rotateX(4deg)', transformStyle: 'preserve-3d', transition: 'all 0.5s ease'
      }}
      onMouseEnter={(e) => e.currentTarget.style.transform = 'rotateY(4deg) rotateX(1deg) scale(1.02)'}
      onMouseLeave={(e) => e.currentTarget.style.transform = 'rotateY(12deg) rotateX(4deg) scale(1)'}
      >
        
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <div className="brand-mark" style={{ width: '48px', height: '48px', fontSize: '1.2rem', margin: '0 auto 16px' }}>AI</div>
          <h1 style={{ margin: 0, fontSize: '1.6rem', color: 'var(--ink)' }}>AI 测试控制台</h1>
          <p style={{ margin: '8px 0 0', color: 'var(--ink-soft)', fontSize: '0.9rem' }}>欢迎回来，请登录您的工作区</p>
        </div>

        <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', background: 'rgba(255,255,255,0.2)', padding: '5px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.3)' }}>
          <button 
            type="button" 
            onClick={() => setMethod('password')}
            style={{ flex: 1, padding: '10px 0', cursor: 'pointer', background: method === 'password' ? 'rgba(255,255,255,0.6)' : 'transparent', border: 'none', borderRadius: '8px', color: method === 'password' ? 'var(--primary)' : 'var(--ink)', fontWeight: 600, transition: 'all 0.2s', boxShadow: method === 'password' ? '0 4px 12px rgba(0,0,0,0.08)' : 'none' }}>密码登录</button>
          <button 
            type="button" 
            onClick={() => setMethod('sms')}
            style={{ flex: 1, padding: '10px 0', cursor: 'pointer', background: method === 'sms' ? 'rgba(255,255,255,0.6)' : 'transparent', border: 'none', borderRadius: '8px', color: method === 'sms' ? 'var(--primary)' : 'var(--ink)', fontWeight: 600, transition: 'all 0.2s', boxShadow: method === 'sms' ? '0 4px 12px rgba(0,0,0,0.08)' : 'none' }}>验证码</button>
          <button 
            type="button" 
            onClick={() => setMethod('wechat')}
            style={{ flex: 1, padding: '10px 0', cursor: 'pointer', background: method === 'wechat' ? 'rgba(255,255,255,0.6)' : 'transparent', border: 'none', borderRadius: '8px', color: method === 'wechat' ? 'var(--primary)' : 'var(--ink)', fontWeight: 600, transition: 'all 0.2s', boxShadow: method === 'wechat' ? '0 4px 12px rgba(0,0,0,0.08)' : 'none' }}>扫码</button>
        </div>

        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          
          {method === 'password' && (
            <>
              <div style={{ display: 'flex', gap: '16px', marginBottom: '4px' }}>
                <span onClick={() => setTab('phone')} style={{ cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600, color: tab === 'phone' ? 'var(--ink)' : 'var(--ink-soft)', paddingBottom: '4px', borderBottom: tab === 'phone' ? '2px solid var(--ink)' : '2px solid transparent' }}>手机号密码</span>
                <span onClick={() => setTab('account')} style={{ cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600, color: tab === 'account' ? 'var(--ink)' : 'var(--ink-soft)', paddingBottom: '4px', borderBottom: tab === 'account' ? '2px solid var(--ink)' : '2px solid transparent' }}>账号密码</span>
              </div>
              
              <div style={{ position: 'relative' }}>
                {tab === 'phone' ? (
                  <input 
                    required 
                    type="text" 
                    name="username"
                    autoComplete="username"
                    value={phone} 
                    onChange={e => setPhone(e.target.value)} 
                    placeholder="请输入已注册手机号" 
                    style={inputStyle} 
                  />
                ) : (
                  <input 
                    required 
                    type="text" 
                    name="username"
                    autoComplete="username"
                    value={username} 
                    onChange={e => setUsername(e.target.value)} 
                    placeholder="请输入账号名" 
                    style={inputStyle} 
                  />
                )}
              </div>

              <div style={{ position: 'relative' }}>
                <div style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-soft)' }}>
                  <Lock size={18} />
                </div>
                <input 
                  required 
                  type="password" 
                  name="password"
                  autoComplete="current-password"
                  value={password} 
                  onChange={e => setPassword(e.target.value)} 
                  placeholder="请输入密码" 
                  style={inputStyle} 
                />
              </div>
              
              {errorText && <div style={{ color: '#ef4444', fontSize: '0.85rem', marginTop: '-4px', fontWeight: 600 }}>{errorText}</div>}

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', color: 'var(--ink-soft)', cursor: 'pointer' }}>
                  <input type="checkbox" style={{ accentColor: 'var(--primary)', width: '16px', height: '16px', cursor: 'pointer' }} /> 保持登录
                </label>
                <span onClick={() => setMethod('sms')} style={{ fontSize: '0.85rem', color: 'var(--primary-hover)', cursor: 'pointer', fontWeight: 500 }}>忘记密码？用短信登录</span>
              </div>
            </>
          )}

          {method === 'sms' && (
            <>
              <div style={{ position: 'relative' }}>
                <div style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-soft)' }}>
                  <Smartphone size={18} />
                </div>
                <input required type="text" value={phone} onChange={e => setPhone(e.target.value)} placeholder="请输入已注册手机号" style={inputStyle} />
              </div>

              <div style={{ position: 'relative', display: 'flex', gap: '12px' }}>
                <div style={{ position: 'relative', flex: 1 }}>
                  <div style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-soft)' }}>
                    <ShieldAlert size={18} />
                  </div>
                  <input required type="text" value={code} onChange={e => setCode(e.target.value)} placeholder={isSmsTestMode ? `测试验证码: ${smsTestCode ?? "123456"}` : "短信验证码"} style={inputStyle} />
                </div>
                <button type="button" style={{ 
                  padding: '0 18px', background: 'var(--primary-alpha-10)', border: 'none', 
                  borderRadius: '12px', color: 'var(--primary-hover)', fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
                  transition: 'all 0.2s',
                }}
                onMouseOver={(e) => e.currentTarget.style.background = 'var(--primary-alpha-20)'}
                onMouseOut={(e) => e.currentTarget.style.background = 'var(--primary-alpha-10)'}
                >
                  获取验证码
                </button>
              </div>
              {errorText && <div style={{ color: '#ef4444', fontSize: '0.85rem', marginTop: '4px', fontWeight: 600 }}>{errorText}</div>}

              <div style={{ fontSize: '0.85rem', color: 'var(--ink-soft)', textAlign: 'center', background: 'rgba(0,0,0,0.02)', padding: '10px', borderRadius: '10px', marginTop: '8px' }}>
                仅支持已注册手机号登录，如无账号请先完成注册
                <br />
                {metaLoading
                  ? "正在加载验证码模式..."
                  : isSmsTestMode
                    ? `当前测试模式验证码为 ${smsTestCode ?? "123456"}（不要填写错误码）`
                    : "当前生产模式请填写短信服务下发的验证码"}
              </div>
            </>
          )}

          {method === 'wechat' && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '16px 0' }}>
              <div style={{ width: '180px', height: '180px', background: 'white', borderRadius: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 12px 24px rgba(0,0,0,0.08), inset 0 0 0 1px var(--line)', position: 'relative' }}>
                <QrCode size={130} color="var(--ink)" strokeWidth={1} style={{ opacity: 0.8 }} />
                <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', background: '#07c160', borderRadius: '8px', width: '38px', height: '38px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '3px solid white' }}>
                  <Hexagon size={24} color="white" fill="white" />
                </div>
              </div>
              <p style={{ marginTop: '20px', fontSize: '0.95rem', color: 'var(--ink)', fontWeight: 500 }}>请使用 微信 扫一扫</p>
              <p style={{ marginTop: '4px', fontSize: '0.85rem', color: 'var(--ink-soft)' }}>关注公众号安全极速登录</p>
              {wechatHint && (
                <p style={{ marginTop: '8px', fontSize: '0.8rem', color: 'var(--primary-hover)' }}>{wechatHint}</p>
              )}

              <div style={{ width: '100%', marginTop: '16px', display: 'flex', gap: '10px' }}>
                <input
                  type="text"
                  value={wechatCode}
                  onChange={(e) => setWechatCode(e.target.value)}
                  placeholder="或粘贴 wechatCode（回调参数 code）"
                  style={{
                    ...inputStyle,
                    flex: 1,
                    padding: '12px 12px 12px 16px',
                  }}
                />
                <button
                  type="button"
                  onClick={() => void handleWechatCodeLogin()}
                  disabled={loading}
                  style={{
                    padding: '0 14px',
                    borderRadius: '12px',
                    border: 'none',
                    background: 'var(--primary)',
                    color: 'white',
                    fontWeight: 600,
                    cursor: 'pointer',
                    opacity: loading ? 0.7 : 1,
                    whiteSpace: 'nowrap',
                  }}
                >
                  微信登录
                </button>
              </div>
              {errorText && <div style={{ color: '#ef4444', fontSize: '0.85rem', marginTop: '8px', fontWeight: 600 }}>{errorText}</div>}
            </div>
          )}

          {method !== 'wechat' && (
            <button type="submit" disabled={loading} style={{
              width: '100%', padding: '14px', borderRadius: '14px', background: 'var(--primary)', color: 'white',
              border: 'none', fontSize: '1rem', fontWeight: 600, cursor: 'pointer', marginTop: '12px',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
              boxShadow: '0 8px 16px var(--primary-alpha-20)', transition: 'all 0.2s',
              opacity: loading ? 0.7 : 1
            }}>
              {loading ? <RefreshCw className="animate-spin" size={18} /> : (
                <>
                  登录系统 <ArrowRight size={18} strokeWidth={2.5} />
                </>
              )}
            </button>
          )}

          <div style={{ textAlign: 'center', color: 'var(--ink-soft)', fontSize: '0.88rem', marginTop: '6px' }}>
            还没有账号？
            <a href="/register" style={{ marginLeft: '6px', color: 'var(--primary)', fontWeight: 600 }}>
              立即注册
            </a>
          </div>
        </form>

      </div>
      
      <style dangerouslySetInnerHTML={{__html: `
        @keyframes spin { 100% { transform: rotate(360deg); } }
        .animate-spin { animation: spin 1s linear infinite; }
        
        input:focus { border-color: var(--primary) !important; box-shadow: 0 0 0 3px var(--primary-alpha-20); }
      `}} />
    </main>
  );
}

// 提取共用样式对象
const inputStyle = {
  width: '100%', padding: '14px 14px 14px 44px', borderRadius: '12px', 
  border: '1px solid rgba(255,255,255,0.4)', background: 'rgba(255,255,255,0.3)',
  fontSize: '0.95rem', color: 'var(--ink)', outline: 'none', transition: 'all 0.2s',
  fontWeight: 500, backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)'
};
