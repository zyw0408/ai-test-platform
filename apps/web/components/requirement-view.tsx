"use client";

import { useState } from "react";
import { UserMenu } from "./user-menu";
import { RequirementTable } from "./requirement-table";
import { AIAssistant } from "./ai-assistant";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

export function RequirementView({ dict, navDict, lang, recentRuns }: any) {
  const [showAI, setShowAI] = useState(true);

  return (
    <div style={{ display: 'flex', flexDirection: 'row', gap: showAI ? '24px' : '0px', width: '100%', height: '100%', transition: 'gap 0.3s cubic-bezier(0.16, 1, 0.3, 1)' }}>
      
      {/* 左侧主要表格区 */}
      <div className="glassboard" style={{ flex: 1, padding: '32px', display: 'flex', flexDirection: 'column', height: '100%', minWidth: 0 }}>
        
        <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ fontSize: '1.8rem', letterSpacing: '-0.03em', margin: 0, fontWeight: 700 }}>{navDict.requirements}</h1>
          
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
            <input 
              type="text" 
              placeholder={dict.searchPlaceholder} 
              style={{
                width: '280px',
                padding: '10px 14px',
                borderRadius: '12px',
                border: '1px solid var(--line)',
                background: 'rgba(255,255,255,0.7)',
                outline: 'none',
                transition: 'all 0.2s',
              }} 
            />
            
            {/* 侧边栏折叠按钮 (VS Code style toggle) */}
            <button 
              onClick={() => setShowAI(!showAI)}
              title={showAI ? "收起 AI 分析侧边栏" : "展开 AI 分析侧边栏"}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: '40px', height: '40px', borderRadius: '20px', border: '1px solid var(--line)',
                background: showAI ? 'var(--primary-alpha-10)' : 'transparent',
                color: showAI ? 'var(--primary)' : 'var(--ink-soft)',
                cursor: 'pointer', transition: 'all 0.2s',
                boxShadow: showAI ? '0 0 0 2px var(--primary-alpha-20)' : 'none'
              }}
            >
              {showAI ? <PanelRightClose size={20} strokeWidth={2} /> : <PanelRightOpen size={20} strokeWidth={2} />}
            </button>

            <UserMenu dict={navDict} lang={lang} />
          </div>
        </div>

        <RequirementTable dict={dict} initialData={recentRuns} />
        
      </div>

      {/* 右侧边栏 AI 助手 */}
      <div style={{ 
        width: showAI ? '400px' : '0px', 
        opacity: showAI ? 1 : 0, 
        flexShrink: 0, 
        height: '100%',
        overflow: 'hidden',
        transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        position: 'relative'
      }}>
        {/* 强制内部元素宽度以免在动画缩小挤压时文字出现换行错位 */}
        <div style={{ width: '400px', height: '100%', position: 'absolute', top: 0, left: 0 }}>
          <AIAssistant />
        </div>
      </div>

    </div>
  );
}
