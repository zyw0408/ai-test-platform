"use client";

import { useEffect, useState } from "react";
import { Check, Languages } from "lucide-react";

const THEMES = [
  { id: "green", color: "#1ab08b", label: "清新绿" },
  { id: "blue", color: "#3b82f6", label: "海洋蓝" },
  { id: "pink", color: "#ec4899", label: "樱花粉" },
  { id: "purple", color: "#a855f7", label: "薰衣紫" },
] as const;

export function SettingsSwitcher({ dict, lang }: { dict: any, lang: string }) {
  const [activeTheme, setActiveTheme] = useState("green");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const saved = localStorage.getItem("app-theme") || "green";
    setActiveTheme(saved);
  }, []);

  const changeTheme = (themeId: string) => {
    setActiveTheme(themeId);
    localStorage.setItem("app-theme", themeId);
    document.documentElement.setAttribute("data-theme", themeId);
  };

  const switchLang = () => {
    const newLang = lang === 'en' ? 'zh' : 'en';
    document.cookie = `lang=${newLang};path=/;max-age=31536000`;
    window.location.reload();
  };

  if (!mounted) {
    return <div style={{ height: 80, marginBottom: 14 }} />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '12px', borderRadius: '18px', background: 'transparent', border: 'none', margin: '0' }}>
      
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        <span style={{ fontSize: '0.8rem', color: 'var(--ink-soft)', fontWeight: 600, flex: 1 }}>{dict.theme}</span>
        {THEMES.map((theme) => (
          <button
            key={theme.id}
            type="button"
            onClick={() => changeTheme(theme.id)}
            title={theme.label}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '24px',
              height: '24px',
              borderRadius: '50%',
              backgroundColor: theme.color,
              border: activeTheme === theme.id ? '2px solid white' : '2px solid transparent',
              boxShadow: activeTheme === theme.id ? '0 0 0 1px rgba(0,0,0,0.1)' : 'none',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              transform: activeTheme === theme.id ? 'scale(1.1)' : 'scale(1)',
            }}
          >
            {activeTheme === theme.id && <Check size={14} color="white" />}
          </button>
        ))}
      </div>

      <div style={{ width: '100%', height: '1px', background: 'var(--line)', margin: '4px 0' }} />

      <button 
        onClick={switchLang} 
        style={{ display: 'flex', alignItems: 'center', gap: '8px', border: 'none', background: 'transparent', cursor: 'pointer', padding: '4px 0', fontSize: '0.82rem', color: 'var(--ink-soft)', fontWeight: 600 }}
      >
        <Languages size={15} />
        <span style={{flex: 1, textAlign: 'left'}}>{dict.langToggle}</span>
      </button>

    </div>
  );
}
