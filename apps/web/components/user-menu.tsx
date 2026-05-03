"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { User, Settings, Palette, LogOut } from "lucide-react";
import { SettingsSwitcher } from "./theme-switcher";
import { fetchJsonWithClientCache, invalidateClientRequestCache } from "../lib/client-request-cache";

export function UserMenu({ dict, lang }: { dict: any, lang: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [profile, setProfile] = useState<{ name: string; username: string } | null>(null);

  useEffect(() => {
    if (!open || profile) return;
    void fetchJsonWithClientCache<{ name?: string; nickname?: string; username?: string }>("/api/auth/me", {
      ttlMs: 15_000,
      key: "GET:/api/auth/me",
    })
      .then((data) => {
        if (!data) return;
        setProfile({
          name: String(data.name || data.nickname || "用户"),
          username: String(data.username || "unknown"),
        });
      })
      .catch(() => {
        // ignore profile prefetch error
      });
  }, [open, profile]);

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      invalidateClientRequestCache("GET:/api/auth/me");
      invalidateClientRequestCache("GET:/api/settings");
      invalidateClientRequestCache("GET:/api/teams");
      router.replace("/login");
      router.refresh();
      setLoggingOut(false);
    }
  };

  return (
    <div style={{ position: "relative", zIndex: 50 }}>
      {/* Avatar Button */}
      <button 
        onClick={() => setOpen(!open)}
        style={{
          cursor: "pointer", border: "2px solid transparent", background: "var(--primary-alpha-10)", 
          width: "40px", height: "40px", borderRadius: "20px", display: "flex", alignItems: "center", 
          justifyContent: "center", color: "var(--primary)", transition: "all 0.2s",
          boxShadow: open ? "0 0 0 2px var(--primary-alpha-20)" : "none"
        }}
      >
        <User size={20} strokeWidth={2.5} />
      </button>

      {/* Dropdown Menu */}
      {open && (
        <div style={{
          position: "absolute", top: "110%", right: 0,
          background: "var(--panel)",
          border: "1px solid var(--line)",
          borderRadius: "16px",
          boxShadow: "0 20px 40px rgba(0,0,0,0.1)",
          width: "240px",
          padding: "16px",
          display: "flex", flexDirection: "column", gap: "12px",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)"
        }}>
          {!showSettings ? (
            <>
              <div style={{ paddingBottom: "12px", borderBottom: "1px solid var(--line)" }}>
                <strong style={{ display: "block", color: "var(--ink)" }}>{profile?.name || "当前用户"}</strong>
                <span style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>@{profile?.username || "loading"}</span>
              </div>
              <button className="user-menu-btn" onClick={() => { router.push("/settings?tab=personal"); setOpen(false); }}><User size={16}/> 个人设置</button>
              <button className="user-menu-btn" onClick={() => { router.push("/settings?tab=ai"); setOpen(false); }}><Settings size={16}/> 信息设置</button>
              <button className="user-menu-btn" onClick={() => setShowSettings(true)}><Palette size={16}/> 主题与语言</button>
              <div style={{ borderTop: "1px solid var(--line)", paddingTop: "12px", marginTop: "4px" }}>
                <button className="user-menu-btn" style={{color: "var(--danger)"}} onClick={handleLogout}>
                  <LogOut size={16}/> {loggingOut ? "正在退出..." : "退出系统"}
                </button>
              </div>
            </>
          ) : (
            <>
               <button className="user-menu-btn" onClick={() => setShowSettings(false)} style={{marginBottom: "8px"}}>← 返回</button>
               <SettingsSwitcher dict={dict} lang={lang} />
            </>
          )}
        </div>
      )}
      <style dangerouslySetInnerHTML={{__html: `
        .user-menu-btn {
          display: flex; align-items: center; gap: 10px; width: 100%;
          padding: 8px 12px; border-radius: 10px; background: transparent; border: none;
          cursor: pointer; color: var(--ink); font-weight: 500;
          transition: background 0.2s; text-align: left;
        }
        .user-menu-btn:hover {
          background: var(--primary-alpha-10);
          color: var(--primary);
        }
      `}} />
    </div>
  );
}
