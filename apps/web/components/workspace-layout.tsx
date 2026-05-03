"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { AppNav } from "./nav";
import { UserMenu } from "./user-menu";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

const AIAssistant = dynamic(
  () => import("./ai-assistant").then((module) => module.AIAssistant),
  {
    ssr: false,
    loading: () => (
      <div
        className="glassboard"
        style={{
          width: "100%",
          height: "100%",
          borderRadius: "24px",
          border: "1px solid var(--line)",
          background: "var(--panel)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--ink-soft)",
          fontSize: ".92rem",
        }}
      >
        AI 助手加载中...
      </div>
    ),
  },
);

export function WorkspaceLayout({ children, dict, navDict, lang }: any) {
  const [showAI, setShowAI] = useState(false);
  const [hasOpenedAI, setHasOpenedAI] = useState(false);

  return (
    <main className="shell" style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      <AppNav dict={navDict} lang={lang} />

      <section className="dashboard-stage" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, padding: 0 }}>
        
        {/* 全局顶栏 (Global Header) */}
        <header style={{ 
          height: '56px', minHeight: '56px', flexShrink: 0,
          borderBottom: '1px solid var(--line)', padding: '0 24px', 
          display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
          background: 'var(--panel)', zIndex: 100,
          position: 'sticky', top: 0
        }}>
          <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
            
            {/* 分栏 Toggle 开关 */}
            <button 
              onClick={() => {
                setShowAI((prev) => {
                  const next = !prev;
                  if (next) {
                    setHasOpenedAI(true);
                  }
                  return next;
                });
              }}
              title={showAI ? "收起 AI 边栏" : "展开 AI 边栏"}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: '44px', height: '44px', borderRadius: '22px', border: '1px solid var(--line)',
                background: showAI ? 'var(--primary-alpha-10)' : 'transparent',
                color: showAI ? 'var(--primary)' : 'var(--ink-soft)',
                cursor: 'pointer', transition: 'all 0.2s',
                boxShadow: showAI ? '0 0 0 2px var(--primary-alpha-20)' : 'none'
              }}
            >
              {showAI ? <PanelRightClose size={20} strokeWidth={2} /> : <PanelRightOpen size={20} strokeWidth={2} />}
            </button>

            {/* 用户菜单 */}
            <UserMenu dict={navDict} lang={lang} />
          </div>
        </header>

        {/* 下半部分：左侧内容 + 右侧 AI */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'row', minHeight: 0, overflow: 'hidden' }}>
          
          {/* 左侧可替换的具体业务页面 (外部注入的 children) */}
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', background: 'var(--bg-main)' }}>
            {children}
          </div>

          {/* 右侧全局公共 AI 助手 */}
          <div style={{ 
            width: showAI ? '420px' : '0px', padding: showAI ? '24px' : '24px 0', opacity: showAI ? 1 : 0, 
            flexShrink: 0, height: '100%', overflow: 'hidden',
            transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
            borderLeft: showAI ? '1px solid var(--line)' : 'none',
            position: 'relative', background: 'var(--bg-main)', boxSizing: 'border-box'
          }}>
            {/* 调整 AI 助手的位置，使其贴合顶部并占满高度，不再使用 140px 偏移 */}
            <div style={{ 
              width: '100%', 
              height: '100%', 
              position: 'relative',
              zIndex: 30
            }}>
              {hasOpenedAI && showAI ? <AIAssistant /> : null}
            </div>
          </div>

        </div>
      </section>
    </main>
  );
}
