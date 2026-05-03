"use client";

import { useState, useRef, useEffect } from "react";
import { Sparkles, Send, Bot, User, Trash2, Square } from "lucide-react";

interface Message {
  role: 'assistant' | 'user' | 'system';
  text: string;
  actions?: Array<{ label: string; command: string }>;
  toolResult?: {
    ok: boolean;
    tool?: string;
    message?: string;
    operationId?: string;
    riskLevel?: "low" | "medium" | "high";
  };
}

type FormFillPayload = {
  module?: string;
  fields?: Record<string, unknown>;
};

function stripActionBlock(text: string): string {
  return text.replace(/```actions[\s\S]*?```/gi, "").trim();
}

function stripFormFillBlock(text: string): string {
  return text.replace(/```form_fill[\s\S]*?```/gi, "").trim();
}

function stripAssistantProtocolBlocks(text: string): string {
  return stripFormFillBlock(stripActionBlock(text)).trim();
}

function sanitizeAssistantReply(text: string): string {
  if (!text) return "";
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => {
      const compact = line.trim();
      if (!compact) return true;
      const isNarrationLine =
        /^\*\(.*\)\*$/.test(compact) &&
        /(执行代理|后台调用|正在汇整|识别到修改|请稍候|执行指令结束)/.test(compact);
      return !isNarrationLine;
    });
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

const QUICK_WORKFLOW_ACTIONS: Array<{ label: string; command: string }> = [
  {
    label: "全流程自动搭建",
    command: "请调用 orchestrate_testing_workflow 工具，workflow=full_e2e_bootstrap, execute=false",
  },
  {
    label: "全流程搭建并执行",
    command: "请调用 orchestrate_testing_workflow 工具，workflow=full_e2e_bootstrap, execute=true",
  },
  {
    label: "API 回归流程",
    command: "请调用 orchestrate_testing_workflow 工具，workflow=api_regression_flow, execute=true",
  },
  {
    label: "安全+性能流程",
    command: "请调用 orchestrate_testing_workflow 工具，workflow=security_perf_flow, execute=true",
  },
  {
    label: "覆盖缺口扫描",
    command: "请调用 orchestrate_testing_workflow 工具，workflow=coverage_scan",
  },
];

export function AIAssistant() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', text: '您好！我是全局 AI 测试辅助专家。\n作为工作台智脑，我可以在任意模块协助您：\n1. 结构化分析模糊的需求\n2. 自动提取测试规范与用例\n3. 智能诊断失败日志和报告\n\n现在您可以直接对我发布指令，或询问关于测试项目的任何问题。' }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  
  const messageListRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastUserPromptRef = useRef<string>("");

  const TOOL_RISK: Record<string, "low" | "medium" | "high"> = {
    delete_project_record: "high",
    delete_requirement_record: "high",
    delete_test_case_record: "high",
    remove_api_step_from_case: "high",
    create_project_record: "medium",
    update_project_record: "medium",
    create_requirement_record: "medium",
    update_requirement_record: "medium",
    create_test_case_record: "medium",
    update_test_case_record: "medium",
    create_api_test_case: "medium",
    update_api_test_parameter: "medium",
    update_api_test_script: "medium",
    bind_existing_request_to_case: "medium",
    reorder_api_steps: "medium",
    generate_api_steps_from_requirement: "medium",
    orchestrate_testing_workflow: "medium",
    invoke_mcp_tool: "medium",
  };

  const inferRiskByToolName = (toolName: string): "low" | "medium" | "high" =>
    TOOL_RISK[toolName] || "low";

  const parseToolNameFromText = (text: string): string | null => {
    const m = text.match(/调用\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*工具/);
    return m?.[1] || null;
  };

  const parseActionCards = (text: string): Array<{ label: string; command: string }> => {
    if (!text) return [];
    const match = text.match(/```actions\s*([\s\S]*?)```/i);
    if (!match) return [];
    try {
      const parsed = JSON.parse(match[1].trim());
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((item) => item && typeof item === "object")
        .map((item) => ({
          label: String((item as any).label || "").trim(),
          command: String((item as any).command || "").trim(),
        }))
        .filter((item) => item.label && item.command)
        .slice(0, 4);
    } catch {
      return [];
    }
  };

  const parseFormFill = (text: string): FormFillPayload | null => {
    if (!text) return null;
    const match = text.match(/```form_fill\s*([\s\S]*?)```/i);
    if (!match?.[1]) return null;
    try {
      const parsed = JSON.parse(match[1].trim());
      if (!parsed || typeof parsed !== "object") return null;
      const moduleName = typeof (parsed as any).module === "string" ? String((parsed as any).module) : undefined;
      const fields =
        (parsed as any).fields && typeof (parsed as any).fields === "object" && !Array.isArray((parsed as any).fields)
          ? ((parsed as any).fields as Record<string, unknown>)
          : undefined;
      return { module: moduleName, fields };
    } catch {
      return null;
    }
  };

  const parseToolResult = (text: string): Message["toolResult"] | undefined => {
    if (!text) return undefined;
    const candidates: string[] = [];
    const full = text.trim();
    if (full.startsWith("{") && full.endsWith("}")) {
      candidates.push(full);
    }
    const jsonBlock = text.match(/```json\s*([\s\S]*?)```/i);
    if (jsonBlock?.[1]) {
      candidates.push(jsonBlock[1].trim());
    }
    for (const candidate of candidates) {
      try {
        const parsed = JSON.parse(candidate);
        if (!parsed || typeof parsed !== "object") continue;
        const ok = Boolean((parsed as any).ok);
        const tool = typeof (parsed as any).tool === "string" ? String((parsed as any).tool) : undefined;
        const message = typeof (parsed as any).message === "string" ? String((parsed as any).message) : undefined;
        const riskLevelRaw = (parsed as any).riskLevel;
        const riskLevel =
          riskLevelRaw === "high" || riskLevelRaw === "medium" || riskLevelRaw === "low"
            ? (riskLevelRaw as "low" | "medium" | "high")
            : undefined;
        const opId =
          typeof (parsed as any)?.data?.summary?.operationId === "string"
            ? String((parsed as any).data.summary.operationId)
            : undefined;
        if (tool || message || typeof (parsed as any).ok === "boolean") {
          return { ok, tool, message, operationId: opId, riskLevel };
        }
      } catch {
        // noop
      }
    }
    return undefined;
  };

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    const container = messageListRef.current;
    if (!container) return;
    container.scrollTo({
      top: container.scrollHeight,
      behavior,
    });
  };

  const validateStructuredCommand = (text: string): { ok: boolean; reason?: string } => {
    const normalized = text.trim();
    if (!normalized) return { ok: false, reason: "输入不能为空。" };
    const mightMutate =
      /创建|新增|更新|修改|删除|调用\s+\w+_(record|script|parameter|test)/.test(normalized);
    if (!mightMutate) return { ok: true };

    // If user sends JSON snippets for mutation, ensure JSON is valid before submit.
    const jsonBlockMatches = normalized.match(/```json[\s\S]*?```/gi) || [];
    for (const block of jsonBlockMatches) {
      const body = block.replace(/```json/i, "").replace(/```/g, "").trim();
      if (!body) continue;
      try {
        JSON.parse(body);
      } catch {
        return { ok: false, reason: "检测到 JSON 格式不合法，请修正后再执行新增/修改操作。" };
      }
    }

    return { ok: true };
  };

  const stopGenerating = () => {
    if (!isTyping) return;
    abortRef.current?.abort();
  };

  useEffect(() => {
    void fetch("/api/ai/chat/history?limit=80", { cache: "no-store" })
      .then(async (res) => (res.ok ? res.json() : { items: [] }))
      .then((data) => {
        const items = Array.isArray(data?.items) ? data.items : [];
        const loaded = items
          .map((item: any) => ({
            role: item?.role === "assistant" ? "assistant" : item?.role === "user" ? "user" : "system",
            text: String(item?.content || ""),
            actions: item?.role === "assistant" ? parseActionCards(String(item?.content || "")) : undefined,
            toolResult: item?.role === "assistant" ? parseToolResult(String(item?.content || "")) : undefined,
          }))
          .map((item: Message) => ({
            ...item,
            text:
              item.role === "assistant"
                ? sanitizeAssistantReply(stripAssistantProtocolBlocks(item.text))
                : item.text,
          }))
          .filter((item: Message) => item.role !== "system" && item.text.trim());
        if (loaded.length > 0) {
          setMessages(loaded);
        }
      })
      .catch(() => {
        // keep default greeting when history API unavailable
      });
  }, []);

  useEffect(() => {
    // Only scroll if there are more than the initial greeting message
    // or if the last message was a user message (to confirm focus)
    if (messages.length > 1 || isTyping) {
      scrollToBottom();
    }
  }, [messages, isTyping]);

  const handleSend = async (forcedText?: string) => {
    const text = (forcedText ?? input).trim();
    if (!text || isTyping) return;
    const parsedTool = parseToolNameFromText(text);
    const risk = parsedTool ? inferRiskByToolName(parsedTool) : "low";
    if (typeof window !== "undefined" && (risk === "high" || risk === "medium")) {
      const prompt = risk === "high"
        ? `检测到高风险工具操作（${parsedTool}）。确认继续执行吗？`
        : `检测到写入工具操作（${parsedTool}）。确认执行吗？`;
      const ok = window.confirm(prompt);
      if (!ok) {
        setMessages(prev => [
          ...prev,
          {
            role: "assistant",
            text: risk === "high"
              ? "已取消高风险操作。建议先执行预检查再确认。"
              : "已取消写入操作。你可以先让我只做分析或预检查。",
          },
        ]);
        return;
      }
    }
    const preflight = validateStructuredCommand(text);
    if (!preflight.ok) {
      setMessages(prev => [
        ...prev,
        {
          role: "assistant",
          text: preflight.reason || "输入格式校验未通过，请检查后重试。",
        },
      ]);
      return;
    }
    let shouldRefreshPage = false;
    let wasAborted = false;
    let finalAssistantText = "";
    
    setInput('');
    lastUserPromptRef.current = text;
    const newMessages: Message[] = [...messages, { role: 'user', text }];
    setMessages(newMessages);
    setIsTyping(true);
    
    // Add an empty assistant message to hold the streaming response
    setMessages(prev => [...prev, { role: 'assistant', text: '' }]);

    const controller = new AbortController();
    abortRef.current = controller;

    const chatPayload = newMessages
      .filter(m => m.role !== 'system' && m.text.trim()) // filter out initial greeting if necessary, though retaining context is better
      .map(m => ({ role: m.role, content: m.text }));

    const buildContext = () => {
      if (typeof window === "undefined") return "";
      const path = window.location.pathname || "/";
      const query = window.location.search || "";
      const title = document.title || "";
      let activeModule = "dashboard";
      if (path.includes("requirements")) activeModule = "requirements";
      else if (path.includes("api")) activeModule = "api-testing";
      else if (path.includes("auto")) activeModule = "auto-testing";
      else if (path.includes("performance")) activeModule = "performance";
      else if (path.includes("security")) activeModule = "security";
      else if (path.includes("reports")) activeModule = "reports";
      else if (path.includes("settings")) activeModule = "settings";

      return [
        `currentPath=${path}`,
        `query=${query}`,
        `activeModule=${activeModule}`,
        `pageTitle=${title}`,
      ].join("\n");
    };

    try {
      let assistantResponse = "";
      let lastError: Error | null = null;

      for (let attempt = 1; attempt <= 2; attempt += 1) {
        try {
          const res = await fetch("/api/ai/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: controller.signal,
            body: JSON.stringify({ 
               messages: chatPayload,
               context: buildContext(),
               stream: true 
            })
          });

          if (!res.ok) {
            const payload = await res.json().catch(() => ({}));
            throw new Error(String(payload?.error || `AI 请求失败(${res.status})`));
          }

          if (!res.body) {
            throw new Error("AI 无响应体");
          }

          const reader = res.body.getReader();
          const decoder = new TextDecoder();

          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split("\n");
            let consumedSse = false;
            
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              consumedSse = true;
              const dataStr = line.replace("data: ", "").trim();
              if (dataStr === "[DONE]") {
                continue;
              }
              try {
                const data = JSON.parse(dataStr);
                if (data.error) {
                  assistantResponse += `\n[系统异常] ${data.error}`;
                } else if (data.content) {
                  assistantResponse += data.content;
                }
              } catch {
                // ignore malformed chunk
              }
              setMessages(prev => {
                 const copy = [...prev];
                 copy[copy.length - 1].text = assistantResponse;
                 copy[copy.length - 1].actions = parseActionCards(assistantResponse);
                 copy[copy.length - 1].toolResult = parseToolResult(assistantResponse);
                 return copy;
              });
            }

            // Backward compatibility if upstream returns plain text stream.
            if (!consumedSse && chunk.trim()) {
              assistantResponse += chunk;
              setMessages(prev => {
                const copy = [...prev];
                copy[copy.length - 1].text = assistantResponse;
                copy[copy.length - 1].actions = parseActionCards(assistantResponse);
                copy[copy.length - 1].toolResult = parseToolResult(assistantResponse);
                return copy;
              });
            }
          }

          lastError = null;
          finalAssistantText = assistantResponse;
          shouldRefreshPage = true;
          break;
        } catch (err: any) {
          if (err?.name === "AbortError") {
            wasAborted = true;
            break;
          }
          lastError = err instanceof Error ? err : new Error(String(err));
          if (attempt < 2) {
            await new Promise((resolve) => setTimeout(resolve, 400));
            continue;
          }
          throw lastError;
        }
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        setMessages(prev => {
          const copy = [...prev];
          copy[copy.length - 1].text += `\n[网络异常或请求中断] ${err.message}`;
          return copy;
        });
      }
    } finally {
      const formFill = parseFormFill(finalAssistantText);
      const changedFields = Object.keys(formFill?.fields || {});
      if (!wasAborted && formFill && changedFields.length > 0 && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("ai-form-fill", {
            detail: {
              module: formFill.module || "api-testing",
              fields: formFill.fields || {},
            },
          }),
        );
      }
      setMessages(prev => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.role === "assistant") {
          last.actions = parseActionCards(last.text);
          last.toolResult = parseToolResult(last.text);
          const stripped = stripAssistantProtocolBlocks(last.text);
          if (formFill && changedFields.length > 0 && !wasAborted) {
            last.text = sanitizeAssistantReply(
              `${stripped}\n\n已同步到页面表单：${changedFields.join("、")}`,
            );
          } else {
            last.text = sanitizeAssistantReply(stripped);
          }
        }
        return copy;
      });
      setIsTyping(false);
      abortRef.current = null;
      if (wasAborted) {
        setMessages(prev => [
          ...prev,
          {
            role: "assistant",
            text: "已停止本次生成。你可以选择继续刚才任务，或补充新要求后再执行。",
            actions: [
              {
                label: "继续刚才回复",
                command: `请基于我上一条请求继续回答，不重复已完成部分。上一条请求：${lastUserPromptRef.current}`,
              },
              {
                label: "放弃本轮并重来",
                command: "忽略上一条未完成内容，我们重新开始新的需求。",
              },
            ],
          },
        ]);
      }
      if (!wasAborted && shouldRefreshPage && typeof window !== "undefined") {
        setTimeout(() => {
          // Soft refresh data only: avoid full router.refresh to reduce page jank.
          window.dispatchEvent(new CustomEvent("platform-data-refresh"));
        }, 180);
      }
    }
  };

  const handleClear = () => {
    void fetch("/api/ai/chat/history", { method: "DELETE" }).catch(() => {});
    setMessages([
      { role: 'assistant', text: '对话已重置。有什么我可以帮您的吗？' }
    ]);
  };

  return (
    <div className="glassboard" style={{
      width: '100%', height: '100%', borderRadius: '24px',
      padding: 0, overflow: 'hidden', border: '1px solid var(--line)',
      display: 'flex', flexDirection: 'column', background: '#f4fcfa',
      boxShadow: '0 8px 24px rgba(16, 185, 129, 0.08)'
    }}>
       {/* 头部 */}
       <div style={{ padding: '24px 24px 20px', background: '#eefaf6', borderBottom: '1px solid #d9eee7', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--primary)', fontWeight: 600, fontSize: '1.05rem' }}>
             <Sparkles size={20} /> AI 测试辅助专家
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {isTyping ? (
              <button
                onClick={stopGenerating}
                style={{
                  border: "1px solid #f3b0b0",
                  background: "#fff5f5",
                  color: "#d14343",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                  fontSize: "0.85rem",
                  borderRadius: 10,
                  padding: "6px 10px",
                }}
                title="打断本次回复"
              >
                <Square size={14} /> 停止生成
              </button>
            ) : null}
            <button 
               onClick={handleClear}
               style={{ background: 'none', border: 'none', color: 'var(--ink-soft)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.85rem' }}
               title="清空对话"
            >
               <Trash2 size={16} /> 清空
            </button>
          </div>
       </div>

       <div
         style={{
           padding: "10px 18px 12px",
           borderBottom: "1px solid #d9eee7",
           background: "#f5fcf9",
           display: "flex",
           flexWrap: "wrap",
           gap: 8,
         }}
       >
         {QUICK_WORKFLOW_ACTIONS.map((item) => (
           <button
             key={item.label}
             type="button"
             onClick={() => {
               void handleSend(item.command);
             }}
             disabled={isTyping}
             style={{
               border: "1px solid #cfe8df",
               background: isTyping ? "#eef4f1" : "#ffffff",
               color: isTyping ? "#93a29c" : "#177b62",
               borderRadius: 999,
               padding: "6px 11px",
               fontSize: "0.8rem",
               fontWeight: 700,
               cursor: isTyping ? "not-allowed" : "pointer",
             }}
             title={item.command}
           >
             {item.label}
           </button>
         ))}
       </div>

       {/* 聊天记录区 */}
       <div
         ref={messageListRef}
         style={{
           flex: 1,
           padding: '24px',
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: '24px',
            overscrollBehavior: 'contain',
            background: '#f8fdfb',
         }}
       >
         {messages.map((m, i) => (
           <div key={i} style={{ display: 'flex', gap: '12px', flexDirection: m.role === 'user' ? 'row-reverse' : 'row' }}>
              <div style={{ 
               width: '36px', height: '36px', borderRadius: '18px', 
               background: m.role === 'user' ? 'var(--primary)' : 'var(--bg-main)', 
               display: 'flex', alignItems: 'center', justifyContent: 'center', 
               color: m.role === 'user' ? 'white' : 'var(--primary)', flexShrink: 0,
               boxShadow: m.role === 'user' ? '0 4px 12px var(--primary-alpha-20)' : '0 2px 8px rgba(0,0,0,0.05)'
             }}>
               {m.role === 'user' ? <User size={18} /> : <Bot size={18} />}
             </div>
             <div style={{ 
               background: m.role === 'user' ? '#14b88a' : '#ffffff', 
               color: m.role === 'user' ? 'white' : 'var(--ink)', 
               padding: '14px 18px', borderRadius: '18px', 
               borderTopRightRadius: m.role === 'user' ? '4px' : '18px', 
               borderTopLeftRadius: m.role === 'user' ? '18px' : '4px', 
               fontSize: '0.95rem', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
               border: m.role === 'user' ? '1px solid rgba(20,184,138,0.3)' : '1px solid #e4f0eb',
               boxShadow: m.role === 'user' ? '0 8px 16px rgba(20,184,138,0.14)' : '0 2px 10px rgba(16,185,129,0.06)',
               maxWidth: '85%'
             }}>
               {m.text || <span style={{ opacity: 0.5 }}>思考中...</span>}
               {m.role === "assistant" && m.toolResult ? (
                 <div
                   style={{
                     marginTop: 10,
                     border: "1px solid var(--line-strong)",
                     background: "var(--panel)",
                     borderRadius: 10,
                     padding: "8px 10px",
                     fontSize: "0.8rem",
                     lineHeight: 1.5,
                   }}
                 >
                   <div style={{ fontWeight: 700, color: m.toolResult.ok ? "var(--ok)" : "var(--danger)" }}>
                     {m.toolResult.ok ? "工具执行成功" : "工具执行失败"}
                   </div>
                   {m.toolResult.tool ? <div>tool: {m.toolResult.tool}</div> : null}
                   {m.toolResult.riskLevel ? <div>risk: {m.toolResult.riskLevel}</div> : null}
                   {m.toolResult.message ? <div>{m.toolResult.message}</div> : null}
                   {m.toolResult.operationId ? <div>operationId: {m.toolResult.operationId}</div> : null}
                 </div>
               ) : null}
               {m.role === "assistant" && Array.isArray(m.actions) && m.actions.length > 0 ? (
                 <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 8 }}>
                   {m.actions.map((action, idx) => (
                     <button
                       key={`${action.label}-${idx}`}
                       type="button"
                       onClick={() => {
                         void handleSend(action.command);
                       }}
                       style={{
                         border: "1px solid var(--line-strong)",
                         background: "var(--panel)",
                         color: "var(--ink)",
                         borderRadius: 999,
                         padding: "4px 10px",
                         fontSize: "0.78rem",
                         cursor: "pointer",
                         fontWeight: 600,
                       }}
                       title={action.command}
                     >
                       {action.label}
                     </button>
                   ))}
                 </div>
               ) : null}
             </div>
           </div>
         ))}
         {isTyping && messages[messages.length-1]?.role !== 'assistant' && (
           <div style={{ display: 'flex', gap: '12px', flexDirection: 'row' }}>
             <div style={{ width: '36px', height: '36px', borderRadius: '18px', background: 'var(--bg-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--primary)', flexShrink: 0, boxShadow: '0 2px 8px rgba(0,0,0,0.05)' }}>
               <Bot size={18} />
             </div>
             <div style={{ background: 'var(--panel-strong)', color: 'var(--ink-soft)', padding: '14px 18px', borderRadius: '18px', borderTopLeftRadius: '4px', fontSize: '0.95rem' }}>
               <div className="typing-dots">
                 <span>.</span><span>.</span><span>.</span>
               </div>
             </div>
           </div>
         )}
         <div ref={messagesEndRef} />
       </div>

       {/* 输入框区 */}
       <div style={{ padding: '20px', borderTop: '1px solid #d9eee7', background: '#eefaf6' }}>
         <div style={{ display: 'flex', gap: '12px', background: '#ffffff', padding: '8px', borderRadius: '16px', border: '1px solid #d7ebe5' }}>
           <input 
             type="text" 
             value={input}
             onChange={e => setInput(e.target.value)}
             onKeyDown={e => e.key === 'Enter' && handleSend()}
             placeholder="输入需求或分析指令，与 AI 智脑对话..." 
             style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', padding: '0 12px', color: 'var(--ink)', fontSize: '0.95rem' }}
             disabled={isTyping}
           />
           <button 
             onClick={() => { void handleSend(); }} 
             disabled={isTyping || !input.trim()}
             style={{ 
               width: '40px', height: '40px', borderRadius: '12px', 
               background: input.trim() && !isTyping ? 'var(--primary)' : 'var(--line-strong)', 
               color: input.trim() && !isTyping ? 'white' : 'var(--ink-soft)',
               border: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center',
               cursor: input.trim() && !isTyping ? 'pointer' : 'not-allowed', transition: 'all 0.2s',
               boxShadow: input.trim() && !isTyping ? '0 4px 12px var(--primary-alpha-30)' : 'none'
             }}
           >
             <Send size={18} style={{ transform: 'translateX(-2px) translateY(2px)' }} />
           </button>
         </div>
       </div>
    </div>
  );
}
