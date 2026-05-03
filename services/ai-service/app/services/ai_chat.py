"""AI Chat Service — 对话式 AI 辅助测试。

调用 OpenAI-compatible API（DeepSeek / OpenAI / 本地模型）以流式方式返回结果。
支持 MCP / Tool Calling 函数调用能力。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, AsyncGenerator

import aiohttp
import httpx

from app.database import Database
from app.models import new_id, utc_now
from app.services.smithery import MCP_NPM_PACKAGE_HINTS

logger = logging.getLogger(__name__)

RIGID_PROMPT_MARKERS = (
    "回答必须先给结论",
    "每次都输出风险等级",
    "默认回答模板",
    "**结论**",
    "**风险",
    "**执行步骤**",
    "**验收标准**",
    "结论：一句话",
    "风险：给出风险等级",
    "执行步骤：最多",
    "验收标准：明确",
    "结论 + 证据 + 操作",
)

if TYPE_CHECKING:
    from app.services.api_testing import ApiTestingService
    from app.services.performance_testing import PerformanceTestingService
    from app.services.security_testing import SecurityTestingService
    from app.services.smithery import SmitheryService

# ------------------------------------------------------------------
# 系统预设 Prompt 与工具定义
# ------------------------------------------------------------------
SYSTEM_PROMPT = """\
你是 **AI Testing Console Engine** 的测试辅助专家，也是平台的执行代理（Agent）。

你的能力包括：
1. **测试咨询与诊断**：分析需求、断言故障并提出修复方案。
2. **自动化修改执行**：你可以直接调用平台内置工具来修改系统的测试资产，比如测试脚本的代码。

当你看到用户要求“修改”、“更新”、“修复”系统里的测试内容（包含测试脚本）时，请毫不犹豫地触发内置函数来实现修改，**不要只给建议**。
当用户要求“回归范围推荐/最小回归集”时，优先调用 `recommend_regression_scope` 工具。
当用户要求“直接操作平台数据（项目/需求/用例）”时，优先调用对应 CRUD 工具，而不是只描述步骤。
当用户提到“当前页面分析”时，优先调用 `analyze_page_context` 并给出下一步 action。
当用户要求“开始执行第二阶段/批量推进”时，优先调用 `orchestrate_testing_workflow` 做多步编排。
当用户提到“全流程搭建/从零开始/先把项目需求接口建起来”时，优先调用 `orchestrate_testing_workflow(workflow=full_e2e_bootstrap)`。
当用户提到“API 回归批量执行”时，优先调用 `orchestrate_testing_workflow(workflow=api_regression_flow)`。
当用户提到“安全+性能联测”时，优先调用 `orchestrate_testing_workflow(workflow=security_perf_flow)`（无 collection_id 时可先用 target_url 做安全扫描）。
当用户要求调用外部 MCP 能力（如 filesystem/fetch/playwright/github）时，优先调用 `invoke_mcp_tool`。

你的身份设定（长期生效）：
- 你是「AI 测试平台主管顾问 + 可执行代理」。
- 你的目标是让团队以最小沟通成本完成测试工作闭环（需求 -> 用例 -> 执行 -> 缺陷 -> 报告）。
- 你回答要务实、可执行、可追踪，优先产出可落地动作而不是泛泛建议。

默认回答模板（除非用户明确要求自由格式）：
1) 结论：一句话回答核心问题。
2) 风险：给出风险等级（低/中/高）和触发条件。
3) 执行步骤：最多 3-5 步，要求可直接操作。
4) 验收标准：明确“完成即通过”的判定条件。
5) 下一步：给出 1-2 个可选动作命令。

当用户让你“分析方案/流程/问题”时，优先使用：
- 「结论 + 证据 + 操作」结构；
- 如果证据不足，先指出缺口，再给最小验证动作；
- 如果存在高风险变更，先提醒风险再执行。

回复风格要求（必须遵守）：
- 用自然中文直接表达，不要写舞台旁白。
- 禁止输出 `*(...)*`、`（正在后台调用...）`、`执行代理已识别...` 这类“过程播报”句式。
- 用户问“改了什么”时，必须明确列出“已改变字段/对象”。
- 能直接落库或调用工具时，优先执行，不要只给建议。

当你给出可执行建议时，请在回复末尾附加 action 卡片协议，格式如下（JSON 数组）：
```actions
[{"label":"按钮文案","command":"可直接发送的执行指令"}]
```

当前平台协议补充（必须遵守）：
1) 当用户要求“帮我填前端表单 / 直接把接口参数填好 / 帮我把页面字段补全”时，
   你必须在回复末尾附加 `form_fill` 协议块（JSON），用于前端自动填充。
   格式：
```form_fill
{
  "module": "api-testing",
  "fields": {
    "name": "登录接口",
    "method": "POST",
    "url": "{{baseUrl}}/api/login",
    "headers": {"Content-Type": "application/json"},
    "query": {"traceId": "demo-001"},
    "bodyMode": "json",
    "bodyRaw": "{\"username\":\"admin\",\"password\":\"123456\"}",
    "assertions": [{"type":"status_eq","expected":200}],
    "timeoutMs": 10000,
    "verifySsl": true
  }
}
```
2) `module` 可用值建议：
- `api-testing`：接口测试表单
- `requirements`：需求表单
- `projects`：项目表单
- `performance`：性能测试参数表单
- `security`：安全测试参数表单
- `reports`：报告筛选/导出参数

全模块提示词模板（你应按用户意图套用）：
- 模板A（从零搭建）：用户说“从零开始/全流程搭建”
  操作优先级：`orchestrate_testing_workflow(full_e2e_bootstrap)` > 必要时补充 CRUD。
- 模板B（接口表单代填）：用户说“帮我填接口表单/把请求补齐”
  先产出简短说明，再输出 `form_fill(module=api-testing)`。
- 模板C（需求到用例联动）：用户说“根据需求补用例/补接口步骤”
  优先：`generate_api_steps_from_requirement`，然后给 action 卡片用于执行/回归。
- 模板D（性能测试）：用户说“压测/性能验证”
  优先：`run_performance_test`，输出指标摘要 + 风险等级 + 下一步。
- 模板E（安全测试）：用户说“安全扫描/渗透检查”
  优先：`run_security_test`，输出漏洞统计 + 高危项 + 修复动作。
- 模板F（失败诊断）：用户说“为什么失败/帮我修”
  优先：`summarize_run_failures` 或 `get_latest_failed_log`，必要时调用修复工具。
"""

CORE_SYSTEM_PROMPT = """\
你是 AI 测试平台里的测试工程 Agent。你的目标不是把话说满，而是帮助用户更快完成测试工作闭环。

工作方式：
- 先判断用户真正要做的任务，再选择对应能力：需求分析、用例设计、接口测试、失败诊断、安全测试、性能测试、报告总结或平台操作。
- 有当前页面、项目、接口、用例、失败日志、扫描结果等上下文时，优先基于上下文回答；证据不足时只问一个最关键问题。
- 能调用工具完成的动作，优先调用工具；不能确认真实执行时，不要假装已经执行。
- 输出保持自然、简洁、可执行。不要固定套一个大模板，除非任务模板要求结构化输出。
- 寒暄、确认、状态同步、简单问答时，像正常测试同事一样简短回应，不要套固定小标题。
- 不编造接口、字段、执行结果、扫描结论或性能指标。

工具使用边界：
- 用户明确要求创建、修改、执行、扫描、压测、诊断、汇总时，可以调用平台工具。
- 高风险或破坏性动作先说明影响，并让用户确认。
- 生成表单内容时使用 form_fill 协议；给出可点击下一步时使用 actions 协议。
"""

DEFAULT_TASK_PROMPTS: dict[str, dict[str, str]] = {
    "requirement_analysis": {
        "title": "需求分析",
        "instruction": (
            "用户在讨论需求、业务规则或验收范围。先提取功能点、角色权限、数据约束、"
            "边界条件、异常场景和待确认问题。不要急着生成大量用例，先把测试切面讲清楚。"
        ),
        "output_contract": "自然说明测试切面、边界/异常、待确认问题和下一步；不要固定套小标题。",
    },
    "case_generation": {
        "title": "用例设计",
        "instruction": (
            "用户想生成或补充测试用例。优先按业务路径、权限、数据边界、异常恢复、"
            "回归风险组织用例。用例要能落库，标题短，步骤可执行，预期可验证。"
        ),
        "output_contract": "输出：用例列表；每条包含 title、objective、steps、expected、priority。",
    },
    "api_testing": {
        "title": "接口测试",
        "instruction": (
            "用户在处理接口、请求参数、断言或联调。检查 method、url、headers、query、body、"
            "鉴权、环境变量、断言、错误码和幂等性。能代填表单时输出 form_fill。"
        ),
        "output_contract": "输出：缺口、建议参数、断言建议、可执行下一步。",
    },
    "failure_diagnosis": {
        "title": "失败诊断",
        "instruction": (
            "用户提供报错、日志、失败结果或说不能用。先分类：环境、数据、鉴权、断言、"
            "接口缺陷、超时、依赖不可用。用证据支撑判断，给最小复现和修复顺序。"
        ),
        "output_contract": "输出：失败类型、证据、根因假设、排查步骤、修复建议。",
    },
    "security_testing": {
        "title": "安全测试",
        "instruction": (
            "用户讨论安全扫描、漏洞或风险。重点覆盖鉴权绕过、越权、注入、敏感信息泄露、"
            "CORS、限流、文件上传、路径穿越、SSRF、错误信息泄露。高危项必须给复测标准。"
        ),
        "output_contract": "按问题严重程度说明扫描范围、重点检查项、修复建议和复测标准；不要用于寒暄。",
    },
    "performance_testing": {
        "title": "性能测试",
        "instruction": (
            "用户讨论压测、TPS、响应时间或容量。明确并发、持续时间、爬坡、目标 TPS、"
            "超时、P95/P99、错误率和 SLA。没有真实结果时只给方案，不编造指标。"
        ),
        "output_contract": "输出：压测参数、SLA、观察指标、风险判断、调优方向。",
    },
    "reporting": {
        "title": "报告总结",
        "instruction": (
            "用户想看报告、进展、质量结论或管理摘要。优先总结范围、通过率、失败聚类、"
            "安全/性能风险、上线阻断项和下一步 owner。"
        ),
        "output_contract": "输出：摘要、关键风险、证据、建议动作。",
    },
    "workflow_bootstrap": {
        "title": "全流程搭建",
        "instruction": (
            "用户想从零开始、批量推进，或一次性创建项目、需求、用例和示范接口。"
            "优先调用 orchestrate_testing_workflow(workflow=full_e2e_bootstrap)，"
            "把项目名、需求标题/内容、用例目标/步骤、示范接口 method/url/body/assertions 一次性传入。"
            "缺少业务细节时用安全的示范接口模板先建骨架，但不要编造真实业务已完成。"
        ),
        "output_contract": "先执行全流程工具；返回创建出的 projectId、requirementId、caseId、collectionId、requestId 和下一步验证动作。",
    },
    "general": {
        "title": "通用协作",
        "instruction": "用户问题不属于明确测试子任务。保持简洁自然，像同事协作，不要强行分析风险或列流程。",
        "output_contract": "输出自然中文；寒暄或确认类一句话即可。",
    },
}

DEFAULT_AGENTS: list[dict[str, Any]] = [
    {
        "key": "orchestrator",
        "title": "测试编排 Agent",
        "description": "判断用户意图、选择专家 Agent、合并上下文并控制回答边界。",
        "task_type": "general",
        "allowed_tools": [
            "invoke_mcp_tool",
            "orchestrate_testing_workflow",
            "analyze_page_context",
            "list_projects",
            "create_project_record",
            "list_requirements_records",
            "list_test_cases_records",
            "explain_security_perf_config",
        ],
        "priority": 0,
    },
    {
        "key": "workflow_agent",
        "title": "全流程搭建 Agent",
        "description": "一次性搭建项目、需求、测试用例、示范接口，并按需触发执行、安全和性能验证。",
        "task_type": "workflow_bootstrap",
        "allowed_tools": [
            "orchestrate_testing_workflow",
            "create_project_record",
            "create_requirement_record",
            "create_test_case_record",
            "create_api_test_case",
            "execute_api_test_case",
            "run_security_test",
            "run_performance_test",
            "list_projects",
            "list_requirements_records",
            "list_test_cases_records",
        ],
        "priority": 5,
    },
    {
        "key": "requirement_agent",
        "title": "需求分析 Agent",
        "description": "提取业务规则、验收标准、测试切面和待确认问题。",
        "task_type": "requirement_analysis",
        "allowed_tools": [
            "create_requirement_doc",
            "create_requirement_record",
            "update_requirement_record",
            "list_requirements_records",
            "analyze_test_gap",
            "analyze_page_context",
        ],
        "priority": 10,
    },
    {
        "key": "case_agent",
        "title": "用例设计 Agent",
        "description": "设计可落库、可执行、可验证的测试用例和测试点。",
        "task_type": "case_generation",
        "allowed_tools": [
            "create_test_case_record",
            "update_test_case_record",
            "list_test_cases_records",
            "create_api_test_case",
            "generate_api_steps_from_requirement",
            "bind_existing_request_to_case",
            "precheck_api_case_steps",
            "analyze_test_gap",
        ],
        "priority": 20,
    },
    {
        "key": "api_agent",
        "title": "接口测试 Agent",
        "description": "检查接口参数、环境变量、断言、错误码和联调问题。",
        "task_type": "api_testing",
        "allowed_tools": [
            "create_api_test_case",
            "update_api_test_parameter",
            "update_api_test_script",
            "bind_existing_request_to_case",
            "remove_api_step_from_case",
            "reorder_api_steps",
            "precheck_api_case_steps",
            "execute_api_test_case",
            "get_latest_failed_log",
            "summarize_run_failures",
        ],
        "priority": 30,
    },
    {
        "key": "failure_agent",
        "title": "失败诊断 Agent",
        "description": "分析报错、失败日志、断言失败和根因假设。",
        "task_type": "failure_diagnosis",
        "allowed_tools": ["get_latest_failed_log", "summarize_run_failures", "recommend_regression_scope", "execute_api_test_case"],
        "priority": 40,
    },
    {
        "key": "security_agent",
        "title": "安全测试 Agent",
        "description": "识别鉴权、越权、注入、敏感信息、CORS、SSRF 等安全风险。",
        "task_type": "security_testing",
        "allowed_tools": ["run_security_test", "run_ui_or_security_scan", "explain_security_perf_config"],
        "priority": 50,
    },
    {
        "key": "performance_agent",
        "title": "性能测试 Agent",
        "description": "设计压测参数、SLA、容量风险和瓶颈排查路径。",
        "task_type": "performance_testing",
        "allowed_tools": ["run_performance_test", "explain_security_perf_config"],
        "priority": 60,
    },
    {
        "key": "report_agent",
        "title": "测试报告 Agent",
        "description": "总结范围、通过率、失败聚类、质量风险和上线建议。",
        "task_type": "reporting",
        "allowed_tools": ["summarize_run_failures", "recommend_regression_scope", "analyze_test_gap"],
        "priority": 70,
    },
]

DEFAULT_HOOKS: list[dict[str, Any]] = [
    {"key": "context_limit_hook", "stage": "before_context_build", "title": "上下文裁剪", "config": {"maxContextChars": 8000}},
    {"key": "tool_permission_hook", "stage": "before_tool_call", "title": "工具权限校验", "config": {}},
    {"key": "destructive_action_hook", "stage": "before_tool_call", "title": "高风险动作确认", "config": {"destructiveTools": ["delete", "batch", "force", "purge"]}},
    {"key": "memory_extract_hook", "stage": "after_response_persist", "title": "记忆抽取", "config": {"enabled": True}},
    {"key": "session_summary_hook", "stage": "after_response_persist", "title": "会话摘要", "config": {"messageThreshold": 30, "recentMessages": 12}},
]

DEFAULT_PLUGINS: list[dict[str, Any]] = [
    {"key": "platform-testing-tools", "title": "平台测试工具", "type": "internal_tool", "config": {"tools": "SYSTEM_TOOLS"}},
    {"key": "smithery-mcp", "title": "Smithery MCP", "type": "mcp", "config": {"provider": "smithery"}},
    {"key": "default-testing-agents", "title": "默认测试专家 Agent 包", "type": "agent_pack", "config": {"agents": [item["key"] for item in DEFAULT_AGENTS]}},
    {"key": "default-testing-hooks", "title": "默认测试 Hooks 包", "type": "hook_pack", "config": {"hooks": [item["key"] for item in DEFAULT_HOOKS]}},
]

TASK_AGENT_MAP: dict[str, list[str]] = {
    "workflow_bootstrap": ["workflow_agent", "requirement_agent", "case_agent"],
    "requirement_analysis": ["requirement_agent", "case_agent"],
    "case_generation": ["case_agent", "requirement_agent"],
    "api_testing": ["api_agent"],
    "failure_diagnosis": ["failure_agent", "api_agent"],
    "security_testing": ["security_agent", "api_agent"],
    "performance_testing": ["performance_agent", "api_agent"],
    "reporting": ["report_agent", "failure_agent"],
    "general": ["orchestrator"],
}

SYSTEM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_api_test_script",
            "description": "更新或修复指定 API 测试请求的测试断言脚本（test_script）",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "需要被修改的 API 请求 ID"},
                    "test_script": {"type": "string", "description": "更新后的完整测试脚本内容（JavaScript 纯代码格式）"},
                },
                "required": ["request_id", "test_script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_requirement_doc",
            "description": "根据沟通内容生成结构化的需求文档，并保存入库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "需求标题"},
                    "content": {"type": "string", "description": "需求内容的详细 Markdown"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_api_test_case",
            "description": "自动在系统中生成一份全新的接口测试用例（包括请求和初始断言参数）",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "description": "要绑定的测试用例 ID（可选，建议传）"},
                    "project_id": {"type": "string", "description": "项目 ID（可选，未传则尝试从 case_id 推断）"},
                    "collection_id": {"type": "string", "description": "接口集合 ID（可选，未传则自动选择或创建）"},
                    "name": {"type": "string", "description": "接口测试用例名称"},
                    "method": {"type": "string", "description": "请求方法，如 GET, POST"},
                    "url": {"type": "string", "description": "请求URL（例如 /api/v1/login）"},
                    "body_raw": {"type": "string", "description": "JSON 格式的请求体数据（如果有）"},
                    "body_mode": {"type": "string", "description": "请求体模式，none/raw/json/form（可选）"},
                    "headers": {"type": "array", "items": {"type": "object"}, "description": "请求头数组（可选）"},
                    "query": {"type": "array", "items": {"type": "object"}, "description": "查询参数数组（可选）"},
                    "test_script": {"type": "string", "description": "使用 JavaScript 编写的断言测试脚本"},
                },
                "required": ["name", "method", "url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_api_test_parameter",
            "description": "更改指定接口测试用例的基础参数，如请求 URL, Header, 测试参数数据等",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "API 请求ID"},
                    "update_fields": {
                        "type": "object",
                        "description": "需要更新的字段名及对应的值字典。例如 {\"url\": \"/new/api\", \"method\": \"POST\"}",
                        "additionalProperties": True,
                    },
                },
                "required": ["request_id", "update_fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bind_existing_request_to_case",
            "description": "将已有 API 请求 request_id 绑定到指定测试用例的 payload.apiSteps。",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "description": "测试用例 ID"},
                    "request_id": {"type": "string", "description": "已有 API 请求 ID"},
                    "name": {"type": "string", "description": "步骤显示名称（可选）"},
                },
                "required": ["case_id", "request_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_api_step_from_case",
            "description": "从测试用例 payload.apiSteps 中删除指定步骤（按 request_id 或 index）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "description": "测试用例 ID"},
                    "request_id": {"type": "string", "description": "要删除的请求 ID（可选）"},
                    "index": {"type": "integer", "description": "要删除的步骤索引（0-based，可选）"},
                },
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reorder_api_steps",
            "description": "重排测试用例 payload.apiSteps 顺序。",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "description": "测试用例 ID"},
                    "request_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "按目标顺序排列的 request_id 列表",
                    },
                },
                "required": ["case_id", "request_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "precheck_api_case_steps",
            "description": "批量执行 API 步骤前预检查：requestId 存在性、method/url 完整性、JSON 合法性。",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "description": "测试用例 ID"},
                },
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_api_steps_from_requirement",
            "description": "根据需求内容自动生成并绑定 API 步骤到指定用例（落库到 api_requests + case.payload.apiSteps）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "需求 ID"},
                    "case_id": {"type": "string", "description": "目标测试用例 ID"},
                    "collection_id": {"type": "string", "description": "接口集合 ID（可选）"},
                    "count": {"type": "integer", "description": "生成步骤数量，默认 3，最大 8"},
                },
                "required": ["requirement_id", "case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_ui_or_security_scan",
            "description": "触发辅助进行本地 UI 自动化测试扫描或安全扫描动作。这是一个调度方法。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scan_type": {"type": "string", "enum": ["ui", "security"], "description": "扫描类型"},
                    "target_url": {"type": "string", "description": "扫描目标地址 URL"},
                },
                "required": ["scan_type", "target_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_performance_test",
            "description": "对指定接口集合执行性能测试（压测），返回吞吐、延迟和错误率结果摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string", "description": "要压测的接口集合 ID"},
                    "project_id": {"type": "string", "description": "项目 ID（不传则从集合读取）"},
                    "environment_id": {"type": "string", "description": "环境 ID（可选）"},
                    "request_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "指定执行的请求 ID 列表（可选）",
                    },
                    "vus": {"type": "integer", "description": "虚拟用户数"},
                    "duration_seconds": {"type": "integer", "description": "持续时间（秒）"},
                    "ramp_up_seconds": {"type": "integer", "description": "爬坡时间（秒）"},
                    "target_tps": {"type": "integer", "description": "目标 TPS（可选）"},
                    "timeout_ms": {"type": "integer", "description": "单请求超时（毫秒）"},
                    "verify_ssl": {"type": "boolean", "description": "是否校验证书"},
                },
                "required": ["collection_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_security_test",
            "description": "执行安全扫描，可按接口集合（collection_id）或目标网址（target_url）扫描，返回漏洞统计和风险摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string", "description": "要扫描的接口集合 ID"},
                    "target_url": {"type": "string", "description": "要扫描的目标网址（可选，填写后按网址模式扫描）"},
                    "project_id": {"type": "string", "description": "项目 ID（不传则从集合读取）"},
                    "environment_id": {"type": "string", "description": "环境 ID（可选）"},
                    "request_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "指定扫描的请求 ID 列表（可选）",
                    },
                    "scan_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "扫描类型：owasp_api / pii_scan / auth_bypass / security_headers / cors_misconfig / xss_reflection / error_leak / insecure_transport / idor_enumeration / path_traversal / ssrf_probe / file_upload_security / command_template_injection / jwt_session_security / rate_limit_bruteforce",
                    },
                    "max_discovered_urls": {"type": "integer", "description": "网址模式下最多探测 URL 数量，默认 8，最大 30"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_api_test_case",
            "description": "真实发起一次 API HTTP 请求，用以验证测试接口的功能是否正常或排查报错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "要执行的 API 请求 ID"},
                },
                "required": ["request_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_failed_log",
            "description": "获取指定 API 测试接口最后一次失败的执行报错日志，通常用于自愈机制 (Auto-healing) 分析",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "需要查询的 API 请求 ID"},
                },
                "required": ["request_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_run_failures",
            "description": "汇总最近一段时间接口执行失败记录，按错误类型聚类并给出修复建议与下一步动作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string", "description": "接口集合 ID（可选）"},
                    "request_id": {"type": "string", "description": "接口请求 ID（可选）"},
                    "limit": {"type": "integer", "description": "分析的失败记录数量上限，默认 20，最大 100"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_regression_scope",
            "description": "基于最近失败、历史执行和接口更新时间，推荐最小回归范围。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID（可选，建议传）"},
                    "collection_id": {"type": "string", "description": "集合 ID（可选）"},
                    "changed_within_days": {"type": "integer", "description": "仅推荐最近 N 天有更新的接口（可选）"},
                    "limit": {"type": "integer", "description": "推荐接口数量上限，默认 10，最大 50"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_test_gap",
            "description": "分析需求与测试用例覆盖缺口，输出未覆盖需求、覆盖偏弱需求与补齐建议。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID（可选，建议传）"},
                    "requirement_id": {"type": "string", "description": "指定需求 ID（可选）"},
                    "limit": {"type": "integer", "description": "返回缺口项数量上限，默认 10，最大 50"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "列出平台内项目，可按关键词搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "项目名称关键词（可选）"},
                    "limit": {"type": "integer", "description": "返回数量上限，默认 20，最大 100"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_project_record",
            "description": "创建项目记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "org_id": {"type": "string", "description": "组织 ID（不传默认 DEFAULT_ORG）"},
                    "name": {"type": "string", "description": "项目名称"},
                    "description": {"type": "string", "description": "项目描述（可选）"},
                    "created_by": {"type": "string", "description": "创建人 ID（可选）"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project_record",
            "description": "更新项目名称或描述。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID"},
                    "name": {"type": "string", "description": "项目名称（可选）"},
                    "description": {"type": "string", "description": "项目描述（可选）"},
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_project_record",
            "description": "删除项目（软删除）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID"},
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_requirements_records",
            "description": "列出需求，可按项目和关键词过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID（可选）"},
                    "q": {"type": "string", "description": "标题/内容关键词（可选）"},
                    "status": {"type": "string", "description": "需求状态（可选）"},
                    "limit": {"type": "integer", "description": "返回数量上限，默认 20，最大 100"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_requirement_record",
            "description": "创建需求记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID"},
                    "org_id": {"type": "string", "description": "组织 ID（不传默认 DEFAULT_ORG）"},
                    "title": {"type": "string", "description": "需求标题"},
                    "content": {"type": "string", "description": "需求内容（Markdown 文本）"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（可选）"},
                    "created_by": {"type": "string", "description": "创建人 ID（可选）"},
                },
                "required": ["project_id", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_requirement_record",
            "description": "更新需求记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "需求 ID"},
                    "title": {"type": "string", "description": "需求标题（可选）"},
                    "content": {"type": "string", "description": "需求内容（可选）"},
                    "status": {"type": "string", "description": "需求状态（可选）"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（可选）"},
                },
                "required": ["requirement_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_requirement_record",
            "description": "删除需求（软删除）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "需求 ID"},
                },
                "required": ["requirement_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_test_cases_records",
            "description": "列出测试用例，可按项目、类型、状态和关键词过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID（可选）"},
                    "kind": {"type": "string", "description": "用例类型（api/ui/security/performance 等，可选）"},
                    "status": {"type": "string", "description": "用例状态（可选）"},
                    "q": {"type": "string", "description": "标题关键词（可选）"},
                    "limit": {"type": "integer", "description": "返回数量上限，默认 20，最大 100"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_test_case_record",
            "description": "创建测试用例记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID"},
                    "org_id": {"type": "string", "description": "组织 ID（不传默认 DEFAULT_ORG）"},
                    "title": {"type": "string", "description": "用例标题"},
                    "kind": {"type": "string", "description": "用例类型，默认 manual"},
                    "objective": {"type": "string", "description": "测试目标（可选）"},
                    "steps": {"type": "array", "items": {"type": "string"}, "description": "测试步骤（可选）"},
                    "assertion_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "断言要点（可选）",
                    },
                    "payload": {"type": "object", "description": "结构化参数（可选）"},
                    "requirement_id": {"type": "string", "description": "关联需求 ID（可选，等价 spec_id）"},
                    "spec_id": {"type": "string", "description": "关联需求文档 ID（可选，优先于 requirement_id）"},
                    "priority": {"type": "string", "description": "优先级 P0/P1/P2/P3（可选）"},
                    "status": {"type": "string", "description": "状态（可选）"},
                    "created_by": {"type": "string", "description": "创建人 ID（可选）"},
                    "collection_id": {"type": "string", "description": "接口集合 ID（可选，自动附加接口步骤时使用）"},
                    "api_url": {"type": "string", "description": "若提供则自动创建并挂载 1 条接口步骤"},
                    "api_method": {"type": "string", "description": "自动接口步骤方法（默认 GET）"},
                    "api_name": {"type": "string", "description": "自动接口步骤名称（可选）"},
                    "api_headers": {"type": "array", "items": {"type": "object"}, "description": "自动接口步骤 headers（可选）"},
                    "api_query": {"type": "array", "items": {"type": "object"}, "description": "自动接口步骤 query（可选）"},
                    "api_body_mode": {"type": "string", "description": "自动接口步骤 body 模式（可选）"},
                    "api_body_raw": {"type": "string", "description": "自动接口步骤 body 文本（可选）"},
                    "api_test_script": {"type": "string", "description": "自动接口步骤断言脚本（可选）"},
                },
                "required": ["project_id", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_test_case_record",
            "description": "更新测试用例记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "description": "用例 ID"},
                    "title": {"type": "string", "description": "用例标题（可选）"},
                    "kind": {"type": "string", "description": "用例类型（可选）"},
                    "objective": {"type": "string", "description": "测试目标（可选）"},
                    "steps": {"type": "array", "items": {"type": "string"}, "description": "步骤（可选）"},
                    "assertion_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "断言要点（可选）",
                    },
                    "payload": {"type": "object", "description": "结构化参数（可选）"},
                    "priority": {"type": "string", "description": "优先级（可选）"},
                    "status": {"type": "string", "description": "状态（可选）"},
                },
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_test_case_record",
            "description": "删除测试用例（软删除）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "description": "用例 ID"},
                },
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_security_perf_config",
            "description": "输出安全测试与性能测试的配置模板、参数建议和常见场景预设。",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string", "description": "接口集合 ID（可选）"},
                    "goal": {"type": "string", "description": "目标，例如 baseline、high-risk、release-gate（可选）"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_page_context",
            "description": "基于当前页面上下文（path/query/module/title）给出可执行测试建议与下一步动作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_path": {"type": "string", "description": "当前路由 path"},
                    "query": {"type": "string", "description": "当前 query string"},
                    "active_module": {"type": "string", "description": "当前模块标识"},
                    "page_title": {"type": "string", "description": "页面标题"},
                    "focus": {"type": "string", "description": "用户关注点（如功能、稳定性、安全）"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orchestrate_testing_workflow",
            "description": "编排并执行多步测试工作流，支持覆盖/稳定性分析，以及全流程资产搭建（项目→需求→用例→接口→安全/性能）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow": {
                        "type": "string",
                        "description": "工作流类型：coverage_scan / stability_scan / release_gate / full_e2e_bootstrap / api_regression_flow / security_perf_flow",
                    },
                    "project_id": {"type": "string", "description": "项目 ID（可选）"},
                    "collection_id": {"type": "string", "description": "接口集合 ID（可选）"},
                    "requirement_id": {"type": "string", "description": "已有需求 ID（可选）"},
                    "case_id": {"type": "string", "description": "已有测试用例 ID（可选）"},
                    "request_id": {"type": "string", "description": "已有接口请求 ID（可选）"},
                    "project_name": {"type": "string", "description": "全流程搭建时创建的项目名称"},
                    "project_description": {"type": "string", "description": "全流程搭建时创建的项目描述"},
                    "requirement_title": {"type": "string", "description": "全流程搭建时创建的需求标题"},
                    "requirement_content": {"type": "string", "description": "全流程搭建时创建的需求正文，建议包含目标、规则、验收标准和边界场景"},
                    "case_title": {"type": "string", "description": "全流程搭建时创建的测试用例标题"},
                    "case_objective": {"type": "string", "description": "测试用例目标"},
                    "case_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "测试用例步骤",
                    },
                    "assertion_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "断言要点",
                    },
                    "priority": {"type": "string", "description": "用例优先级，如 P0/P1/P2/P3"},
                    "api_name": {"type": "string", "description": "示范接口名称"},
                    "api_method": {"type": "string", "description": "示范接口方法，如 GET/POST/PUT/DELETE"},
                    "api_url": {"type": "string", "description": "示范接口路径或完整 URL"},
                    "api_headers": {"type": "array", "items": {"type": "object"}, "description": "示范接口请求头"},
                    "api_query": {"type": "array", "items": {"type": "object"}, "description": "示范接口 query 参数"},
                    "api_body_mode": {"type": "string", "description": "示范接口 body 模式：none/raw/json/form"},
                    "api_body_raw": {"type": "string", "description": "示范接口 body 文本"},
                    "api_test_script": {"type": "string", "description": "示范接口断言脚本"},
                    "limit": {"type": "integer", "description": "分析样本数量上限，默认 20"},
                    "execute": {"type": "boolean", "description": "是否执行可执行步骤（默认 false）"},
                    "run_security": {"type": "boolean", "description": "全流程执行后是否触发安全扫描，默认 true"},
                    "run_performance": {"type": "boolean", "description": "全流程执行后是否触发性能测试，默认 true"},
                    "target_url": {"type": "string", "description": "安全+性能联测中的目标 URL（无 collection_id 时可用于安全扫描）"},
                    "environment_id": {"type": "string", "description": "执行接口/压测时使用的环境 ID"},
                    "vus": {"type": "integer", "description": "性能测试虚拟用户数"},
                    "duration_seconds": {"type": "integer", "description": "性能测试持续时间"},
                    "ramp_up_seconds": {"type": "integer", "description": "性能测试爬坡时间"},
                    "timeout_ms": {"type": "integer", "description": "请求超时时间"},
                    "verify_ssl": {"type": "boolean", "description": "是否校验证书"},
                },
                "required": ["workflow"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invoke_mcp_tool",
            "description": "调用已安装的 MCP 工具（通过 smithery 连接）并返回结果摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection_id": {"type": "string", "description": "MCP 连接 ID（例如 filesystem、github）"},
                    "tool_name": {"type": "string", "description": "工具名称"},
                    "payload": {"type": "object", "description": "工具调用参数 JSON"},
                },
                "required": ["connection_id", "tool_name"],
            },
        },
    },
]


# =====================================================================
# 工具执行引擎
# =====================================================================
async def execute_tool_call(
    tool_name: str,
    arguments_json: str,
    db: Database,
    *,
    actor_id: str | None = None,
    api_testing: "ApiTestingService | None" = None,
    performance_testing: "PerformanceTestingService | None" = None,
    security_testing: "SecurityTestingService | None" = None,
    smithery: "SmitheryService | None" = None,
) -> str:
    """本地执行大模型意图对应的方法"""
    try:
        args = json.loads(arguments_json)
    except json.JSONDecodeError:
        return "参数必须是合法的 JSON 字符串。"

    logger.info("执行智能工具 [%s] 参数: %r", tool_name, args)

    def _infer_risk_level(name: str) -> str:
        high = {
            "delete_project_record",
            "delete_requirement_record",
            "delete_test_case_record",
            "remove_api_step_from_case",
        }
        medium = {
            "create_project_record",
            "update_project_record",
            "create_requirement_record",
            "update_requirement_record",
            "create_test_case_record",
            "update_test_case_record",
            "create_api_test_case",
            "update_api_test_parameter",
            "update_api_test_script",
            "bind_existing_request_to_case",
            "reorder_api_steps",
            "generate_api_steps_from_requirement",
        }
        if name in high:
            return "high"
        if name in medium:
            return "medium"
        return "low"

    def _tool_ok(
        message: str,
        data: dict[str, Any] | None = None,
        actions: list[dict[str, Any]] | None = None,
        risk_level: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "ok": True,
            "tool": tool_name,
            "message": message,
            "riskLevel": risk_level or _infer_risk_level(tool_name),
        }
        if isinstance(data, dict):
            payload["data"] = data
        if isinstance(actions, list):
            payload["actions"] = actions
        return json.dumps(payload, ensure_ascii=False)

    def _tool_error(
        message: str,
        code: str = "TOOL_ERROR",
        data: dict[str, Any] | None = None,
        risk_level: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "ok": False,
            "tool": tool_name,
            "riskLevel": risk_level or _infer_risk_level(tool_name),
            "error": {"code": code, "message": message},
        }
        if isinstance(data, dict):
            payload["data"] = data
        return json.dumps(payload, ensure_ascii=False)

    def _resolve_actor_org_ids() -> set[str]:
        if not actor_id:
            return {"DEFAULT_ORG"}
        rows = db.fetchall(
            """
            SELECT DISTINCT t.org_id
            FROM team_members tm
            JOIN teams t ON t.id = tm.team_id
            WHERE tm.user_id = ?
            """,
            (actor_id,),
        )
        org_ids = {str(row.get("org_id") or "").strip() for row in rows if str(row.get("org_id") or "").strip()}
        if not org_ids:
            org_ids.add("DEFAULT_ORG")
        return org_ids

    actor_org_ids = _resolve_actor_org_ids()

    if tool_name == "invoke_mcp_tool":
        connection_id = str(args.get("connection_id") or "").strip()
        mcp_tool_name = str(args.get("tool_name") or "").strip()
        payload_raw = args.get("payload", {})
        payload_obj = payload_raw if isinstance(payload_raw, dict) else {}
        if not connection_id or not mcp_tool_name:
            return _tool_error("缺少 connection_id 或 tool_name。", "INVALID_ARGUMENT")
        if not smithery:
            return _tool_error("MCP 服务未就绪，无法调用外部工具。", "MCP_UNAVAILABLE")
        result = smithery.call_tool(connection_id, mcp_tool_name, payload_obj)
        ok = bool(getattr(result, "ok", False))
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        exit_code = getattr(result, "exitCode", None)
        if not ok:
            return _tool_error(
                f"MCP 工具调用失败：{stderr or 'unknown error'}",
                "MCP_TOOL_CALL_FAILED",
                data={
                    "connectionId": connection_id,
                    "toolName": mcp_tool_name,
                    "exitCode": exit_code,
                    "stderr": stderr[:1500],
                },
            )
        return _tool_ok(
            "MCP 工具调用成功。",
            data={
                "connectionId": connection_id,
                "toolName": mcp_tool_name,
                "exitCode": exit_code,
                "stdout": stdout[:3000],
            },
            actions=[
                {"label": "查看该连接工具列表", "command": f"请查询 MCP 连接 {connection_id} 的工具列表"},
            ],
        )

    def _assert_org_access(target_org_id: str | None) -> str | None:
        normalized = str(target_org_id or "DEFAULT_ORG").strip() or "DEFAULT_ORG"
        if normalized not in actor_org_ids:
            return f"无权限访问组织 {normalized} 的数据。"
        return None

    def _project_org(project_id: str) -> str | None:
        row = db.fetchone("SELECT org_id FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,))
        return str(row.get("org_id") or "").strip() if row else None

    def _requirement_org(requirement_id: str) -> str | None:
        row = db.fetchone("SELECT org_id FROM requirements WHERE id = ? AND deleted_at IS NULL", (requirement_id,))
        return str(row.get("org_id") or "").strip() if row else None

    def _case_org(case_id: str) -> str | None:
        row = db.fetchone("SELECT org_id FROM cases WHERE id = ? AND deleted_at IS NULL", (case_id,))
        return str(row.get("org_id") or "").strip() if row else None

    def _load_case_payload(case_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        row = db.fetchone(
            "SELECT id, org_id, project_id, title, payload_json, kind FROM cases WHERE id = ? AND deleted_at IS NULL",
            (case_id,),
        )
        if not row:
            return {}, None
        payload_obj: dict[str, Any] = {}
        payload_raw = row.get("payload_json")
        if isinstance(payload_raw, str) and payload_raw.strip():
            try:
                parsed = json.loads(payload_raw)
                if isinstance(parsed, dict):
                    payload_obj = parsed
            except Exception:
                payload_obj = {}
        return payload_obj, row

    def _save_case_payload(case_id: str, payload_obj: dict[str, Any], *, force_api_kind: bool = True) -> None:
        if force_api_kind:
            db.execute(
                """
                UPDATE cases
                SET kind = 'api',
                    payload_json = ?,
                    updated_at = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (json.dumps(payload_obj, ensure_ascii=False), utc_now(), case_id),
            )
        else:
            db.execute(
                """
                UPDATE cases
                SET payload_json = ?,
                    updated_at = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (json.dumps(payload_obj, ensure_ascii=False), utc_now(), case_id),
            )

    if tool_name == "update_api_test_script":
        req_id = args.get("request_id", "")
        script = args.get("test_script", "")
        if not req_id or not script:
            return _tool_error(
                "缺少 request_id 或 test_script 字段，无法更新接口脚本。",
                code="INVALID_ARGUMENT",
                data={
                    "required": ["request_id", "test_script"],
                    "received": sorted([k for k in args.keys()]),
                },
            )

        # 校验对应的请求是否存在
        row = db.fetchone("SELECT id, name FROM api_requests WHERE id = ?", (req_id,))
        if not row:
            return _tool_error(
                f"系统中找不到编号为 [{req_id}] 的 API 测试接口。",
                code="NOT_FOUND",
                data={"request_id": req_id},
            )

        # 执行真实热更修改
        try:
            db.execute("UPDATE api_requests SET test_script = ?, updated_at = datetime('now') WHERE id = ?", (script, req_id))
            return _tool_ok(
                f"已成功更新接口「{row['name']}」（ID: {req_id}）的自动化测试脚本。",
                data={"request_id": req_id, "request_name": row["name"]},
            )
        except Exception as e:
            return _tool_error(
                f"更新数据库出现异常：{e}",
                code="DB_ERROR",
                data={"request_id": req_id},
            )

    elif tool_name == "create_requirement_doc":
        import uuid
        from datetime import datetime as _dt
        req_id = "req_" + uuid.uuid4().hex[:8]
        now = _dt.utcnow().replace(microsecond=0).isoformat() + "Z"
        title = args.get("title", "未命名需求")
        content = args.get("content", "")
        # 加入默认值逻辑处理直接生成
        org_id = "DEFAULT_ORG"
        project_id = "default_project"
        
        try:
            db.execute(
                "INSERT INTO requirements (id, org_id, project_id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (req_id, org_id, project_id, title, content, now, now)
            )
            return f"✅ 已为您新建需求文档：【{title}】（ID: {req_id}），您可以在项目管理列表中查看它。"
        except Exception as e:
            return f"创建需求失败：{e}"

    elif tool_name == "create_api_test_case":
        name = str(args.get("name") or "").strip() or "未命名接口步骤"
        method = str(args.get("method") or "GET").strip().upper()
        url = str(args.get("url") or "").strip()
        if not url:
            return _tool_error("生成接口用例失败：url 不能为空。", "INVALID_ARGUMENT")

        case_id = str(args.get("case_id") or "").strip()
        project_id = str(args.get("project_id") or "").strip()
        collection_id = str(args.get("collection_id") or "").strip()
        body_raw = str(args.get("body_raw") or "")
        body_mode = str(args.get("body_mode") or ("raw" if body_raw else "none")).strip().lower()
        test_script = str(args.get("test_script") or "")

        headers = args.get("headers") if isinstance(args.get("headers"), list) else []
        query = args.get("query") if isinstance(args.get("query"), list) else []

        case_row = None
        before_count = 0
        if case_id:
            payload_obj_tmp, case_row_tmp = _load_case_payload(case_id)
            case_row = case_row_tmp
            if not case_row:
                return _tool_error(f"找不到测试用例 {case_id}。", "NOT_FOUND")
            denied = _assert_org_access(case_row.get("org_id"))
            if denied:
                return _tool_error(denied, "FORBIDDEN")
            if not project_id:
                project_id = str(case_row.get("project_id") or "").strip()
            steps_tmp = payload_obj_tmp.get("apiSteps")
            before_count = len(steps_tmp) if isinstance(steps_tmp, list) else 0

        if project_id:
            proj_org = _project_org(project_id)
            if not proj_org:
                return _tool_error(f"项目 {project_id} 不存在。", "NOT_FOUND")
            denied = _assert_org_access(proj_org)
            if denied:
                return _tool_error(denied, "FORBIDDEN")

        # Resolve or auto-create API collection.
        if not collection_id:
            if project_id:
                row = db.fetchone(
                    """
                    SELECT id
                    FROM api_collections
                    WHERE project_id = ? AND deleted_at IS NULL
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (project_id,),
                )
                if row:
                    collection_id = str(row.get("id") or "")
                else:
                    proj = db.fetchone(
                        "SELECT org_id FROM projects WHERE id = ? AND deleted_at IS NULL",
                        (project_id,),
                    )
                    if not proj:
                        return _tool_error("无法自动创建集合：project_id 无效。", "INVALID_ARGUMENT")
                    collection_id = new_id("acol")
                    now = utc_now()
                    db.execute(
                        """
                        INSERT INTO api_collections (
                          id, org_id, project_id, name, description, variables_json, version,
                          created_by, deleted_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, '{}', 1, ?, NULL, ?, ?)
                        """,
                        (
                            collection_id,
                            str(proj.get("org_id") or "DEFAULT_ORG"),
                            project_id,
                            "AI 自动化集合",
                            "由 AI 自动创建，用于承载接口自动化步骤",
                            actor_id or "ai-agent",
                            now,
                            now,
                        ),
                    )
            else:
                return _tool_error("缺少 collection_id/project_id/case_id，无法确定接口归属。", "INVALID_ARGUMENT")

        coll_row = db.fetchone(
            """
            SELECT c.id, c.org_id, c.project_id
            FROM api_collections c
            WHERE c.id = ? AND c.deleted_at IS NULL
            """,
            (collection_id,),
        )
        if not coll_row:
            return _tool_error(f"接口集合 {collection_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(coll_row.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")

        if not project_id:
            project_id = str(coll_row.get("project_id") or "")

        request_id = new_id("areq")
        now = utc_now()
        try:
            db.execute(
                """
                INSERT INTO api_requests (
                  id, collection_id, parent_id, name, group_name, tags_json, method, url,
                  query_json, headers_json, body_mode, body_raw, body_form_json,
                  auth_type, auth_json, tests_json, pre_script, test_script,
                  is_folder, sort_order, created_by, deleted_at, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, 'default', '[]', ?, ?, ?, ?, ?, ?, '[]', 'none', '{}', '[]', '', ?, 0, 0, ?, NULL, ?, ?)
                """,
                (
                    request_id,
                    collection_id,
                    name,
                    method,
                    url,
                    json.dumps(query, ensure_ascii=False),
                    json.dumps(headers, ensure_ascii=False),
                    body_mode if body_mode in {"none", "raw", "json", "form"} else "raw",
                    body_raw,
                    test_script,
                    actor_id or "ai-agent",
                    now,
                    now,
                ),
            )
        except Exception as e:
            return _tool_error(f"写入接口请求失败：{e}", "DB_ERROR")

        linked_case = False
        after_count = before_count
        if case_row:
            try:
                payload_obj, _ = _load_case_payload(case_id)
                api_steps = payload_obj.get("apiSteps")
                if not isinstance(api_steps, list):
                    api_steps = []
                api_steps.append(
                    {
                        "name": name,
                        "requestId": request_id,
                        "collectionId": collection_id,
                        "method": method,
                        "url": url,
                        "bodyMode": body_mode if body_mode in {"none", "raw", "json", "form"} else "raw",
                        "bodyRaw": body_raw,
                        "headers": headers,
                        "query": query,
                        "testScript": test_script,
                    }
                )
                payload_obj["apiSteps"] = api_steps
                _save_case_payload(case_id, payload_obj, force_api_kind=True)
                linked_case = True
                after_count = len(api_steps)
            except Exception as e:
                # Compensation rollback: avoid orphan request if case binding failed.
                try:
                    db.execute("UPDATE api_requests SET deleted_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), request_id))
                except Exception:
                    pass
                return _tool_error(
                    f"请求已创建但绑定用例失败，已回滚请求。原因: {e}",
                    "CASE_BIND_FAILED",
                    data={"requestId": request_id, "caseId": case_id},
                )

        return _tool_ok(
            "接口步骤创建成功。",
            data={
                "requestId": request_id,
                "collectionId": collection_id,
                "projectId": project_id or None,
                "name": name,
                "method": method,
                "url": url,
                "linkedCase": linked_case,
                "caseId": case_id or None,
                "caseApiStepCountBefore": before_count if case_id else None,
                "caseApiStepCountAfter": after_count if case_id else None,
            },
            actions=[
                {"label": "执行该接口", "command": f"请调用 execute_api_test_case 工具，request_id={request_id}"},
                {"label": "查看最新失败日志", "command": f"请调用 get_latest_failed_log 工具，request_id={request_id}"},
            ],
        )

    elif tool_name == "generate_api_steps_from_requirement":
        requirement_id = str(args.get("requirement_id") or "").strip()
        case_id = str(args.get("case_id") or "").strip()
        collection_id = str(args.get("collection_id") or "").strip()
        count_raw = args.get("count", 3)
        try:
            count = max(1, min(int(count_raw), 8))
        except Exception:
            count = 3
        if not requirement_id or not case_id:
            return _tool_error("缺少 requirement_id 或 case_id。", "INVALID_ARGUMENT")

        req = db.fetchone(
            "SELECT id, org_id, project_id, title, content FROM requirements WHERE id = ? AND deleted_at IS NULL",
            (requirement_id,),
        )
        if not req:
            return _tool_error(f"需求 {requirement_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(req.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")

        payload_obj, case_row = _load_case_payload(case_id)
        if not case_row:
            return _tool_error(f"测试用例 {case_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(case_row.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")

        project_id = str(case_row.get("project_id") or req.get("project_id") or "").strip()
        if not project_id:
            return _tool_error("无法确定 project_id。", "INVALID_ARGUMENT")
        if not collection_id:
            row = db.fetchone(
                """
                SELECT id FROM api_collections
                WHERE project_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (project_id,),
            )
            if row:
                collection_id = str(row.get("id") or "")
            else:
                collection_id = new_id("acol")
                now = utc_now()
                db.execute(
                    """
                    INSERT INTO api_collections (
                      id, org_id, project_id, name, description, variables_json, version,
                      created_by, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, '{}', 1, ?, NULL, ?, ?)
                    """,
                    (
                        collection_id,
                        str(req.get("org_id") or "DEFAULT_ORG"),
                        project_id,
                        "需求生成集合",
                        f"由需求 {requirement_id} 自动生成",
                        actor_id or "ai-agent",
                        now,
                        now,
                    ),
                )

        title = str(req.get("title") or "需求接口")
        generated_defs = [
            {"name": f"{title}-健康检查", "method": "GET", "url": "/api/v1/health", "body_mode": "none", "body_raw": ""},
            {"name": f"{title}-主流程提交", "method": "POST", "url": "/api/v1/submit", "body_mode": "json", "body_raw": "{\"id\":\"demo\",\"payload\":{}}"},
            {"name": f"{title}-详情查询", "method": "GET", "url": "/api/v1/detail?id=demo", "body_mode": "none", "body_raw": ""},
            {"name": f"{title}-更新", "method": "PUT", "url": "/api/v1/update", "body_mode": "json", "body_raw": "{\"id\":\"demo\",\"status\":\"active\"}"},
            {"name": f"{title}-删除", "method": "DELETE", "url": "/api/v1/delete?id=demo", "body_mode": "none", "body_raw": ""},
        ][:count]

        api_steps = payload_obj.get("apiSteps")
        if not isinstance(api_steps, list):
            api_steps = []
        before = len(api_steps)
        created_request_ids: list[str] = []
        appended_steps: list[dict[str, Any]] = []

        try:
            for item in generated_defs:
                rid = new_id("areq")
                now = utc_now()
                db.execute(
                    """
                    INSERT INTO api_requests (
                      id, collection_id, parent_id, name, group_name, tags_json, method, url,
                      query_json, headers_json, body_mode, body_raw, body_form_json,
                      auth_type, auth_json, tests_json, pre_script, test_script,
                      is_folder, sort_order, created_by, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, NULL, ?, 'default', '[]', ?, ?, '[]', '[]', ?, ?, '[]', 'none', '{}', '[]', '', '', 0, 0, ?, NULL, ?, ?)
                    """,
                    (
                        rid,
                        collection_id,
                        item["name"],
                        item["method"],
                        item["url"],
                        item["body_mode"],
                        item["body_raw"],
                        actor_id or "ai-agent",
                        now,
                        now,
                    ),
                )
                created_request_ids.append(rid)
                step_obj = {
                    "name": item["name"],
                    "requestId": rid,
                    "collectionId": collection_id,
                    "method": item["method"],
                    "url": item["url"],
                    "bodyMode": item["body_mode"],
                    "bodyRaw": item["body_raw"],
                }
                appended_steps.append(step_obj)

            payload_obj["apiSteps"] = api_steps + appended_steps
            _save_case_payload(case_id, payload_obj, force_api_kind=True)
        except Exception as e:
            # Compensation rollback: remove all created requests for this batch.
            for rid in created_request_ids:
                try:
                    db.execute("UPDATE api_requests SET deleted_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), rid))
                except Exception:
                    pass
            return _tool_error(
                f"需求生成步骤失败，已回滚本批请求。原因: {e}",
                "BATCH_GENERATE_FAILED",
                data={"caseId": case_id, "rolledBackRequestIds": created_request_ids},
            )
        return _tool_ok(
            "已基于需求生成并绑定 API 步骤。",
            data={
                "requirementId": requirement_id,
                "caseId": case_id,
                "collectionId": collection_id,
                "createdRequestIds": created_request_ids,
                "before": before,
                "after": len(api_steps),
            },
            actions=[
                {"label": "预检查该用例步骤", "command": f"请调用 precheck_api_case_steps 工具，case_id={case_id}"},
            ],
        )

    elif tool_name == "update_api_test_parameter":
        req_id = args.get("request_id")
        fields = args.get("update_fields", {})
        if not req_id or not fields: return "更改失败：未提供 ID 或 参数字典。"
        
        row = db.fetchone("SELECT id, name FROM api_requests WHERE id = ?", (req_id,))
        if not row: return f"更改失败：找不到编号为 {req_id} 的用例。"
        
        # Build dynamic update
        set_clauses = []
        vals = []
        for k, v in fields.items():
            if k in ["url", "method", "body_raw", "query_json", "headers_json", "name", "body_mode"]:
                set_clauses.append(f"{k} = ?")
                vals.append(v if isinstance(v, str) else json.dumps(v))
        
        if not set_clauses: return "没有支持更新的参数字段"
        
        set_clauses.append("updated_at = datetime('now')")
        vals.append(req_id)
        
        query = f"UPDATE api_requests SET {', '.join(set_clauses)} WHERE id = ?"
        try:
            db.execute(query, tuple(vals))
            return f"✅ 已更新接口【{row['name']}】的 {list(fields.keys())} 参数信息！"
        except Exception as e:
            return f"参数更新失败：{e}"

    elif tool_name == "bind_existing_request_to_case":
        case_id = str(args.get("case_id") or "").strip()
        request_id = str(args.get("request_id") or "").strip()
        step_name = str(args.get("name") or "").strip()
        if not case_id or not request_id:
            return _tool_error("缺少 case_id 或 request_id。", "INVALID_ARGUMENT")

        payload_obj, case_row = _load_case_payload(case_id)
        if not case_row:
            return _tool_error(f"测试用例 {case_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(case_row.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")

        req_row = db.fetchone(
            """
            SELECT r.id, r.name, r.method, r.url, r.body_mode, r.body_raw, r.test_script, r.collection_id,
                   c.org_id
            FROM api_requests r
            JOIN api_collections c ON c.id = r.collection_id
            WHERE r.id = ? AND r.deleted_at IS NULL AND c.deleted_at IS NULL
            """,
            (request_id,),
        )
        if not req_row:
            return _tool_error(f"接口请求 {request_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(req_row.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")

        api_steps = payload_obj.get("apiSteps")
        if not isinstance(api_steps, list):
            api_steps = []
        before = len(api_steps)
        exists = any(str(item.get("requestId") or "").strip() == request_id for item in api_steps if isinstance(item, dict))
        if exists:
            return _tool_ok(
                "该 request 已绑定到用例，无需重复添加。",
                data={"caseId": case_id, "requestId": request_id, "before": before, "after": before},
            )
        api_steps.append(
            {
                "name": step_name or str(req_row.get("name") or "接口步骤"),
                "requestId": request_id,
                "collectionId": str(req_row.get("collection_id") or ""),
                "method": str(req_row.get("method") or "GET"),
                "url": str(req_row.get("url") or ""),
                "bodyMode": str(req_row.get("body_mode") or "none"),
                "bodyRaw": str(req_row.get("body_raw") or ""),
                "testScript": str(req_row.get("test_script") or ""),
            }
        )
        payload_obj["apiSteps"] = api_steps
        _save_case_payload(case_id, payload_obj, force_api_kind=True)
        return _tool_ok(
            "接口已绑定到测试用例。",
            data={"caseId": case_id, "requestId": request_id, "before": before, "after": len(api_steps)},
        )

    elif tool_name == "remove_api_step_from_case":
        case_id = str(args.get("case_id") or "").strip()
        request_id = str(args.get("request_id") or "").strip()
        index_raw = args.get("index")
        if not case_id:
            return _tool_error("缺少 case_id。", "INVALID_ARGUMENT")
        payload_obj, case_row = _load_case_payload(case_id)
        if not case_row:
            return _tool_error(f"测试用例 {case_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(case_row.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        api_steps = payload_obj.get("apiSteps")
        if not isinstance(api_steps, list) or not api_steps:
            return _tool_error("当前用例没有 apiSteps。", "EMPTY_SCOPE")
        before = len(api_steps)
        removed = None
        if request_id:
            next_steps = []
            for step in api_steps:
                if removed is None and isinstance(step, dict) and str(step.get("requestId") or "").strip() == request_id:
                    removed = step
                    continue
                next_steps.append(step)
            api_steps = next_steps
        elif index_raw is not None:
            try:
                idx = int(index_raw)
            except Exception:
                return _tool_error("index 必须是整数。", "INVALID_ARGUMENT")
            if idx < 0 or idx >= len(api_steps):
                return _tool_error("index 超出范围。", "INVALID_ARGUMENT")
            removed = api_steps.pop(idx)
        else:
            return _tool_error("请提供 request_id 或 index。", "INVALID_ARGUMENT")

        if removed is None:
            return _tool_error("未找到待删除步骤。", "NOT_FOUND")
        payload_obj["apiSteps"] = api_steps
        _save_case_payload(case_id, payload_obj, force_api_kind=True)
        return _tool_ok(
            "步骤已删除。",
            data={
                "caseId": case_id,
                "before": before,
                "after": len(api_steps),
                "removedRequestId": str(removed.get("requestId") or "") if isinstance(removed, dict) else None,
            },
        )

    elif tool_name == "reorder_api_steps":
        case_id = str(args.get("case_id") or "").strip()
        request_ids_raw = args.get("request_ids")
        if not case_id or not isinstance(request_ids_raw, list):
            return _tool_error("缺少 case_id 或 request_ids。", "INVALID_ARGUMENT")
        request_ids = [str(item).strip() for item in request_ids_raw if str(item).strip()]
        if not request_ids:
            return _tool_error("request_ids 不能为空。", "INVALID_ARGUMENT")
        payload_obj, case_row = _load_case_payload(case_id)
        if not case_row:
            return _tool_error(f"测试用例 {case_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(case_row.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        api_steps = payload_obj.get("apiSteps")
        if not isinstance(api_steps, list) or not api_steps:
            return _tool_error("当前用例没有 apiSteps。", "EMPTY_SCOPE")
        step_map = {
            str(step.get("requestId") or "").strip(): step
            for step in api_steps
            if isinstance(step, dict) and str(step.get("requestId") or "").strip()
        }
        missing = [rid for rid in request_ids if rid not in step_map]
        if missing:
            return _tool_error("request_ids 中存在未绑定步骤。", "INVALID_ARGUMENT", data={"missingRequestIds": missing})
        reordered = [step_map[rid] for rid in request_ids]
        remaining = [
            step for step in api_steps
            if not (isinstance(step, dict) and str(step.get("requestId") or "").strip() in set(request_ids))
        ]
        payload_obj["apiSteps"] = reordered + remaining
        _save_case_payload(case_id, payload_obj, force_api_kind=True)
        return _tool_ok(
            "步骤顺序已更新。",
            data={"caseId": case_id, "orderedRequestIds": request_ids, "total": len(payload_obj["apiSteps"])},
        )

    elif tool_name == "precheck_api_case_steps":
        case_id = str(args.get("case_id") or "").strip()
        if not case_id:
            return _tool_error("缺少 case_id。", "INVALID_ARGUMENT")
        payload_obj, case_row = _load_case_payload(case_id)
        if not case_row:
            return _tool_error(f"测试用例 {case_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(case_row.get("org_id"))
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        api_steps = payload_obj.get("apiSteps")
        if not isinstance(api_steps, list) or not api_steps:
            return _tool_error("当前用例没有 apiSteps。", "EMPTY_SCOPE")

        issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        checked = 0
        for idx, step in enumerate(api_steps):
            if not isinstance(step, dict):
                issues.append({"index": idx, "code": "INVALID_STEP", "message": "step 不是对象"})
                continue
            checked += 1
            rid = str(step.get("requestId") or "").strip()
            method = str(step.get("method") or "").strip().upper()
            url = str(step.get("url") or "").strip()
            if not method:
                issues.append({"index": idx, "code": "MISSING_METHOD", "message": "method 为空"})
            if not url:
                issues.append({"index": idx, "code": "MISSING_URL", "message": "url 为空"})
            if rid:
                req = db.fetchone("SELECT id, deleted_at FROM api_requests WHERE id = ?", (rid,))
                if not req or req.get("deleted_at") is not None:
                    issues.append({"index": idx, "code": "REQUEST_NOT_FOUND", "message": f"requestId {rid} 不存在"})
            else:
                warnings.append({"index": idx, "code": "NO_REQUEST_ID", "message": "未绑定 requestId，将按内联字段执行"})

            body_raw = step.get("bodyRaw")
            mode = str(step.get("bodyMode") or "").strip().lower()
            if mode in {"json", "raw"} and isinstance(body_raw, str) and body_raw.strip():
                text = body_raw.strip()
                if text.startswith("{") or text.startswith("["):
                    try:
                        json.loads(text)
                    except Exception:
                        issues.append({"index": idx, "code": "INVALID_JSON_BODY", "message": "bodyRaw 不是合法 JSON"})

        ok = len(issues) == 0
        return _tool_ok(
            "预检查完成。" if ok else "预检查发现问题。",
            data={"caseId": case_id, "ok": ok, "checked": checked, "issueCount": len(issues), "issues": issues, "warnings": warnings},
            actions=[
                {"label": "修复后再跑", "command": f"请先修复 case {case_id} 的 apiSteps 问题，再执行该用例"},
            ] if not ok else None,
        )

    elif tool_name == "run_ui_or_security_scan":
        scan_type = args.get("scan_type", "ui")
        target = args.get("target_url", "")
        if not target.startswith("http"):
            target = "https://" + target
            
        logger.info(f"Triggered background {scan_type} scan on {target}")
        
        if scan_type == "security":
            collection_id = str(args.get("collection_id") or "").strip()
            if collection_id and api_testing and security_testing:
                from app.models import ApiRequestPublic, ApiEnvironmentPublic, SecurityScanRequest

                collection = api_testing.get_collection(collection_id)
                if not collection:
                    return f"安全扫描失败：集合 {collection_id} 不存在。"
                requests_raw = api_testing.list_requests(collection_id)
                requests = [ApiRequestPublic.model_validate(r) for r in requests_raw if not bool(r.get("isFolder"))]
                if not requests:
                    return f"安全扫描失败：集合 {collection_id} 中没有可执行接口。"
                env = None
                environment_id = str(args.get("environment_id") or "").strip()
                if environment_id:
                    env_raw = api_testing.get_environment(environment_id)
                    if not env_raw:
                        return f"安全扫描失败：环境 {environment_id} 不存在。"
                    env = ApiEnvironmentPublic.model_validate(env_raw)

                result = await security_testing.run_security_scan(
                    request=SecurityScanRequest(
                        projectId=str(args.get("project_id") or collection.get("projectId") or "default_project"),
                        collectionIds=[collection_id],
                        scanTypes=list(args.get("scan_types") or [
                            "owasp_api",
                            "pii_scan",
                            "auth_bypass",
                            "security_headers",
                            "cors_misconfig",
                            "xss_reflection",
                            "error_leak",
                            "insecure_transport",
                            "idor_enumeration",
                            "path_traversal",
                            "ssrf_probe",
                            "file_upload_security",
                            "command_template_injection",
                            "jwt_session_security",
                            "rate_limit_bruteforce",
                        ]),
                    ),
                    collection_requests=requests,
                    env=env,
                )
                return (
                    "✅ 安全扫描完成。"
                    f"\n问题总数: {result.totalIssues}"
                    f"\n严重: {result.criticalCount} / 高危: {result.highCount} / 中危: {result.mediumCount} / 低危: {result.lowCount}"
                )

            # 真实通过 HTTP 获取基础安全头报告
            try:
                import httpx
                async with httpx.AsyncClient(verify=False, timeout=10) as client:
                    res = await client.get(target)
                headers = res.headers
                security_issues = []
                if "Strict-Transport-Security" not in headers:
                    security_issues.append("缺少 HSTS 头防降级攻击")
                if "X-Frame-Options" not in headers:
                    security_issues.append("缺少 X-Frame-Options 防点击劫持")
                if "Content-Security-Policy" not in headers:
                    security_issues.append("缺少 CSP 内容安全策略")
                
                status_text = "发现潜在安全风险！" if security_issues else "基础头安全策略合规。"
                return f"✅ 安全探针已探测 {target}。\n扫描结果: {status_text}\n风险项: {', '.join(security_issues) if security_issues else '无'}"
            except Exception as e:
                return f"安全扫描请求失败: {e}"
        else:
            agent_type = "全链路 UI 断言调度引擎"
            return f"✅ 已经成功启用了云端节点上的【{agent_type}】，正前往探测 {target}。任务正在后台异步执行，扫描完成后结果将推送到大盘的汇报分析控制台。"

    elif tool_name == "execute_api_test_case":
        req_id = args.get("request_id")
        if not req_id: return "未提供 request_id"
        if api_testing:
            try:
                run = await api_testing.send_request(
                    request_id=req_id,
                    created_by="ai-agent",
                    environment_id=str(args.get("environment_id") or "").strip() or None,
                    timeout_ms=int(args.get("timeout_ms") or 15000),
                    verify_ssl=bool(args.get("verify_ssl", True)),
                )
                status_code = run.get("statusCode")
                passed = bool(run.get("success"))
                duration_ms = int(run.get("durationMs") or 0)
                assertion_count = len(run.get("assertions") or [])
                if passed:
                    return (
                        f"执行成功 ✅！HTTP 状态码: {status_code}，耗时 {duration_ms}ms，"
                        f"断言数 {assertion_count}。运行ID: {run.get('id')}"
                    )
                return (
                    f"执行失败 ❌！状态码: {status_code}，耗时 {duration_ms}ms。"
                    f"\n错误: {run.get('errorMessage') or '断言未通过'}"
                    f"\n运行ID: {run.get('id')}"
                    "\n你可以调用 update_api_test_parameter 或 update_api_test_script 修复后重试。"
                )
            except Exception as e:
                return f"执行出错: {e}"

        row = db.fetchone("SELECT method, url FROM api_requests WHERE id = ?", (req_id,))
        if not row:
            return f"找不到接口 ID: {req_id}"
        return (
            f"请求 {req_id} 已找到，但当前 AI 会话未挂载执行引擎。"
            f"方法: {row.get('method')}，URL: {row.get('url')}。"
        )

    elif tool_name == "run_performance_test":
        if not api_testing or not performance_testing:
            return _tool_error("性能测试引擎不可用：当前 AI 服务未挂载 performance_testing。", "ENGINE_UNAVAILABLE")
        collection_id = str(args.get("collection_id") or "").strip()
        if not collection_id:
            return _tool_error("性能测试失败：缺少 collection_id。", "INVALID_ARGUMENT")
        from app.models import ApiEnvironmentPublic, ApiRequestPublic, PerformanceRunRequest

        collection = api_testing.get_collection(collection_id)
        if not collection:
            return _tool_error(f"性能测试失败：集合 {collection_id} 不存在。", "NOT_FOUND")
        requests_raw = api_testing.list_requests(collection_id)
        requests = [ApiRequestPublic.model_validate(r) for r in requests_raw if not bool(r.get("isFolder"))]
        request_ids = [str(item).strip() for item in (args.get("request_ids") or []) if str(item).strip()]
        if request_ids:
            selected = set(request_ids)
            requests = [item for item in requests if item.id in selected]
        if not requests:
            return _tool_error(f"性能测试失败：集合 {collection_id} 中没有可执行接口。", "EMPTY_SCOPE")

        env = None
        environment_id = str(args.get("environment_id") or "").strip()
        if environment_id:
            env_raw = api_testing.get_environment(environment_id)
            if not env_raw:
                return _tool_error(f"性能测试失败：环境 {environment_id} 不存在。", "NOT_FOUND")
            env = ApiEnvironmentPublic.model_validate(env_raw)

        request_payload = PerformanceRunRequest(
            collectionId=collection_id,
            projectId=str(args.get("project_id") or collection.get("projectId") or "default_project"),
            environmentId=environment_id or None,
            requestIds=request_ids or None,
            vus=max(1, int(args.get("vus") or 10)),
            durationSeconds=max(5, int(args.get("duration_seconds") or 30)),
            rampUpSeconds=max(0, int(args.get("ramp_up_seconds") or 5)),
            targetTps=(int(args["target_tps"]) if args.get("target_tps") is not None else None),
            timeoutMs=max(500, int(args.get("timeout_ms") or 15000)),
            verifySsl=bool(args.get("verify_ssl", True)),
        )
        result = await performance_testing.run_load_test(
            request=request_payload,
            requests=requests,
            env=env,
        )
        return _tool_ok(
            "性能测试完成。",
            data={
                "collectionId": collection_id,
                "projectId": request_payload.projectId,
                "environmentId": request_payload.environmentId,
                "requestCount": result.totalRequests,
                "successCount": result.successCount,
                "failCount": result.failCount,
                "tps": result.tps,
                "avgLatencyMs": result.avgLatencyMs,
                "p95LatencyMs": result.p95LatencyMs,
                "passedSla": result.passedSla,
                "errorMsg": result.errorMsg,
            },
        )

    elif tool_name == "run_security_test":
        if not api_testing or not security_testing:
            return _tool_error("安全测试引擎不可用：当前 AI 服务未挂载 security_testing。", "ENGINE_UNAVAILABLE")
        collection_id = str(args.get("collection_id") or "").strip()
        target_url = str(args.get("target_url") or "").strip()
        if not collection_id and not target_url:
            return _tool_error("安全测试失败：collection_id 与 target_url 至少传一个。", "INVALID_ARGUMENT")
        from app.models import ApiEnvironmentPublic, ApiRequestPublic, SecurityScanRequest

        collection = None
        normalized_target_url: str | None = None
        requests: list[ApiRequestPublic] = []
        request_ids = [str(item).strip() for item in (args.get("request_ids") or []) if str(item).strip()]
        env = None

        if target_url:
            try:
                normalized_target_url = security_testing.normalize_target_url(target_url)
                requests = await security_testing.build_requests_from_target_url(
                    normalized_target_url,
                    max_discovered_urls=max(1, min(int(args.get("max_discovered_urls") or 8), 30)),
                )
            except Exception as exc:
                return _tool_error(f"安全测试失败：target_url 无效或不可访问（{exc}）。", "INVALID_ARGUMENT")
            if not requests:
                return _tool_error("安全测试失败：目标网址未发现可扫描 URL。", "EMPTY_SCOPE")
        else:
            collection = api_testing.get_collection(collection_id)
            if not collection:
                return _tool_error(f"安全测试失败：集合 {collection_id} 不存在。", "NOT_FOUND")
            requests_raw = api_testing.list_requests(collection_id)
            requests = [ApiRequestPublic.model_validate(r) for r in requests_raw if not bool(r.get("isFolder"))]
            if request_ids:
                selected = set(request_ids)
                requests = [item for item in requests if item.id in selected]
            if not requests:
                return _tool_error(f"安全测试失败：集合 {collection_id} 中没有可执行接口。", "EMPTY_SCOPE")

            environment_id = str(args.get("environment_id") or "").strip()
            if environment_id:
                env_raw = api_testing.get_environment(environment_id)
                if not env_raw:
                    return _tool_error(f"安全测试失败：环境 {environment_id} 不存在。", "NOT_FOUND")
                env = ApiEnvironmentPublic.model_validate(env_raw)

        scan_types = args.get("scan_types")
        if not isinstance(scan_types, list) or not scan_types:
            scan_types = [
                "owasp_api",
                "pii_scan",
                "auth_bypass",
                "security_headers",
                "cors_misconfig",
                "xss_reflection",
                "error_leak",
                "insecure_transport",
                "idor_enumeration",
                "path_traversal",
                "ssrf_probe",
                "file_upload_security",
                "command_template_injection",
                "jwt_session_security",
                "rate_limit_bruteforce",
            ]
        result = await security_testing.run_security_scan(
            request=SecurityScanRequest(
                projectId=str(args.get("project_id") or (collection.get("projectId") if collection else "") or "default_project"),
                collectionIds=[collection_id] if collection_id else [],
                targetUrl=normalized_target_url,
                maxDiscoveredUrls=max(1, min(int(args.get("max_discovered_urls") or 8), 30)),
                scanTypes=[str(item) for item in scan_types],
            ),
            collection_requests=requests,
            env=env,
        )
        top_issue = result.vulnerabilities[0] if result.vulnerabilities else None
        return _tool_ok(
            "安全扫描完成。",
            data={
                "collectionId": collection_id,
                "targetUrl": normalized_target_url,
                "projectId": str(args.get("project_id") or (collection.get("projectId") if collection else "") or "default_project"),
                "scannedRequestCount": len(requests),
                "issueCount": result.totalIssues,
                "criticalCount": result.criticalCount,
                "highCount": result.highCount,
                "mediumCount": result.mediumCount,
                "lowCount": result.lowCount,
                "topIssue": (
                    {"type": top_issue.type, "endpoint": top_issue.endpoint}
                    if top_issue
                    else None
                ),
            },
        )

    elif tool_name == "get_latest_failed_log":
        req_id = args.get("request_id")
        if not req_id: return "缺少 request_id"
        
        row = db.fetchone(
            """
            SELECT *
            FROM api_request_runs
            WHERE request_id = ? AND success = 0
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (req_id,),
        )
        if not row:
            return f"接口 {req_id} 暂时没有失败记录。"
        payload = {
            "error": row.get("error_message"),
            "statusCode": row.get("status_code"),
            "meta": row.get("meta_json"),
        }
        return (
            f"接口 {req_id} 最近一次失败信息 (执行时间: {row['created_at']})：\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            "提示：请分析原因并修复它。"
        )

    elif tool_name == "summarize_run_failures":
        limit_raw = args.get("limit", 20)
        try:
            limit = max(1, min(int(limit_raw), 100))
        except Exception:
            limit = 20
        collection_id = str(args.get("collection_id") or "").strip()
        request_id = str(args.get("request_id") or "").strip()

        where = ["success = 0"]
        params: list[Any] = []
        if collection_id:
            where.append("collection_id = ?")
            params.append(collection_id)
        if request_id:
            where.append("request_id = ?")
            params.append(request_id)
        params.append(limit)

        rows = db.fetchall(
            f"""
            SELECT id, request_id, collection_id, method, url, status_code, duration_ms, error_message, created_at
            FROM api_request_runs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        if not rows:
            scope_text = f"集合 {collection_id}" if collection_id else (f"接口 {request_id}" if request_id else "当前范围")
            return f"{scope_text} 最近没有失败记录。"

        def _bucket(row: dict[str, Any]) -> str:
            status = row.get("status_code")
            error = str(row.get("error_message") or "").lower()
            if status == 401 or "token" in error or "unauthorized" in error:
                return "认证/鉴权失败"
            if status == 403:
                return "权限不足/越权"
            if status == 404:
                return "接口地址或路由不存在"
            if status == 429:
                return "限流/防刷触发"
            if status and int(status) >= 500:
                return "服务端异常(5xx)"
            if "timeout" in error or "timed out" in error:
                return "超时/网络抖动"
            if "ssl" in error or "certificate" in error:
                return "TLS/证书问题"
            if status == 400:
                return "请求参数不合法(400)"
            return "其他失败"

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = _bucket(row)
            grouped.setdefault(key, []).append(row)

        sorted_groups = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)
        lines = [
            f"最近失败记录共 {len(rows)} 条（分析样本上限 {limit}）。",
            "失败聚类 Top：",
        ]
        for idx, (label, items) in enumerate(sorted_groups[:5], start=1):
            sample = items[0]
            lines.append(
                f"{idx}. {label}：{len(items)} 条，示例 {sample.get('method')} {sample.get('url')} "
                f"(status={sample.get('status_code')}, at={sample.get('created_at')})"
            )

        suggestions: list[str] = []
        top_label = sorted_groups[0][0]
        if top_label == "认证/鉴权失败":
            suggestions.extend([
                "检查环境中的 token/key 是否过期，确认登录与刷新策略。",
                "为关键接口增加 401/403 断言与重试前置登录脚本。",
            ])
        elif top_label == "请求参数不合法(400)":
            suggestions.extend([
                "对请求体做 schema 校验并补充边界值用例。",
                "检查必填参数、字段类型与业务枚举取值。",
            ])
        elif top_label == "服务端异常(5xx)":
            suggestions.extend([
                "优先拉取后端日志并定位异常栈，补充熔断与重试策略。",
                "将高频失败接口纳入稳定性回归集。",
            ])
        elif top_label == "超时/网络抖动":
            suggestions.extend([
                "提高单请求超时并添加可配置重试机制（幂等接口）。",
                "区分网络层失败与业务失败，避免误报。",
            ])
        else:
            suggestions.append("优先查看最近失败接口日志，按状态码分组逐项修复。")

        lines.append("建议动作：")
        for idx, item in enumerate(suggestions, start=1):
            lines.append(f"- {idx}) {item}")

        # Action-card protocol for frontend parser.
        action_cards: list[dict[str, str]] = []
        target_req = request_id or str(rows[0].get("request_id") or "")
        if target_req:
            action_cards.append({
                "label": "查看最近失败日志",
                "command": f"请调用 get_latest_failed_log 工具，request_id={target_req}",
            })
            action_cards.append({
                "label": "重跑该接口",
                "command": f"请调用 execute_api_test_case 工具，request_id={target_req}",
            })
        if collection_id:
            action_cards.append({
                "label": "跑一轮安全扫描",
                "command": f"请调用 run_security_test 工具，collection_id={collection_id}",
            })
        lines.append("```actions")
        lines.append(json.dumps(action_cards, ensure_ascii=False))
        lines.append("```")
        return "\n".join(lines)

    elif tool_name == "recommend_regression_scope":
        project_id = str(args.get("project_id") or "").strip()
        collection_id = str(args.get("collection_id") or "").strip()
        changed_within_days_raw = args.get("changed_within_days")
        changed_within_days: int | None = None
        if changed_within_days_raw is not None:
            try:
                changed_within_days = max(1, min(int(changed_within_days_raw), 365))
            except Exception:
                changed_within_days = None
        limit_raw = args.get("limit", 10)
        try:
            limit = max(1, min(int(limit_raw), 50))
        except Exception:
            limit = 10

        where = ["r.deleted_at IS NULL", "c.deleted_at IS NULL"]
        params: list[Any] = []
        if project_id:
            where.append("c.project_id = ?")
            params.append(project_id)
        if collection_id:
            where.append("r.collection_id = ?")
            params.append(collection_id)
        cutoff_text = None
        if changed_within_days:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=changed_within_days)
            cutoff_text = cutoff_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            where.append("r.updated_at >= ?")
            params.append(cutoff_text)
        params.append(limit * 4)

        rows = db.fetchall(
            f"""
            SELECT
              r.id,
              r.name,
              r.method,
              r.url,
              r.collection_id,
              r.updated_at,
              (
                SELECT COUNT(*)
                FROM api_request_runs rr
                WHERE rr.request_id = r.id
                  AND rr.success = 0
              ) AS fail_count,
              (
                SELECT COUNT(*)
                FROM api_request_runs rr
                WHERE rr.request_id = r.id
              ) AS total_runs,
              (
                SELECT MAX(rr.created_at)
                FROM api_request_runs rr
                WHERE rr.request_id = r.id
              ) AS last_run_at
            FROM api_requests r
            JOIN api_collections c ON c.id = r.collection_id
            WHERE {' AND '.join(where)}
            ORDER BY fail_count DESC, r.updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        if not rows:
            scope = f"项目 {project_id}" if project_id else "当前范围"
            return f"{scope} 没有可推荐的接口。"

        def score(item: dict[str, Any]) -> float:
            fail = float(item.get("fail_count") or 0)
            total = float(item.get("total_runs") or 0)
            no_run_bonus = 1.5 if total == 0 else 0.0
            unstable = (fail / total) if total > 0 else 0.0
            return fail * 2.0 + unstable * 3.0 + no_run_bonus

        ranked = sorted(rows, key=score, reverse=True)[:limit]
        rec_ids = [str(item.get("id") or "") for item in ranked if str(item.get("id") or "")]
        lines = [
            f"推荐最小回归范围（共 {len(rec_ids)} 条）：",
        ]
        if cutoff_text:
            lines.append(f"筛选条件：仅包含最近 {changed_within_days} 天更新的接口（updated_at >= {cutoff_text}）。")
        for idx, item in enumerate(ranked, start=1):
            fail = int(item.get("fail_count") or 0)
            total = int(item.get("total_runs") or 0)
            reason_parts = []
            if fail > 0:
                reason_parts.append(f"历史失败 {fail} 次")
            if total == 0:
                reason_parts.append("从未执行")
            if not reason_parts:
                reason_parts.append("近期有更新")
            lines.append(
                f"{idx}. [{item.get('id')}] {item.get('method')} {item.get('url')} - "
                f"{'，'.join(reason_parts)}"
            )
        lines.append("建议：先执行这些接口，再按失败结果扩展到关联上下游接口。")
        lines.append("推荐 request_ids:")
        lines.append(", ".join(rec_ids))

        action_cards: list[dict[str, str]] = []
        if rec_ids:
            action_cards.append({
                "label": "批量执行推荐回归集",
                "command": f"请对以下 request_ids 执行回归：{', '.join(rec_ids)}",
            })
        if collection_id:
            action_cards.append({
                "label": "对该集合跑安全扫描",
                "command": f"请调用 run_security_test 工具，collection_id={collection_id}",
            })
        lines.append("```actions")
        lines.append(json.dumps(action_cards, ensure_ascii=False))
        lines.append("```")
        return "\n".join(lines)

    elif tool_name == "analyze_test_gap":
        project_id = str(args.get("project_id") or "").strip()
        requirement_id = str(args.get("requirement_id") or "").strip()
        limit_raw = args.get("limit", 10)
        try:
            limit = max(1, min(int(limit_raw), 50))
        except Exception:
            limit = 10

        req_where = ["deleted_at IS NULL"]
        req_params: list[Any] = []
        if project_id:
            req_where.append("project_id = ?")
            req_params.append(project_id)
        if requirement_id:
            req_where.append("id = ?")
            req_params.append(requirement_id)

        requirements = db.fetchall(
            f"""
            SELECT id, project_id, title, status, updated_at
            FROM requirements
            WHERE {' AND '.join(req_where)}
            ORDER BY updated_at DESC
            LIMIT 500
            """,
            tuple(req_params),
        )
        if not requirements:
            scope = f"项目 {project_id}" if project_id else "当前范围"
            return f"{scope} 没有可分析的需求记录。"

        req_ids = [str(row.get("id") or "") for row in requirements if str(row.get("id") or "")]
        if not req_ids:
            return "需求记录无有效 ID，无法分析覆盖缺口。"

        placeholders = ",".join(["?"] * len(req_ids))
        case_rows = db.fetchall(
            f"""
            SELECT requirement_id, kind, status
            FROM cases
            WHERE deleted_at IS NULL AND requirement_id IN ({placeholders})
            """,
            tuple(req_ids),
        )

        coverage_map: dict[str, dict[str, Any]] = {
            rid: {"total": 0, "kinds": set(), "active": 0}
            for rid in req_ids
        }
        for row in case_rows:
            rid = str(row.get("requirement_id") or "")
            if rid not in coverage_map:
                continue
            coverage_map[rid]["total"] += 1
            kind = str(row.get("kind") or "").strip().lower()
            if kind:
                coverage_map[rid]["kinds"].add(kind)
            status = str(row.get("status") or "").strip().lower()
            if status in {"ready", "active", "passed", "approved"}:
                coverage_map[rid]["active"] += 1

        uncovered: list[dict[str, Any]] = []
        weak: list[dict[str, Any]] = []
        for req in requirements:
            rid = str(req.get("id") or "")
            title = str(req.get("title") or rid)
            c = coverage_map.get(rid, {"total": 0, "kinds": set(), "active": 0})
            total = int(c["total"])
            kinds = set(c["kinds"])
            if total == 0:
                uncovered.append({"id": rid, "title": title, "reason": "无任何关联用例"})
                continue
            gaps: list[str] = []
            if "api" not in kinds:
                gaps.append("缺 API 用例")
            if "security" not in kinds:
                gaps.append("缺安全用例")
            if "performance" not in kinds:
                gaps.append("缺性能用例")
            if total < 2:
                gaps.append("用例数量偏少")
            if gaps:
                weak.append({"id": rid, "title": title, "reason": "、".join(gaps), "total": total})

        lines = [
            f"需求总数: {len(requirements)}",
            f"无覆盖需求: {len(uncovered)}",
            f"覆盖偏弱需求: {len(weak)}",
        ]
        if uncovered:
            lines.append("未覆盖需求 Top：")
            for idx, item in enumerate(uncovered[:limit], start=1):
                lines.append(f"{idx}. [{item['id']}] {item['title']}（{item['reason']}）")
        if weak:
            lines.append("覆盖偏弱需求 Top：")
            for idx, item in enumerate(weak[:limit], start=1):
                lines.append(f"{idx}. [{item['id']}] {item['title']}（{item['reason']}，当前 {item['total']} 条）")

        action_cards: list[dict[str, str]] = []
        target_req = uncovered[0]["id"] if uncovered else (weak[0]["id"] if weak else "")
        if target_req:
            action_cards.append({
                "label": "为首个缺口需求生成用例",
                "command": f"请为需求 {target_req} 生成一组 API + 安全 + 性能测试用例草案，并给出可执行字段。",
            })
        if project_id:
            action_cards.append({
                "label": "生成项目级补齐计划",
                "command": f"请基于项目 {project_id} 的覆盖缺口，输出按优先级排序的补齐计划（本周可落地）。",
            })
        if weak:
            action_cards.append({
                "label": "补齐安全与性能覆盖",
                "command": "请针对覆盖偏弱需求补齐安全和性能场景，并标注每条用例的风险收益。",
            })

        result_payload = {
            "scope": {
                "projectId": project_id or None,
                "requirementId": requirement_id or None,
                "limit": limit,
            },
            "summary": {
                "requirementCount": len(requirements),
                "uncoveredCount": len(uncovered),
                "weakCoverageCount": len(weak),
            },
            "uncoveredTop": uncovered[:limit],
            "weakCoverageTop": weak[:limit],
        }
        operation_id = new_id("aiop")
        try:
            db.execute(
                """
                INSERT INTO ai_operations (
                  id, operation_type, target_type, target_id, status,
                  request_payload, response_payload, error_message, created_by,
                  attempt_count, created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    "analyze_test_gap",
                    "project" if project_id else ("requirement" if requirement_id else "scope"),
                    project_id or requirement_id or "global",
                    "succeeded",
                    json.dumps(args, ensure_ascii=False),
                    json.dumps(result_payload, ensure_ascii=False),
                    None,
                    "ai-agent",
                    1,
                    utc_now(),
                    utc_now(),
                    utc_now(),
                    utc_now(),
                ),
            )
            lines.append(f"分析结果已入库，operation_id={operation_id}")
        except Exception:
            lines.append("分析结果入库失败（仅影响追踪，不影响本次输出）。")

        lines.append("```json")
        lines.append(json.dumps(result_payload, ensure_ascii=False))
        lines.append("```")
        lines.append("```actions")
        lines.append(json.dumps(action_cards, ensure_ascii=False))
        lines.append("```")
        return "\n".join(lines)

    elif tool_name == "list_projects":
        q = str(args.get("q") or "").strip()
        limit_raw = args.get("limit", 20)
        try:
            limit = max(1, min(int(limit_raw), 100))
        except Exception:
            limit = 20
        where = ["deleted_at IS NULL"]
        params: list[Any] = []
        org_placeholders = ",".join(["?"] * len(actor_org_ids))
        where.append(f"org_id IN ({org_placeholders})")
        params.extend(list(actor_org_ids))
        if q:
            where.append("(name LIKE ? OR description LIKE ?)")
            fuzzy = f"%{q}%"
            params.extend([fuzzy, fuzzy])
        params.append(limit)
        rows = db.fetchall(
            f"""
            SELECT id, org_id, name, description, created_at, updated_at
            FROM projects
            WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return _tool_ok("项目列表查询完成。", data={"total": len(rows), "items": rows})

    elif tool_name == "create_project_record":
        name = str(args.get("name") or "").strip()
        if not name:
            return _tool_error("创建项目失败：name 不能为空。", "INVALID_ARGUMENT")
        org_id = str(args.get("org_id") or "DEFAULT_ORG").strip() or "DEFAULT_ORG"
        denied = _assert_org_access(org_id)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        description = str(args.get("description") or "").strip()
        created_by = str(args.get("created_by") or "ai-agent").strip() or "ai-agent"
        exists = db.fetchone(
            "SELECT id FROM projects WHERE org_id = ? AND lower(name) = lower(?) AND deleted_at IS NULL",
            (org_id, name),
        )
        if exists:
            return _tool_error(
                f"创建项目失败：同组织下已存在同名项目（id={exists.get('id')}）。",
                "CONFLICT",
            )
        project_id = new_id("proj")
        now = utc_now()
        db.execute(
            """
            INSERT INTO projects (id, org_id, name, description, created_by, deleted_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (project_id, org_id, name, description, created_by, now, now),
        )
        return _tool_ok("项目创建成功。", data={"id": project_id, "name": name, "orgId": org_id})

    elif tool_name == "update_project_record":
        project_id = str(args.get("project_id") or "").strip()
        if not project_id:
            return _tool_error("更新项目失败：缺少 project_id。", "INVALID_ARGUMENT")
        org_id = _project_org(project_id)
        if not org_id:
            return _tool_error(f"更新项目失败：项目 {project_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(org_id)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        current = db.fetchone(
            "SELECT id, name, description FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        )
        if not current:
            return _tool_error(f"更新项目失败：项目 {project_id} 不存在。", "NOT_FOUND")
        set_clauses: list[str] = []
        values: list[Any] = []
        if args.get("name") is not None:
            name = str(args.get("name") or "").strip()
            if not name:
                return _tool_error("更新项目失败：name 不能为空字符串。", "INVALID_ARGUMENT")
            set_clauses.append("name = ?")
            values.append(name)
        if args.get("description") is not None:
            set_clauses.append("description = ?")
            values.append(str(args.get("description") or "").strip())
        if not set_clauses:
            return _tool_error("更新项目失败：未提供可更新字段。", "INVALID_ARGUMENT")
        set_clauses.append("updated_at = ?")
        values.append(utc_now())
        values.append(project_id)
        db.execute(f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = ?", tuple(values))
        row = db.fetchone("SELECT id, name, description, updated_at FROM projects WHERE id = ?", (project_id,))
        return _tool_ok("项目更新成功。", data={"item": row})

    elif tool_name == "delete_project_record":
        project_id = str(args.get("project_id") or "").strip()
        if not project_id:
            return _tool_error("删除项目失败：缺少 project_id。", "INVALID_ARGUMENT")
        org_id = _project_org(project_id)
        if not org_id:
            return _tool_error(f"删除项目失败：项目 {project_id} 不存在或已删除。", "NOT_FOUND")
        denied = _assert_org_access(org_id)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        row = db.fetchone("SELECT id, name FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,))
        if not row:
            return _tool_error(f"删除项目失败：项目 {project_id} 不存在或已删除。", "NOT_FOUND")
        db.execute("UPDATE projects SET deleted_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), project_id))
        return _tool_ok("项目删除成功（软删除）。", data={"id": project_id, "name": row.get("name")})

    elif tool_name == "list_requirements_records":
        project_id = str(args.get("project_id") or "").strip()
        q = str(args.get("q") or "").strip()
        status = str(args.get("status") or "").strip()
        limit_raw = args.get("limit", 20)
        try:
            limit = max(1, min(int(limit_raw), 100))
        except Exception:
            limit = 20
        where = ["deleted_at IS NULL"]
        params: list[Any] = []
        org_placeholders = ",".join(["?"] * len(actor_org_ids))
        where.append(f"org_id IN ({org_placeholders})")
        params.extend(list(actor_org_ids))
        if project_id:
            proj_org = _project_org(project_id)
            if not proj_org:
                return _tool_error(f"项目 {project_id} 不存在。", "NOT_FOUND")
            denied = _assert_org_access(proj_org)
            if denied:
                return _tool_error(denied, "FORBIDDEN")
            where.append("project_id = ?")
            params.append(project_id)
        if q:
            where.append("(title LIKE ? OR content LIKE ?)")
            fuzzy = f"%{q}%"
            params.extend([fuzzy, fuzzy])
        if status:
            where.append("status = ?")
            params.append(status)
        params.append(limit)
        rows = db.fetchall(
            f"""
            SELECT id, project_id, title, status, updated_at
            FROM requirements
            WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return _tool_ok("需求列表查询完成。", data={"total": len(rows), "items": rows})

    elif tool_name == "create_requirement_record":
        project_id = str(args.get("project_id") or "").strip()
        title = str(args.get("title") or "").strip()
        content = str(args.get("content") or "").strip()
        if not project_id or not title or not content:
            return _tool_error("创建需求失败：project_id、title、content 都是必填。", "INVALID_ARGUMENT")
        org_id = str(args.get("org_id") or "DEFAULT_ORG").strip() or "DEFAULT_ORG"
        denied = _assert_org_access(org_id)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        proj_org = _project_org(project_id)
        if not proj_org:
            return _tool_error(f"创建需求失败：项目 {project_id} 不存在。", "NOT_FOUND")
        if proj_org != org_id:
            return _tool_error("创建需求失败：project_id 与 org_id 不匹配。", "INVALID_ARGUMENT")
        created_by = str(args.get("created_by") or "ai-agent").strip() or "ai-agent"
        tags_raw = args.get("tags") or []
        tags = [str(item).strip() for item in tags_raw if str(item).strip()] if isinstance(tags_raw, list) else []

        dup = db.fetchone(
            """
            SELECT id
            FROM requirements
            WHERE project_id = ? AND deleted_at IS NULL
              AND lower(title) = lower(?)
              AND lower(content) = lower(?)
            """,
            (project_id, title, content),
        )
        if dup:
            return _tool_error(f"创建需求失败：检测到重复需求（id={dup.get('id')}）。", "CONFLICT")

        req_id = new_id("req")
        now = utc_now()
        db.execute(
            """
            INSERT INTO requirements (
              id, org_id, project_id, source_spec_id, title, content, tags_json, status,
              latest_analysis_version, version, created_by, deleted_at, created_at, updated_at
            ) VALUES (?, ?, ?, NULL, ?, ?, ?, 'draft', NULL, 1, ?, NULL, ?, ?)
            """,
            (req_id, org_id, project_id, title, content, json.dumps(tags, ensure_ascii=False), created_by, now, now),
        )
        return _tool_ok("需求创建成功。", data={"id": req_id, "title": title, "projectId": project_id})

    elif tool_name == "update_requirement_record":
        requirement_id = str(args.get("requirement_id") or "").strip()
        if not requirement_id:
            return _tool_error("更新需求失败：缺少 requirement_id。", "INVALID_ARGUMENT")
        req_org = _requirement_org(requirement_id)
        if not req_org:
            return _tool_error(f"更新需求失败：需求 {requirement_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(req_org)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        exists = db.fetchone(
            "SELECT id, title FROM requirements WHERE id = ? AND deleted_at IS NULL",
            (requirement_id,),
        )
        if not exists:
            return _tool_error(f"更新需求失败：需求 {requirement_id} 不存在。", "NOT_FOUND")
        set_clauses: list[str] = []
        values: list[Any] = []
        if args.get("title") is not None:
            title = str(args.get("title") or "").strip()
            if not title:
                return _tool_error("更新需求失败：title 不能为空字符串。", "INVALID_ARGUMENT")
            set_clauses.append("title = ?")
            values.append(title)
        if args.get("content") is not None:
            content = str(args.get("content") or "").strip()
            if not content:
                return _tool_error("更新需求失败：content 不能为空字符串。", "INVALID_ARGUMENT")
            set_clauses.append("content = ?")
            values.append(content)
        if args.get("status") is not None:
            status_val = str(args.get("status") or "").strip()
            if not status_val:
                return _tool_error("更新需求失败：status 不能为空字符串。", "INVALID_ARGUMENT")
            set_clauses.append("status = ?")
            values.append(status_val)
        if args.get("tags") is not None:
            tags_raw = args.get("tags") or []
            tags = [str(item).strip() for item in tags_raw if str(item).strip()] if isinstance(tags_raw, list) else []
            set_clauses.append("tags_json = ?")
            values.append(json.dumps(tags, ensure_ascii=False))
        if not set_clauses:
            return _tool_error("更新需求失败：未提供可更新字段。", "INVALID_ARGUMENT")
        set_clauses.append("version = version + 1")
        set_clauses.append("updated_at = ?")
        values.append(utc_now())
        values.append(requirement_id)
        db.execute(f"UPDATE requirements SET {', '.join(set_clauses)} WHERE id = ?", tuple(values))
        row = db.fetchone(
            "SELECT id, title, status, updated_at FROM requirements WHERE id = ?",
            (requirement_id,),
        )
        return _tool_ok("需求更新成功。", data={"item": row})

    elif tool_name == "delete_requirement_record":
        requirement_id = str(args.get("requirement_id") or "").strip()
        if not requirement_id:
            return _tool_error("删除需求失败：缺少 requirement_id。", "INVALID_ARGUMENT")
        req_org = _requirement_org(requirement_id)
        if not req_org:
            return _tool_error(f"删除需求失败：需求 {requirement_id} 不存在或已删除。", "NOT_FOUND")
        denied = _assert_org_access(req_org)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        exists = db.fetchone(
            "SELECT id, title FROM requirements WHERE id = ? AND deleted_at IS NULL",
            (requirement_id,),
        )
        if not exists:
            return _tool_error(f"删除需求失败：需求 {requirement_id} 不存在或已删除。", "NOT_FOUND")
        db.execute(
            "UPDATE requirements SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), requirement_id),
        )
        return _tool_ok("需求删除成功（软删除）。", data={"id": requirement_id, "title": exists.get("title")})

    elif tool_name == "list_test_cases_records":
        project_id = str(args.get("project_id") or "").strip()
        kind = str(args.get("kind") or "").strip()
        status = str(args.get("status") or "").strip()
        q = str(args.get("q") or "").strip()
        limit_raw = args.get("limit", 20)
        try:
            limit = max(1, min(int(limit_raw), 100))
        except Exception:
            limit = 20
        where = ["deleted_at IS NULL"]
        params: list[Any] = []
        org_placeholders = ",".join(["?"] * len(actor_org_ids))
        where.append(f"org_id IN ({org_placeholders})")
        params.extend(list(actor_org_ids))
        if project_id:
            proj_org = _project_org(project_id)
            if not proj_org:
                return _tool_error(f"项目 {project_id} 不存在。", "NOT_FOUND")
            denied = _assert_org_access(proj_org)
            if denied:
                return _tool_error(denied, "FORBIDDEN")
            where.append("project_id = ?")
            params.append(project_id)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if status:
            where.append("status = ?")
            params.append(status)
        if q:
            where.append("title LIKE ?")
            params.append(f"%{q}%")
        params.append(limit)
        rows = db.fetchall(
            f"""
            SELECT id, project_id, spec_id, requirement_id, title, kind, status, priority, updated_at
            FROM cases
            WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return _tool_ok("测试用例列表查询完成。", data={"total": len(rows), "items": rows})

    elif tool_name == "create_test_case_record":
        project_id = str(args.get("project_id") or "").strip()
        title = str(args.get("title") or "").strip()
        if not project_id or not title:
            return _tool_error("创建用例失败：project_id 和 title 必填。", "INVALID_ARGUMENT")
        org_id = str(args.get("org_id") or "DEFAULT_ORG").strip() or "DEFAULT_ORG"
        denied = _assert_org_access(org_id)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        proj_org = _project_org(project_id)
        if not proj_org:
            return _tool_error(f"创建用例失败：项目 {project_id} 不存在。", "NOT_FOUND")
        if proj_org != org_id:
            return _tool_error("创建用例失败：project_id 与 org_id 不匹配。", "INVALID_ARGUMENT")
        kind = str(args.get("kind") or "manual").strip() or "manual"
        objective = str(args.get("objective") or "").strip()
        spec_id_input = str(args.get("spec_id") or "").strip()
        requirement_input = str(args.get("requirement_id") or "").strip()
        spec_id = spec_id_input or requirement_input or None
        requirement_id = spec_id
        priority = str(args.get("priority") or "P2").strip() or "P2"
        status_val = str(args.get("status") or "draft").strip() or "draft"
        created_by = str(args.get("created_by") or "ai-agent").strip() or "ai-agent"
        steps_raw = args.get("steps") or []
        steps = [str(item) for item in steps_raw] if isinstance(steps_raw, list) else []
        assertion_raw = args.get("assertion_hints") or []
        assertion_hints = [str(item) for item in assertion_raw] if isinstance(assertion_raw, list) else []
        payload_obj = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        if spec_id:
            req_row = db.fetchone(
                "SELECT id, org_id, project_id FROM requirements WHERE id = ? AND deleted_at IS NULL",
                (spec_id,),
            )
            if not req_row:
                return _tool_error(f"创建用例失败：需求 {spec_id} 不存在。", "NOT_FOUND")
            req_org = str(req_row.get("org_id") or "").strip()
            if req_org and req_org != org_id:
                return _tool_error("创建用例失败：spec_id 与 org_id 不匹配。", "INVALID_ARGUMENT")
            req_project = str(req_row.get("project_id") or "").strip()
            if req_project and req_project != project_id:
                return _tool_error("创建用例失败：spec_id 与 project_id 不匹配。", "INVALID_ARGUMENT")

        case_id = new_id("case")
        now = utc_now()
        db.execute(
            """
            INSERT INTO cases (
              id, org_id, project_id, spec_id, requirement_id, title, objective, preconditions,
              steps_json, assertion_hints_json, payload_json, tags_json, priority, status, kind,
              version, created_by, deleted_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, '[]', ?, ?, ?, 1, ?, NULL, ?, ?)
            """,
            (
                case_id,
                org_id,
                project_id,
                spec_id,
                requirement_id,
                title,
                objective,
                json.dumps(steps, ensure_ascii=False),
                json.dumps(assertion_hints, ensure_ascii=False),
                json.dumps(payload_obj, ensure_ascii=False),
                priority,
                status_val,
                kind,
                created_by,
                now,
                now,
            ),
        )
        response_data: dict[str, Any] = {
            "id": case_id,
            "title": title,
            "projectId": project_id,
            "specId": spec_id,
            "requirementId": requirement_id,
        }
        response_actions: list[dict[str, str]] = []
        auto_api_url = str(args.get("api_url") or args.get("url") or "").strip()
        if kind.lower() == "api":
            if auto_api_url:
                create_step_raw = await execute_tool_call(
                    "create_api_test_case",
                    json.dumps(
                        {
                            "case_id": case_id,
                            "project_id": project_id,
                            "collection_id": str(args.get("collection_id") or "").strip() or None,
                            "name": str(args.get("api_name") or title).strip() or title,
                            "method": str(args.get("api_method") or "GET").strip().upper(),
                            "url": auto_api_url,
                            "headers": args.get("api_headers") if isinstance(args.get("api_headers"), list) else [],
                            "query": args.get("api_query") if isinstance(args.get("api_query"), list) else [],
                            "body_mode": str(args.get("api_body_mode") or "none").strip(),
                            "body_raw": str(args.get("api_body_raw") or ""),
                            "test_script": str(args.get("api_test_script") or ""),
                        },
                        ensure_ascii=False,
                    ),
                    db,
                    actor_id=actor_id,
                    api_testing=api_testing,
                    performance_testing=performance_testing,
                    security_testing=security_testing,
                    smithery=smithery,
                )
                try:
                    step_payload = json.loads(create_step_raw)
                except Exception:
                    step_payload = {"ok": False, "message": str(create_step_raw or "")}
                response_data["apiStep"] = step_payload
                if not bool(step_payload.get("ok")):
                    response_actions.append(
                        {
                            "label": "手动补充接口步骤",
                            "command": f"请调用 create_api_test_case 工具，case_id={case_id}, project_id={project_id}, url=<接口地址>, method=GET",
                        }
                    )
            else:
                response_actions.append(
                    {
                        "label": "为该 API 用例添加接口步骤",
                        "command": f"请调用 create_api_test_case 工具，case_id={case_id}, project_id={project_id}, url=<接口地址>, method=GET",
                    }
                )
        return _tool_ok("测试用例创建成功。", data=response_data, actions=response_actions or None)

    elif tool_name == "update_test_case_record":
        case_id = str(args.get("case_id") or "").strip()
        if not case_id:
            return _tool_error("更新用例失败：缺少 case_id。", "INVALID_ARGUMENT")
        case_org = _case_org(case_id)
        if not case_org:
            return _tool_error(f"更新用例失败：用例 {case_id} 不存在。", "NOT_FOUND")
        denied = _assert_org_access(case_org)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        exists = db.fetchone(
            "SELECT id, title FROM cases WHERE id = ? AND deleted_at IS NULL",
            (case_id,),
        )
        if not exists:
            return _tool_error(f"更新用例失败：用例 {case_id} 不存在。", "NOT_FOUND")
        set_clauses: list[str] = []
        values: list[Any] = []
        simple_fields = {
            "title": "title",
            "kind": "kind",
            "objective": "objective",
            "priority": "priority",
            "status": "status",
        }
        for key, col in simple_fields.items():
            if args.get(key) is not None:
                set_clauses.append(f"{col} = ?")
                values.append(str(args.get(key) or "").strip())
        if args.get("steps") is not None:
            steps_raw = args.get("steps") or []
            steps = [str(item) for item in steps_raw] if isinstance(steps_raw, list) else []
            set_clauses.append("steps_json = ?")
            values.append(json.dumps(steps, ensure_ascii=False))
        if args.get("assertion_hints") is not None:
            hints_raw = args.get("assertion_hints") or []
            hints = [str(item) for item in hints_raw] if isinstance(hints_raw, list) else []
            set_clauses.append("assertion_hints_json = ?")
            values.append(json.dumps(hints, ensure_ascii=False))
        if args.get("payload") is not None:
            payload_obj = args.get("payload") if isinstance(args.get("payload"), dict) else {}
            set_clauses.append("payload_json = ?")
            values.append(json.dumps(payload_obj, ensure_ascii=False))
        if not set_clauses:
            return _tool_error("更新用例失败：未提供可更新字段。", "INVALID_ARGUMENT")
        set_clauses.append("version = version + 1")
        set_clauses.append("updated_at = ?")
        values.append(utc_now())
        values.append(case_id)
        db.execute(f"UPDATE cases SET {', '.join(set_clauses)} WHERE id = ?", tuple(values))
        row = db.fetchone(
            "SELECT id, title, kind, status, updated_at FROM cases WHERE id = ?",
            (case_id,),
        )
        return _tool_ok("测试用例更新成功。", data={"item": row})

    elif tool_name == "delete_test_case_record":
        case_id = str(args.get("case_id") or "").strip()
        if not case_id:
            return _tool_error("删除用例失败：缺少 case_id。", "INVALID_ARGUMENT")
        case_org = _case_org(case_id)
        if not case_org:
            return _tool_error(f"删除用例失败：用例 {case_id} 不存在或已删除。", "NOT_FOUND")
        denied = _assert_org_access(case_org)
        if denied:
            return _tool_error(denied, "FORBIDDEN")
        exists = db.fetchone("SELECT id, title FROM cases WHERE id = ? AND deleted_at IS NULL", (case_id,))
        if not exists:
            return _tool_error(f"删除用例失败：用例 {case_id} 不存在或已删除。", "NOT_FOUND")
        db.execute("UPDATE cases SET deleted_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), case_id))
        return _tool_ok("测试用例删除成功（软删除）。", data={"id": case_id, "title": exists.get("title")})

    elif tool_name == "explain_security_perf_config":
        collection_id = str(args.get("collection_id") or "").strip()
        goal = str(args.get("goal") or "baseline").strip() or "baseline"
        lines = [
            "安全/性能测试配置建议如下：",
            f"- 目标模式: {goal}",
            "",
            "安全测试（run_security_test）建议：",
            "- `scan_types` 默认全开，最小集可用：owasp_api, auth_bypass, security_headers, jwt_session_security, rate_limit_bruteforce",
            "- 文件上传场景加：file_upload_security",
            "- 注入场景加：command_template_injection",
            "- 资源访问场景加：idor_enumeration, path_traversal, ssrf_probe",
            "",
            "性能测试（run_performance_test）建议：",
            "- 基线压测：vus=10, duration_seconds=30, ramp_up_seconds=5",
            "- 发布门禁：vus=30~80, duration_seconds=120, ramp_up_seconds=20, 关注 p95 与错误率",
            "- 大促预演：vus>=100, duration_seconds>=300, 配合 target_tps 做容量验证",
            "",
        ]
        actions: list[dict[str, str]] = []
        if collection_id:
            actions = [
                {
                    "label": "跑安全扫描（全量）",
                    "command": f"请调用 run_security_test 工具，collection_id={collection_id}",
                },
                {
                    "label": "跑性能基线",
                    "command": (
                        "请调用 run_performance_test 工具，"
                        f"collection_id={collection_id}, vus=10, duration_seconds=30, ramp_up_seconds=5"
                    ),
                },
            ]
        return _tool_ok(
            "安全/性能配置建议已生成。",
            data={"goal": goal, "collectionId": collection_id or None, "guide": "\n".join(lines)},
            actions=actions or None,
        )

    elif tool_name == "analyze_page_context":
        current_path = str(args.get("current_path") or "").strip()
        query = str(args.get("query") or "").strip()
        active_module = str(args.get("active_module") or "").strip()
        page_title = str(args.get("page_title") or "").strip()
        focus = str(args.get("focus") or "").strip() or "功能+稳定性"

        module_hint = active_module or "unknown"
        if not module_hint and current_path:
            path_lower = current_path.lower()
            if "requirement" in path_lower:
                module_hint = "requirements"
            elif "security" in path_lower:
                module_hint = "security"
            elif "performance" in path_lower:
                module_hint = "performance"
            elif "api" in path_lower:
                module_hint = "api-testing"
            elif "case" in path_lower:
                module_hint = "test-cases"
            else:
                module_hint = "dashboard"

        lines = [
            "页面上下文分析：",
            f"- path: {current_path or '(unknown)'}",
            f"- query: {query or '(none)'}",
            f"- module: {module_hint}",
            f"- title: {page_title or '(unknown)'}",
            f"- focus: {focus}",
            "",
            "建议下一步：",
        ]
        actions: list[dict[str, str]] = []
        if module_hint in {"requirements", "dashboard"}:
            lines.append("- 先运行覆盖缺口分析（analyze_test_gap），明确哪些需求无用例。")
            actions.append({"label": "分析需求覆盖缺口", "command": "请调用 analyze_test_gap 工具，limit=20"})
        if module_hint in {"api-testing", "test-cases"}:
            lines.append("- 汇总近失败记录并优先修复高频问题。")
            actions.append({"label": "汇总失败记录", "command": "请调用 summarize_run_failures 工具，limit=30"})
            actions.append({"label": "推荐最小回归集", "command": "请调用 recommend_regression_scope 工具，limit=15"})
        if module_hint == "security":
            lines.append("- 先跑全量安全扫描，再按高危/严重排序修复。")
            actions.append({"label": "执行安全扫描", "command": "请调用 run_security_test 工具，collection_id=<你的集合ID>"})
        if module_hint == "performance":
            lines.append("- 先做 30 秒基线压测，再扩大并发做容量评估。")
            actions.append(
                {
                    "label": "执行性能基线",
                    "command": "请调用 run_performance_test 工具，collection_id=<你的集合ID>, vus=10, duration_seconds=30, ramp_up_seconds=5",
                }
            )
        if not actions:
            actions.append({"label": "列出项目", "command": "请调用 list_projects 工具"})
            actions.append({"label": "列出需求", "command": "请调用 list_requirements_records 工具，limit=20"})

        return _tool_ok(
            "页面上下文分析完成。",
            data={
                "path": current_path or None,
                "query": query or None,
                "module": module_hint,
                "title": page_title or None,
                "focus": focus,
                "guide": "\n".join(lines),
            },
            actions=actions,
        )

    elif tool_name == "orchestrate_testing_workflow":
        workflow = str(args.get("workflow") or "").strip().lower()
        project_id = str(args.get("project_id") or "").strip()
        collection_id = str(args.get("collection_id") or "").strip()
        requirement_id = str(args.get("requirement_id") or "").strip()
        case_id = str(args.get("case_id") or "").strip()
        request_id = str(args.get("request_id") or "").strip()
        target_url = str(args.get("target_url") or "").strip()
        execute = bool(args.get("execute", False))
        limit_raw = args.get("limit", 20)
        try:
            limit = max(5, min(int(limit_raw), 100))
        except Exception:
            limit = 20

        supported_workflows = {
            "coverage_scan",
            "stability_scan",
            "release_gate",
            "full_e2e_bootstrap",
            "api_regression_flow",
            "security_perf_flow",
        }
        if workflow not in supported_workflows:
            return _tool_error(
                "workflow 必须是 coverage_scan / stability_scan / release_gate / full_e2e_bootstrap / api_regression_flow / security_perf_flow。",
                "INVALID_ARGUMENT",
            )

        if project_id:
            proj_org = _project_org(project_id)
            if not proj_org:
                return _tool_error(f"项目 {project_id} 不存在。", "NOT_FOUND")
            denied = _assert_org_access(proj_org)
            if denied:
                return _tool_error(denied, "FORBIDDEN")
        if collection_id:
            row = db.fetchone(
                """
                SELECT c.id, c.org_id, c.project_id
                FROM api_collections c
                WHERE c.id = ? AND c.deleted_at IS NULL
                """,
                (collection_id,),
            )
            if not row:
                return _tool_error(f"集合 {collection_id} 不存在。", "NOT_FOUND")
            denied = _assert_org_access(str(row.get("org_id") or ""))
            if denied:
                return _tool_error(denied, "FORBIDDEN")
            if not project_id:
                project_id = str(row.get("project_id") or "")

        steps: list[dict[str, Any]] = []
        actions: list[dict[str, str]] = []
        summary: dict[str, Any] = {
            "workflow": workflow,
            "projectId": project_id or None,
            "collectionId": collection_id or None,
            "requirementId": requirement_id or None,
            "caseId": case_id or None,
            "requestId": request_id or None,
        }

        async def _call_tool_json(name: str, payload: dict[str, Any]) -> dict[str, Any]:
            raw = await execute_tool_call(
                name,
                json.dumps(payload, ensure_ascii=False),
                db,
                actor_id=actor_id,
                api_testing=api_testing,
                performance_testing=performance_testing,
                security_testing=security_testing,
                smithery=smithery,
            )
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    if "tool" not in parsed:
                        parsed["tool"] = name
                    return parsed
            except Exception:
                pass
            text = str(raw or "").strip()
            text_lower = text.lower()
            bad_tokens = ("失败", "出错", "error", "not found", "invalid", "不可用", "缺少")
            guessed_ok = not any(token in text_lower for token in bad_tokens)
            return {"ok": guessed_ok, "tool": name, "message": text, "data": {}}

        if workflow in {"full_e2e_bootstrap", "api_regression_flow"}:
            default_name = f"AI 全流程项目 {datetime.now().strftime('%Y%m%d%H%M%S')}"
            project_name = str(args.get("project_name") or "").strip() or default_name
            project_description = str(args.get("project_description") or "").strip() or "由 AI 工作流自动创建的测试项目"
            org_id = str(args.get("org_id") or "DEFAULT_ORG").strip() or "DEFAULT_ORG"
            created_by = str(args.get("created_by") or actor_id or "ai-agent").strip() or "ai-agent"

            if not project_id:
                proj_result = await _call_tool_json(
                    "create_project_record",
                    {
                        "name": project_name,
                        "description": project_description,
                        "org_id": org_id,
                        "created_by": created_by,
                    },
                )
                if not bool(proj_result.get("ok")):
                    return _tool_error(
                        f"全流程编排失败：项目创建失败（{(proj_result.get('error') or {}).get('message') or proj_result.get('message') or 'unknown'}）。",
                        "WORKFLOW_STEP_FAILED",
                        data={"failedStep": "create_project_record", "detail": proj_result},
                    )
                project_id = str((proj_result.get("data") or {}).get("id") or "").strip()
                steps.append({"step": "create_project_record", "ok": True, "detail": proj_result})
                summary["projectId"] = project_id or None

            if not requirement_id:
                requirement_title = str(args.get("requirement_title") or "").strip() or "AI 自动生成需求"
                requirement_content = str(args.get("requirement_content") or "").strip() or (
                    "目标：打通测试全流程。验收：可完成项目、需求、用例、接口创建，并可执行安全/性能测试。"
                )
                req_result = await _call_tool_json(
                    "create_requirement_record",
                    {
                        "project_id": project_id,
                        "org_id": org_id,
                        "title": requirement_title,
                        "content": requirement_content,
                        "created_by": created_by,
                    },
                )
                if not bool(req_result.get("ok")):
                    return _tool_error(
                        f"全流程编排失败：需求创建失败（{(req_result.get('error') or {}).get('message') or req_result.get('message') or 'unknown'}）。",
                        "WORKFLOW_STEP_FAILED",
                        data={"failedStep": "create_requirement_record", "detail": req_result},
                    )
                requirement_id = str((req_result.get("data") or {}).get("id") or "").strip()
                steps.append({"step": "create_requirement_record", "ok": True, "detail": req_result})
                summary["requirementId"] = requirement_id or None

            if not case_id:
                case_title = str(args.get("case_title") or "").strip() or "AI 自动化接口回归用例"
                case_steps = args.get("case_steps")
                case_step_list = [str(item) for item in case_steps] if isinstance(case_steps, list) else [
                    "准备测试环境与鉴权信息",
                    "发送接口请求",
                    "校验状态码、关键字段和响应时间",
                ]
                case_result = await _call_tool_json(
                    "create_test_case_record",
                    {
                        "project_id": project_id,
                        "org_id": org_id,
                        "requirement_id": requirement_id or None,
                        "title": case_title,
                        "kind": "api",
                        "objective": str(args.get("case_objective") or "验证核心接口流程可用"),
                        "steps": case_step_list,
                        "assertion_hints": args.get("assertion_hints") if isinstance(args.get("assertion_hints"), list) else ["HTTP 2xx", "响应结构符合预期"],
                        "priority": str(args.get("priority") or "P1"),
                        "status": str(args.get("case_status") or "draft"),
                        "created_by": created_by,
                    },
                )
                if not bool(case_result.get("ok")):
                    return _tool_error(
                        f"全流程编排失败：用例创建失败（{(case_result.get('error') or {}).get('message') or case_result.get('message') or 'unknown'}）。",
                        "WORKFLOW_STEP_FAILED",
                        data={"failedStep": "create_test_case_record", "detail": case_result},
                    )
                case_id = str((case_result.get("data") or {}).get("id") or "").strip()
                steps.append({"step": "create_test_case_record", "ok": True, "detail": case_result})
                summary["caseId"] = case_id or None

            if not request_id:
                api_url = str(args.get("api_url") or args.get("url") or "").strip() or "/api/health"
                api_result = await _call_tool_json(
                    "create_api_test_case",
                    {
                        "name": str(args.get("api_name") or "AI 自动生成接口步骤"),
                        "method": str(args.get("api_method") or "GET").strip().upper(),
                        "url": api_url,
                        "project_id": project_id,
                        "collection_id": collection_id or None,
                        "case_id": case_id or None,
                        "headers": args.get("api_headers") if isinstance(args.get("api_headers"), list) else [],
                        "query": args.get("api_query") if isinstance(args.get("api_query"), list) else [],
                        "body_mode": str(args.get("api_body_mode") or "none"),
                        "body_raw": str(args.get("api_body_raw") or ""),
                        "test_script": str(args.get("api_test_script") or ""),
                    },
                )
                if not bool(api_result.get("ok")):
                    return _tool_error(
                        f"全流程编排失败：接口步骤创建失败（{(api_result.get('error') or {}).get('message') or api_result.get('message') or 'unknown'}）。",
                        "WORKFLOW_STEP_FAILED",
                        data={"failedStep": "create_api_test_case", "detail": api_result},
                    )
                api_data = api_result.get("data") or {}
                request_id = str(api_data.get("requestId") or "").strip()
                collection_id = str(api_data.get("collectionId") or collection_id or "").strip()
                steps.append({"step": "create_api_test_case", "ok": True, "detail": api_result})
                summary["requestId"] = request_id or None
                summary["collectionId"] = collection_id or None
                summary["apiUrlFallbackUsed"] = not bool(str(args.get("api_url") or args.get("url") or "").strip())

            actions.append({"label": "查看用例列表", "command": f"请调用 list_test_cases_records 工具，project_id={project_id}, limit=20"})
            if request_id:
                actions.append({"label": "查看最近失败日志", "command": f"请调用 get_latest_failed_log 工具，request_id={request_id}"})

            if execute and request_id:
                run_result = await _call_tool_json(
                    "execute_api_test_case",
                    {
                        "request_id": request_id,
                        "environment_id": str(args.get("environment_id") or "").strip() or None,
                        "timeout_ms": int(args.get("timeout_ms") or 15000),
                        "verify_ssl": bool(args.get("verify_ssl", True)),
                    },
                )
                steps.append({"step": "execute_api_test_case", "ok": bool(run_result.get("ok")), "detail": run_result})
                run_security = bool(args.get("run_security", True))
                run_performance = bool(args.get("run_performance", True))
                if collection_id and run_security:
                    sec_result = await _call_tool_json(
                        "run_security_test",
                        {
                            "collection_id": collection_id,
                            "project_id": project_id or None,
                        },
                    )
                    steps.append({"step": "run_security_test", "ok": bool(sec_result.get("ok")), "detail": sec_result})
                if collection_id and run_performance:
                    perf_result = await _call_tool_json(
                        "run_performance_test",
                        {
                            "collection_id": collection_id,
                            "project_id": project_id or None,
                            "vus": max(1, int(args.get("vus") or 10)),
                            "duration_seconds": max(5, int(args.get("duration_seconds") or 30)),
                            "ramp_up_seconds": max(0, int(args.get("ramp_up_seconds") or 5)),
                            "timeout_ms": int(args.get("timeout_ms") or 15000),
                            "verify_ssl": bool(args.get("verify_ssl", True)),
                        },
                    )
                    steps.append({"step": "run_performance_test", "ok": bool(perf_result.get("ok")), "detail": perf_result})

        if workflow == "api_regression_flow":
            actions.append({"label": "汇总失败记录", "command": f"请调用 summarize_run_failures 工具，collection_id={collection_id}, limit={limit}" if collection_id else "请调用 summarize_run_failures 工具，limit=20"})
            actions.append({"label": "推荐最小回归集", "command": f"请调用 recommend_regression_scope 工具，collection_id={collection_id}, limit=15" if collection_id else "请调用 recommend_regression_scope 工具，limit=15"})

        if workflow == "security_perf_flow":
            if not collection_id and not target_url:
                return _tool_error("security_perf_flow 需要 collection_id 或 target_url。", "INVALID_ARGUMENT")
            if execute:
                sec_payload: dict[str, Any] = {"project_id": project_id or None}
                if collection_id:
                    sec_payload["collection_id"] = collection_id
                if target_url:
                    sec_payload["target_url"] = target_url
                sec_result = await _call_tool_json("run_security_test", sec_payload)
                steps.append({"step": "run_security_test", "ok": bool(sec_result.get("ok")), "detail": sec_result})
                if collection_id:
                    perf_result = await _call_tool_json(
                        "run_performance_test",
                        {
                            "collection_id": collection_id,
                            "project_id": project_id or None,
                            "vus": max(1, int(args.get("vus") or 10)),
                            "duration_seconds": max(5, int(args.get("duration_seconds") or 30)),
                            "ramp_up_seconds": max(0, int(args.get("ramp_up_seconds") or 5)),
                            "timeout_ms": int(args.get("timeout_ms") or 15000),
                            "verify_ssl": bool(args.get("verify_ssl", True)),
                        },
                    )
                    steps.append({"step": "run_performance_test", "ok": bool(perf_result.get("ok")), "detail": perf_result})
                else:
                    steps.append(
                        {
                            "step": "run_performance_test",
                            "ok": False,
                            "detail": {"message": "仅提供 target_url 时无法执行性能压测，需提供 collection_id。"},
                        }
                    )
            actions.append({"label": "执行安全扫描", "command": f"请调用 run_security_test 工具，collection_id={collection_id}" if collection_id else f"请调用 run_security_test 工具，target_url={target_url}"})
            if collection_id:
                actions.append(
                    {
                        "label": "执行性能测试",
                        "command": f"请调用 run_performance_test 工具，collection_id={collection_id}, vus=10, duration_seconds=30, ramp_up_seconds=5",
                    }
                )

        if workflow in {"coverage_scan", "release_gate"}:
            req_where = ["deleted_at IS NULL"]
            req_params: list[Any] = []
            if project_id:
                req_where.append("project_id = ?")
                req_params.append(project_id)
            org_placeholders = ",".join(["?"] * len(actor_org_ids))
            req_where.append(f"org_id IN ({org_placeholders})")
            req_params.extend(list(actor_org_ids))
            req_rows = db.fetchall(
                f"SELECT id FROM requirements WHERE {' AND '.join(req_where)} LIMIT 500",
                tuple(req_params),
            )
            req_ids = [str(r.get("id") or "") for r in req_rows if str(r.get("id") or "")]
            uncovered = 0
            if req_ids:
                placeholders = ",".join(["?"] * len(req_ids))
                cov = db.fetchall(
                    f"""
                    SELECT requirement_id, COUNT(*) AS cnt
                    FROM cases
                    WHERE deleted_at IS NULL AND requirement_id IN ({placeholders})
                    GROUP BY requirement_id
                    """,
                    tuple(req_ids),
                )
                covered = {str(x.get("requirement_id")) for x in cov if int(x.get("cnt") or 0) > 0}
                uncovered = max(0, len(req_ids) - len(covered))
            steps.append(
                {
                    "step": "coverage_scan",
                    "ok": True,
                    "detail": {"requirements": len(req_ids), "uncovered": uncovered},
                }
            )
            summary["coverage"] = {"requirements": len(req_ids), "uncovered": uncovered}
            actions.append(
                {
                    "label": "执行覆盖缺口分析",
                    "command": f"请调用 analyze_test_gap 工具，project_id={project_id}" if project_id else "请调用 analyze_test_gap 工具，limit=20",
                }
            )

        if workflow in {"stability_scan", "release_gate"}:
            run_where = ["rr.success = 0"]
            run_params: list[Any] = []
            if collection_id:
                run_where.append("rr.collection_id = ?")
                run_params.append(collection_id)
            elif project_id:
                run_where.append("c.project_id = ?")
                run_params.append(project_id)
            org_placeholders = ",".join(["?"] * len(actor_org_ids))
            run_where.append(f"c.org_id IN ({org_placeholders})")
            run_params.extend(list(actor_org_ids))
            run_params.append(limit)
            fail_rows = db.fetchall(
                f"""
                SELECT rr.request_id, rr.status_code, rr.error_message, rr.created_at
                FROM api_request_runs rr
                JOIN api_collections c ON c.id = rr.collection_id
                WHERE {' AND '.join(run_where)}
                ORDER BY rr.created_at DESC
                LIMIT ?
                """,
                tuple(run_params),
            )
            fail_count = len(fail_rows)
            status_5xx = sum(1 for r in fail_rows if int(r.get("status_code") or 0) >= 500)
            steps.append(
                {
                    "step": "stability_scan",
                    "ok": True,
                    "detail": {"failures": fail_count, "serverErrors": status_5xx},
                }
            )
            summary["stability"] = {"failures": fail_count, "serverErrors": status_5xx}
            if collection_id:
                actions.append({"label": "汇总失败记录", "command": f"请调用 summarize_run_failures 工具，collection_id={collection_id}, limit={limit}"})
                actions.append({"label": "推荐最小回归集", "command": f"请调用 recommend_regression_scope 工具，collection_id={collection_id}, limit=15"})

        executed: list[str] = []
        if execute and workflow == "release_gate" and collection_id and api_testing and security_testing and performance_testing:
            sec_args = {"collection_id": collection_id}
            if project_id:
                sec_args["project_id"] = project_id
            sec_result_raw = await execute_tool_call(
                "run_security_test",
                json.dumps(sec_args, ensure_ascii=False),
                db,
                actor_id=actor_id,
                api_testing=api_testing,
                performance_testing=performance_testing,
                security_testing=security_testing,
                smithery=smithery,
            )
            perf_args = {
                "collection_id": collection_id,
                "project_id": project_id or None,
                "vus": 10,
                "duration_seconds": 30,
                "ramp_up_seconds": 5,
            }
            perf_result_raw = await execute_tool_call(
                "run_performance_test",
                json.dumps(perf_args, ensure_ascii=False),
                db,
                actor_id=actor_id,
                api_testing=api_testing,
                performance_testing=performance_testing,
                security_testing=security_testing,
                smithery=smithery,
            )
            executed.extend(["run_security_test", "run_performance_test"])
            sec_result: Any
            perf_result: Any
            try:
                sec_result = json.loads(sec_result_raw)
            except Exception:
                sec_result = {"ok": False, "raw": sec_result_raw}
            try:
                perf_result = json.loads(perf_result_raw)
            except Exception:
                perf_result = {"ok": False, "raw": perf_result_raw}
            steps.append({"step": "execute_security", "ok": bool(sec_result.get("ok")), "detail": sec_result})
            steps.append({"step": "execute_performance", "ok": bool(perf_result.get("ok")), "detail": perf_result})
            summary["execution"] = {"security": sec_result, "performance": perf_result}

        summary["executed"] = executed
        operation_id = new_id("aiop")
        try:
            db.execute(
                """
                INSERT INTO ai_operations (
                  id, operation_type, target_type, target_id, status,
                  request_payload, response_payload, error_message, created_by,
                  attempt_count, created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    f"workflow:{workflow}",
                    "project" if project_id else ("collection" if collection_id else "scope"),
                    project_id or collection_id or "global",
                    "succeeded",
                    json.dumps(args, ensure_ascii=False),
                    json.dumps({"summary": summary, "steps": steps}, ensure_ascii=False),
                    None,
                    actor_id or "ai-agent",
                    1,
                    utc_now(),
                    utc_now(),
                    utc_now(),
                    utc_now(),
                ),
            )
            summary["operationId"] = operation_id
        except Exception:
            pass
        return _tool_ok("工作流编排完成。", data={"summary": summary, "steps": steps}, actions=actions)

    return f"找不到注册的工具方法：{tool_name}"


# =====================================================================
# AI Service 核心类
# =====================================================================
class AIChatService:
    """封装 LLM API 调用，支持 Agent Function Calling 和流式交互。"""

    def __init__(
        self,
        db: Database,
        api_testing: "ApiTestingService | None" = None,
        performance_testing: "PerformanceTestingService | None" = None,
        security_testing: "SecurityTestingService | None" = None,
        smithery: "SmitheryService | None" = None,
        base_url: str | None = "https://api.deepseek.com/v1",
        api_key: str | None = "",
        model: str | None = "deepseek-chat",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self.db = db
        self.base_url = (base_url or "https://api.deepseek.com/v1").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or "deepseek-chat"
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.api_testing = api_testing
        self.performance_testing = performance_testing
        self.security_testing = security_testing
        self.smithery = smithery
        self._client: httpx.AsyncClient | None = None
        self._ensure_default_prompt_templates()
        self._ensure_default_agents_hooks_plugins()

    def resolve_runtime_config(self, user_settings: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = user_settings or {}
        base_url = str(
            raw.get("modelBaseUrl")
            or raw.get("aiEndpoint")
            or raw.get("ai_endpoint")
            or self.base_url
            or "https://api.deepseek.com/v1"
        ).rstrip("/")
        api_key = str(raw.get("modelApiKey") or raw.get("aiKey") or raw.get("ai_key") or self.api_key or "").strip()
        model = str(raw.get("modelName") or raw.get("aiModel") or raw.get("ai_model") or self.model or "deepseek-chat").strip()
        temperature_raw = raw.get("temperature", raw.get("aiTemperature", raw.get("ai_temperature", self.temperature)))
        max_tokens_raw = raw.get("maxTokens", raw.get("aiMaxTokens", raw.get("ai_max_tokens", self.max_tokens)))
        system_prompt = self._sanitize_user_system_prompt(
            str(raw.get("systemPrompt") or raw.get("aiSystemPrompt") or raw.get("ai_system_prompt") or "").strip()
        )
        custom_rules_raw = raw.get("customRules", raw.get("custom_rules"))
        mcp_servers_raw = raw.get("mcpServers", raw.get("mcp_servers"))
        skill_paths_raw = raw.get("skillSearchPaths", raw.get("skill_search_paths"))
        custom_rules = (
            self._sanitize_custom_rules([str(item).strip() for item in (custom_rules_raw or []) if str(item).strip()])
            if isinstance(custom_rules_raw, list)
            else []
        )
        mcp_servers = [item for item in (mcp_servers_raw or []) if isinstance(item, dict)] if isinstance(mcp_servers_raw, list) else []
        skill_search_paths = [str(item).strip() for item in (skill_paths_raw or []) if str(item).strip()] if isinstance(skill_paths_raw, list) else []
        try:
            temperature = float(temperature_raw)
        except Exception:
            temperature = float(self.temperature)
        try:
            max_tokens = int(max_tokens_raw)
        except Exception:
            max_tokens = int(self.max_tokens)
        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system_prompt": system_prompt,
            "custom_rules": custom_rules,
            "mcp_servers": mcp_servers,
            "skill_search_paths": skill_search_paths,
        }

    def _candidate_base_urls(self, base_url: str) -> list[str]:
        raw = str(base_url or "").strip().rstrip("/")
        if not raw:
            return []

        normalized_base = raw
        for suffix in ("/chat/completions", "/models"):
            if normalized_base.endswith(suffix):
                normalized_base = normalized_base[: -len(suffix)].rstrip("/")
                break

        candidates: list[str] = []
        if normalized_base.endswith("/v1"):
            candidates.append(normalized_base)
        else:
            # Prefer OpenAI-compatible /v1 first; then fallback to raw.
            candidates.extend([f"{normalized_base}/v1", normalized_base])

        for item in list(candidates):
            if not item.endswith("/v1"):
                candidates.append(f"{item}/v1")

        # Keep order and de-duplicate.
        dedup: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            normalized = item.rstrip("/")
            if normalized and normalized not in seen:
                seen.add(normalized)
                dedup.append(normalized)
        return dedup

    def _should_retry_candidate(self, status_code: int | None) -> bool:
        # Some gateways return 502 for wrong upstream path (instead of 404).
        return status_code in {400, 404, 405, 502}

    def _sanitize_user_system_prompt(self, prompt: str) -> str:
        text = str(prompt or "").strip()
        if not text:
            return ""
        if any(marker in text for marker in RIGID_PROMPT_MARKERS):
            return ""
        return text[:3000]

    def _sanitize_custom_rules(self, rules: list[str]) -> list[str]:
        cleaned: list[str] = []
        for rule in rules:
            text = str(rule or "").strip()
            if not text:
                continue
            if any(marker in text for marker in RIGID_PROMPT_MARKERS):
                continue
            cleaned.append(text)
        return cleaned[:12]

    def _sanitize_template_contract(self, task_type: str, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if task_type == "general":
            return "自然中文；寒暄、确认、状态同步只回复一句，不要列步骤。"
        if any(marker in raw for marker in RIGID_PROMPT_MARKERS):
            fallback = DEFAULT_TASK_PROMPTS.get(task_type) or DEFAULT_TASK_PROMPTS["general"]
            return str(fallback.get("output_contract") or "").strip()
        return raw

    @staticmethod
    def _is_smalltalk(messages: list[dict[str, Any]]) -> bool:
        latest = next(
            (str(item.get("content") or "").strip() for item in reversed(messages) if str(item.get("role") or "") == "user"),
            "",
        )
        normalized = latest.replace(" ", "").lower()
        return normalized in {
            "你好",
            "hello",
            "hi",
            "在吗",
            "欢迎回来",
            "早",
            "早上好",
            "下午好",
            "晚上好",
            "ok",
            "好的",
        } or (len(normalized) <= 8 and any(word in normalized for word in ("你好", "hello", "hi", "在吗")))

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120, connect=10),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def test_connection(self, user_settings: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = self.resolve_runtime_config(user_settings)
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        api_key = str(cfg.get("api_key") or "").strip()
        model = str(cfg.get("model") or "").strip()
        if not base_url:
            return {
                "ok": False,
                "message": "模型 API Base URL 为空，请先配置。",
                "baseUrl": base_url,
                "model": model,
            }
        if not model:
            return {
                "ok": False,
                "message": "模型名称为空，请先配置。",
                "baseUrl": base_url,
                "model": model,
            }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        started = time.perf_counter()
        candidate_urls = self._candidate_base_urls(base_url)
        last_status_code: int | None = None
        last_detail = ""
        try:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Try URL candidates (raw + auto /v1) to maximize compatibility.
                for candidate in candidate_urls:
                    async with session.get(f"{candidate}/models", headers=headers) as models_res:
                        last_status_code = models_res.status
                        elapsed = int((time.perf_counter() - started) * 1000)
                        if models_res.status < 400:
                            data = {}
                            ctype = (models_res.headers.get("Content-Type") or "").lower()
                            if "application/json" in ctype:
                                try:
                                    data = await models_res.json(content_type=None)
                                except Exception:
                                    data = {}
                            found = False
                            if isinstance(data, dict) and isinstance(data.get("data"), list):
                                found = any(str(item.get("id") or "") == model for item in data["data"] if isinstance(item, dict))
                            return {
                                "ok": True,
                                "message": "模型服务连通成功。",
                                "baseUrl": candidate,
                                "model": model,
                                "latencyMs": elapsed,
                                "modelFound": found,
                                "statusCode": models_res.status,
                            }

                    async with session.post(
                        f"{candidate}/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 8,
                            "temperature": 0,
                            "stream": False,
                        },
                    ) as fallback_res:
                        last_status_code = fallback_res.status
                        last_detail = (await fallback_res.text())[:300]
                        elapsed = int((time.perf_counter() - started) * 1000)
                        if fallback_res.status < 400:
                            return {
                                "ok": True,
                                "message": "模型服务连通成功（通过 chat/completions 校验）。",
                                "baseUrl": candidate,
                                "model": model,
                                "latencyMs": elapsed,
                                "statusCode": fallback_res.status,
                            }

                    # For path mismatch style errors, continue to next candidate.
                    if self._should_retry_candidate(last_status_code):
                        continue

            elapsed = int((time.perf_counter() - started) * 1000)
            return {
                "ok": False,
                "message": f"连接失败：HTTP {last_status_code or '-'}",
                "baseUrl": base_url,
                "model": model,
                "latencyMs": elapsed,
                "statusCode": last_status_code,
                "detail": last_detail,
            }
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            return {
                "ok": False,
                "message": f"连接异常：{exc}",
                "baseUrl": base_url,
                "model": model,
                "latencyMs": elapsed,
            }

    async def discover_models(self, user_settings: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = self.resolve_runtime_config(user_settings)
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        api_key = str(cfg.get("api_key") or "").strip()
        selected_model = str(cfg.get("model") or "").strip()
        if not base_url:
            return {
                "ok": False,
                "message": "模型 API Base URL 为空，请先配置。",
                "baseUrl": base_url,
                "models": [],
                "recommendedModels": [],
            }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        candidate_urls = self._candidate_base_urls(base_url)
        started = time.perf_counter()
        last_status_code: int | None = None
        last_detail = ""

        try:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for candidate in candidate_urls:
                    async with session.get(f"{candidate}/models", headers=headers) as resp:
                        last_status_code = resp.status
                        text = await resp.text()
                        if resp.status >= 400:
                            last_detail = text[:300]
                            if self._should_retry_candidate(resp.status):
                                continue
                            break

                        data: Any = {}
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError:
                            data = {}
                        items = data.get("data") if isinstance(data, dict) else []
                        models: list[str] = []
                        if isinstance(items, list):
                            for item in items:
                                if isinstance(item, dict):
                                    model_id = str(item.get("id") or "").strip()
                                    if model_id:
                                        models.append(model_id)
                        models = sorted(set(models))

                        preferred = [
                            "gpt-5.3-codex",
                            "claude-sonnet-4-6",
                            "gpt-5.1-codex",
                            "gpt-5-codex",
                            "qwen-plus",
                            "deepseek-chat",
                        ]
                        recommended = [m for m in preferred if m in models][:4]
                        if not recommended:
                            recommended = [
                                m for m in models
                                if any(k in m.lower() for k in ("codex", "sonnet", "deepseek", "qwen", "gpt-5"))
                            ][:4]

                        elapsed = int((time.perf_counter() - started) * 1000)
                        return {
                            "ok": True,
                            "message": f"已发现 {len(models)} 个模型。",
                            "baseUrl": candidate,
                            "statusCode": resp.status,
                            "latencyMs": elapsed,
                            "models": models,
                            "recommendedModels": recommended,
                            "selectedModelAvailable": selected_model in models if selected_model else False,
                        }
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            return {
                "ok": False,
                "message": f"模型发现异常：{exc}",
                "baseUrl": base_url,
                "statusCode": last_status_code,
                "latencyMs": elapsed,
                "models": [],
                "recommendedModels": [],
            }

        elapsed = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "message": f"发现模型失败：HTTP {last_status_code or '-'}",
            "baseUrl": base_url,
            "statusCode": last_status_code,
            "latencyMs": elapsed,
            "detail": last_detail,
            "models": [],
            "recommendedModels": [],
        }

    def get_provider(self):
        """Build and return a ModelProvider instance based on the service configuration."""
        from app.services.providers import OpenAICompatibleProvider
        from app.config import get_settings
        settings = get_settings()
        return OpenAICompatibleProvider(
            settings=settings,
            api_key=self.api_key,
            base_url=self.base_url,
            model_name=self.model
        )

    def append_chat_message(
        self,
        *,
        user_id: str,
        role: str,
        content: str,
        model: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        task_type: str | None = None,
        agent_key: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        text = str(content or "").strip()
        if not text:
            return
        self.db.execute(
            """
            INSERT INTO ai_chat_messages (
                id, user_id, session_id, project_id, role, content, model, task_type, agent_key,
                token_estimate, meta_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("aicm"),
                user_id,
                session_id,
                project_id,
                role,
                text,
                model,
                task_type,
                agent_key,
                self._estimate_tokens(text),
                json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else None,
                utc_now(),
            ),
        )
        if session_id:
            self._touch_chat_session(session_id)

    def list_chat_messages(
        self,
        *,
        user_id: str,
        limit: int = 100,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = "WHERE user_id = ?"
        params: list[Any] = [user_id]
        if session_id:
            where += " AND session_id = ?"
            params.append(session_id)
        params.append(max(1, min(limit, 500)))
        rows = self.db.fetchall(
            f"""
            SELECT id, user_id, session_id, project_id, role, content, model, task_type, agent_key,
                   token_estimate, meta_json, created_at
            FROM ai_chat_messages
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            meta: dict[str, Any] | None = None
            raw = row.get("meta_json")
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        meta = parsed
                except json.JSONDecodeError:
                    meta = None
            result.append(
                {
                    "id": row["id"],
                    "userId": row["user_id"],
                    "sessionId": row.get("session_id"),
                    "projectId": row.get("project_id"),
                    "role": row["role"],
                    "content": row["content"],
                    "model": row.get("model"),
                    "taskType": row.get("task_type"),
                    "agentKey": row.get("agent_key"),
                    "tokenEstimate": int(row.get("token_estimate") or 0),
                    "meta": meta,
                    "createdAt": row["created_at"],
                }
            )
        return list(reversed(result))

    def clear_chat_messages(self, *, user_id: str) -> int:
        return self.db.execute("DELETE FROM ai_chat_messages WHERE user_id = ?", (user_id,))

    def ensure_chat_session(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        project_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        if session_id:
            existing = self.get_chat_session(session_id=session_id, user_id=user_id)
            if existing:
                return existing
        if not session_id:
            recent = self.db.fetchone(
                """
                SELECT *
                FROM ai_chat_sessions
                WHERE user_id = ? AND COALESCE(project_id, '') = COALESCE(?, '')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, project_id),
            )
            if recent:
                return self._row_to_session(recent)
            session_id = new_id("ais")
        safe_title = str(title or "AI 对话").strip()[:120] or "AI 对话"
        self.db.execute(
            """
            INSERT INTO ai_chat_sessions (
                id, user_id, project_id, title, summary, summary_updated_at, message_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (session_id, user_id, project_id, safe_title, "", None, 0, now, now),
        )
        return self.get_chat_session(session_id=session_id, user_id=user_id) or {
            "id": session_id,
            "userId": user_id,
            "projectId": project_id,
            "title": safe_title,
            "summary": "",
            "messageCount": 0,
            "createdAt": now,
            "updatedAt": now,
        }

    def list_chat_sessions(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM ai_chat_sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, max(1, min(limit, 200))),
        )
        return [self._row_to_session(row) for row in rows]

    def get_chat_session(self, *, session_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        if user_id:
            row = self.db.fetchone(
                "SELECT * FROM ai_chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
        else:
            row = self.db.fetchone("SELECT * FROM ai_chat_sessions WHERE id = ?", (session_id,))
        return self._row_to_session(row) if row else None

    def delete_chat_session(self, *, session_id: str, user_id: str) -> bool:
        session = self.get_chat_session(session_id=session_id, user_id=user_id)
        if not session:
            return False
        self.db.execute("DELETE FROM ai_chat_messages WHERE session_id = ? AND user_id = ?", (session_id, user_id))
        deleted = self.db.execute("DELETE FROM ai_chat_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        return int(deleted or 0) > 0

    def summarize_chat_session(self, *, session_id: str, user_id: str) -> dict[str, Any]:
        messages = self.list_chat_messages(user_id=user_id, session_id=session_id, limit=200)
        summary = self._build_extractive_summary(messages)
        now = utc_now()
        self.db.execute(
            """
            UPDATE ai_chat_sessions
            SET summary = ?, summary_updated_at = ?, message_count = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (summary, now, len(messages), now, session_id, user_id),
        )
        return self.get_chat_session(session_id=session_id, user_id=user_id) or {}

    def _touch_chat_session(self, session_id: str) -> None:
        row = self.db.fetchone(
            "SELECT user_id FROM ai_chat_sessions WHERE id = ?",
            (session_id,),
        )
        if not row:
            return
        count_row = self.db.fetchone(
            "SELECT COUNT(1) AS c FROM ai_chat_messages WHERE session_id = ?",
            (session_id,),
        )
        count = int(count_row.get("c") or 0) if count_row else 0
        self.db.execute(
            "UPDATE ai_chat_sessions SET message_count = ?, updated_at = ? WHERE id = ?",
            (count, utc_now(), session_id),
        )

    @staticmethod
    def _row_to_session(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "userId": row.get("user_id"),
            "projectId": row.get("project_id"),
            "title": row.get("title") or "",
            "summary": row.get("summary") or "",
            "summaryUpdatedAt": row.get("summary_updated_at"),
            "messageCount": int(row.get("message_count") or 0),
            "createdAt": row.get("created_at"),
            "updatedAt": row.get("updated_at"),
        }

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        raw = str(text or "")
        return max(1, int(len(raw) / 3.5)) if raw else 0

    def _build_extractive_summary(self, messages: list[dict[str, Any]]) -> str:
        useful: list[str] = []
        for item in messages[-24:]:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip().replace("\r\n", "\n")
            if not content:
                continue
            useful.append(f"{role}: {content[:260]}")
        if not useful:
            return ""
        return "会话摘要（自动压缩，保留最近关键意图与结论）：\n" + "\n".join(useful)[-3000:]

    # ------------------------------------------------------------------
    # 非流式对话
    # ------------------------------------------------------------------
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        context: str | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> str:
        cfg = runtime_config or self.resolve_runtime_config()
        full_messages = self._build_messages(
            messages,
            system_prompt or cfg.get("system_prompt"),
            context,
            runtime_config=cfg,
        )
        candidate_urls = self._candidate_base_urls(str(cfg.get("base_url") or ""))
        if not candidate_urls:
            return "[AI 服务异常] 模型 API Base URL 为空"

        timeout = aiohttp.ClientTimeout(total=120, connect=10)
        last_error = "[AI 服务异常] 未知错误"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for candidate in candidate_urls:
                try:
                    async with session.post(
                        f"{candidate}/chat/completions",
                        headers=self._headers(api_key=str(cfg.get("api_key") or "")),
                        json={
                            "model": cfg["model"],
                            "messages": full_messages,
                            "max_tokens": cfg["max_tokens"],
                            "temperature": cfg["temperature"],
                            "stream": False,
                        },
                    ) as resp:
                        if resp.status >= 400:
                            body = (await resp.text())[:300]
                            last_error = f"[AI 服务异常] HTTP {resp.status} {body}"
                            if self._should_retry_candidate(resp.status):
                                continue
                            logger.error("AI chat request failed: %s", last_error)
                            return last_error
                        data = await resp.json(content_type=None)
                        return str(data["choices"][0]["message"]["content"])
                except Exception as exc:
                    logger.exception("AI chat request failed")
                    last_error = f"[AI 服务异常] {exc}"
        return last_error

    # ------------------------------------------------------------------
    # 增强流式对话：带有函数调用 Agent 能力的持续循环 (Agent Loop)
    # ------------------------------------------------------------------
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system_prompt: str | None = None,
        context: str | None = None,
        runtime_config: dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        # Agent 流的核心逻辑：如果在流的解析截断中发现 function calling 意向，
        # 我们会在幕后直接执行，并将结果再次喂入模型，保持当前 SSE 连接不断。
        
        cfg = runtime_config or self.resolve_runtime_config()
        full_messages = self._build_messages(
            messages,
            system_prompt or cfg.get("system_prompt"),
            context,
            runtime_config=cfg,
        )
        candidate_urls = self._candidate_base_urls(str(cfg.get("base_url") or ""))
        if not candidate_urls:
            yield "data: " + json.dumps({"error": "[Agent 服务异常] 模型 API Base URL 为空"}, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"
            return

        agents = cfg.get("agents") if isinstance(cfg.get("agents"), list) else []
        available_tools = self._tools_for_agents(agents)
        max_loops = 3 # 防止工具调用的死循环
        loop_count = 0

        def _sse_payload(payload: dict[str, Any] | str) -> str:
            if isinstance(payload, str):
                return f"data: {payload}\n\n"
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while loop_count < max_loops:
                loop_count += 1
                payload_json = {
                    "model": cfg["model"],
                    "messages": full_messages,
                    "max_tokens": cfg["max_tokens"],
                    "temperature": cfg["temperature"],
                    "stream": True,
                }
                if available_tools:
                    payload_json["tools"] = available_tools

                try:
                    # 为了在流式中解析 Function Calling，我们需要在内存中拼凑大模型截断输出的 JSON String
                    tool_calls_buffer: dict[int, dict] = {}
                    has_yielded_text = False

                    stream_started = False
                    for candidate in candidate_urls:
                        async with session.post(
                            f"{candidate}/chat/completions",
                            headers=self._headers(api_key=str(cfg.get("api_key") or "")),
                            json=payload_json,
                        ) as resp:
                            if resp.status >= 400:
                                if self._should_retry_candidate(resp.status):
                                    continue
                                body = (await resp.text())[:300]
                                raise RuntimeError(f"HTTP {resp.status}: {body}")
                            stream_started = True
                            while True:
                                raw_line = await resp.content.readline()
                                if not raw_line:
                                    break
                                line = raw_line.decode("utf-8", errors="ignore").strip()
                                if not line or not line.startswith("data: "):
                                    continue
                                raw_data = line[6:]
                                if raw_data.strip() == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(raw_data)
                                    if "choices" not in chunk or not chunk["choices"]:
                                        continue

                                    delta = chunk["choices"][0].get("delta", {})

                                    # 处理正常文本聊天内容输出
                                    content = delta.get("content", "")
                                    if content:
                                        has_yielded_text = True
                                        yield _sse_payload({"content": content})

                                    # 处理流式大模型在拼凑 function 工具调用的块
                                    if "tool_calls" in delta and delta["tool_calls"]:
                                        for tc in delta["tool_calls"]:
                                            idx = tc["index"]
                                            if idx not in tool_calls_buffer:
                                                tool_calls_buffer[idx] = {
                                                    "id": tc.get("id"),
                                                    "type": "function",
                                                    "function": {
                                                        "name": tc.get("function", {}).get("name", ""),
                                                        "arguments": tc.get("function", {}).get("arguments", "")
                                                    }
                                                }
                                            else:
                                                # SSE 分片的 JSON string 参数合并
                                                if tc.get("function", {}).get("name"):
                                                    tool_calls_buffer[idx]["function"]["name"] += tc["function"]["name"]
                                                if tc.get("function", {}).get("arguments"):
                                                    tool_calls_buffer[idx]["function"]["arguments"] += tc["function"]["arguments"]
                                except json.JSONDecodeError:
                                    continue
                        break
                    if not stream_started:
                        raise RuntimeError("模型接口地址无效，请检查 Base URL（可能需要 /v1）。")

                    # 判断本次循环是否产生了工具调用意向
                    if tool_calls_buffer:
                        # 组装完整的 AI Assistant 侧产生的 tool_calls 上下文
                        assembled_calls = []
                        for idx, tc in sorted(tool_calls_buffer.items()):
                            assembled_calls.append({
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"]
                                }
                            })

                        # 将工具调用状态作为 metadata 事件给前端，避免污染助手正文。
                        tool_names = [
                            str(call.get("function", {}).get("name") or "").strip()
                            for call in assembled_calls
                        ]
                        tool_names = [name for name in tool_names if name]
                        yield _sse_payload(
                            {
                                "event": "tool_call_start",
                                "tools": sorted(set(tool_names)),
                            }
                        )
                        
                        full_messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": assembled_calls
                        })

                        # 本地真实去执行每个工具调用，并提交执行结果角色(Tool)给大模型
                        for tc in assembled_calls:
                            validation_error = self._validate_tool_call(
                                tc["function"]["name"],
                                tc["function"]["arguments"],
                                agents,
                            )
                            if validation_error:
                                func_result = validation_error
                            else:
                                func_result = await execute_tool_call(
                                    tc["function"]["name"],
                                    tc["function"]["arguments"],
                                    self.db,
                                    actor_id=actor_id,
                                    api_testing=self.api_testing,
                                    performance_testing=self.performance_testing,
                                    security_testing=self.security_testing,
                                    smithery=self.smithery,
                                )
                            try:
                                self.db.execute(
                                    """
                                    INSERT INTO audit_logs (
                                      id, actor_id, action, target_type, target_id, payload_json, created_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        new_id("aud"),
                                        actor_id,
                                        "ai.tool.call",
                                        "tool",
                                        str(tc["function"]["name"]),
                                        json.dumps(
                                            {
                                                "toolCallId": tc.get("id"),
                                                "arguments": tc["function"]["arguments"],
                                                "resultPreview": str(func_result)[:500],
                                            },
                                            ensure_ascii=False,
                                        ),
                                        utc_now(),
                                    ),
                                )
                            except Exception:
                                # Keep chat flow resilient even if audit insert fails.
                                pass
                            try:
                                parsed_result: dict[str, Any] | None = None
                                status = "succeeded"
                                error_message = None
                                try:
                                    parsed = json.loads(func_result)
                                    if isinstance(parsed, dict):
                                        parsed_result = parsed
                                        if parsed.get("ok") is False:
                                            status = "failed"
                                            err = parsed.get("error")
                                            if isinstance(err, dict):
                                                error_message = str(err.get("message") or "")[:500] or None
                                except Exception:
                                    parsed_result = {"raw": str(func_result)[:2000]}

                                self.db.execute(
                                    """
                                    INSERT INTO ai_operations (
                                      id, operation_type, target_type, target_id, status,
                                      request_payload, response_payload, error_message, created_by,
                                      attempt_count, created_at, updated_at, started_at, finished_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        new_id("aiop"),
                                        f"tool_call:{tc['function']['name']}",
                                        "tool",
                                        str(tc["function"]["name"]),
                                        status,
                                        tc["function"]["arguments"],
                                        json.dumps(parsed_result, ensure_ascii=False) if isinstance(parsed_result, dict) else None,
                                        error_message,
                                        actor_id or "ai-agent",
                                        1,
                                        utc_now(),
                                        utc_now(),
                                        utc_now(),
                                        utc_now(),
                                    ),
                                )
                            except Exception:
                                pass
                            full_messages.append({
                                "tool_call_id": tc["id"],
                                "role": "tool",
                                "name": tc["function"]["name"],
                                "content": func_result
                            })
                        
                        yield _sse_payload({"event": "tool_call_end", "tools": sorted(set(tool_names))})
                        continue
                    else:
                        # 如果没有工具调用或者只是一次纯文本的总结，直接结束外层 loop，完成当前轮对话
                        break

                except Exception as exc:
                    logger.exception("AI chat Agent Stream 发生了网络断连或故障")
                    yield _sse_payload({"error": f"[Agent 服务异常] {exc}"})
                    break

        yield _sse_payload("[DONE]")


    # ------------------------------------------------------------------
    # 便捷方法：AI 辅助需求分析
    # ------------------------------------------------------------------
    async def analyze_requirement(self, requirement_text: str) -> str:
        messages = [
            {
                "role": "user",
                "content": (
                    "请帮我分析以下需求文档，提取出以下内容：\n"
                    "1. 功能性需求\n"
                    "2. 非功能性需求\n"
                    "3. 验收标准\n"
                    "4. 风险点\n"
                    "5. 推荐测试重点\n\n"
                    f"---\n{requirement_text}\n---"
                ),
            }
        ]
        return await self.chat(messages)

    # ------------------------------------------------------------------
    # 便捷方法：AI 辅助生成测试用例
    # ------------------------------------------------------------------
    async def generate_test_cases(
        self,
        context: str,
        *,
        kind: str = "api",
        count: int = 5,
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": (
                    f"根据以下上下文信息，为我生成 {count} 条 {kind.upper()} 测试用例。\n"
                    "每条用例应包含：标题、测试目标、前置条件、操作步骤、预期结果。\n"
                    "使用 markdown 表格输出。\n\n"
                    f"---\n{context}\n---"
                ),
            }
        ]
        return await self.chat(messages)

    # ------------------------------------------------------------------
    # 便捷方法：AI 诊断失败报告
    # ------------------------------------------------------------------
    async def diagnose_failure(
        self,
        error_log: str,
        test_case_info: str = "",
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": (
                    "作为一名高级测试工程师，请分析以下测试失败信息：\n\n"
                    f"**测试用例信息**：\n{test_case_info}\n\n"
                    f"**错误日志**：\n```\n{error_log}\n```\n\n"
                    "请提供：\n"
                    "1. 根因分析 (Root Cause Analysis)\n"
                    "2. 修复建议\n"
                    "3. 预防措施"
                ),
            }
        ]
        return await self.chat(messages)

    # ------------------------------------------------------------------
    # 内部数据处理
    # ------------------------------------------------------------------
    def _headers(self, api_key: str | None = None) -> dict[str, str]:
        key = api_key if api_key is not None else self.api_key
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }

    def _ensure_default_prompt_templates(self) -> None:
        now = utc_now()
        for task_type, item in DEFAULT_TASK_PROMPTS.items():
            try:
                self.db.execute(
                    """
                    INSERT INTO ai_prompt_templates (
                        id, task_type, title, instruction, output_contract, enabled, version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (task_type) DO NOTHING
                    """,
                    (
                        new_id("aipt"),
                        task_type,
                        item["title"],
                        item["instruction"],
                        item.get("output_contract", ""),
                        1,
                        1,
                        now,
                        now,
                    ),
                )
            except Exception:
                logger.exception("failed to seed prompt template: %s", task_type)

    def _ensure_default_agents_hooks_plugins(self) -> None:
        now = utc_now()
        for item in DEFAULT_AGENTS:
            try:
                template = self.db.fetchone(
                    "SELECT id FROM ai_prompt_templates WHERE task_type = ?",
                    (item["task_type"],),
                )
                self.db.execute(
                    """
                    INSERT INTO ai_agents (
                        id, key, title, description, prompt_template_id, allowed_tools_json,
                        enabled, priority, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (
                        new_id("aiag"),
                        item["key"],
                        item["title"],
                        item["description"],
                        template.get("id") if template else None,
                        json.dumps(item.get("allowed_tools") or [], ensure_ascii=False),
                        1,
                        int(item.get("priority") or 100),
                        now,
                        now,
                    ),
                )
                current = self.db.fetchone("SELECT allowed_tools_json FROM ai_agents WHERE key = ?", (item["key"],))
                current_tools = self._json_list(current.get("allowed_tools_json")) if current else []
                merged_tools = list(dict.fromkeys([str(tool) for tool in [*current_tools, *(item.get("allowed_tools") or [])] if str(tool).strip()]))
                if current and set(merged_tools) != {str(tool) for tool in current_tools}:
                    self.db.execute(
                        "UPDATE ai_agents SET allowed_tools_json = ?, updated_at = ? WHERE key = ?",
                        (json.dumps(merged_tools, ensure_ascii=False), now, item["key"]),
                    )
            except Exception:
                logger.exception("failed to seed agent: %s", item.get("key"))
        for item in DEFAULT_HOOKS:
            try:
                self.db.execute(
                    """
                    INSERT INTO ai_hooks (id, key, stage, title, enabled, config_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (
                        new_id("aihk"),
                        item["key"],
                        item["stage"],
                        item["title"],
                        1,
                        json.dumps(item.get("config") or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except Exception:
                logger.exception("failed to seed hook: %s", item.get("key"))
        for item in DEFAULT_PLUGINS:
            try:
                self.db.execute(
                    """
                    INSERT INTO ai_plugins (id, key, title, type, config_json, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (
                        new_id("aiplg"),
                        item["key"],
                        item["title"],
                        item["type"],
                        json.dumps(item.get("config") or {}, ensure_ascii=False),
                        1,
                        now,
                        now,
                    ),
                )
            except Exception:
                logger.exception("failed to seed plugin: %s", item.get("key"))

    def list_agents(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT a.*, t.task_type, t.title AS template_title
            FROM ai_agents a
            LEFT JOIN ai_prompt_templates t ON t.id = a.prompt_template_id
            ORDER BY a.priority ASC, a.key ASC
            """
        )
        return [self._row_to_agent(row) for row in rows]

    def update_agent(self, key: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self._get_agent(key)
        if not current:
            raise KeyError(key)
        enabled = 1 if bool(patch.get("enabled", current.get("enabled", True))) else 0
        priority = int(patch.get("priority", current.get("priority", 100)) or 100)
        allowed_tools = patch.get("allowedTools", current.get("allowedTools", []))
        if not isinstance(allowed_tools, list):
            raise ValueError("allowedTools must be a list")
        self.db.execute(
            """
            UPDATE ai_agents
            SET enabled = ?, priority = ?, allowed_tools_json = ?, updated_at = ?
            WHERE key = ?
            """,
            (enabled, priority, json.dumps(allowed_tools, ensure_ascii=False), utc_now(), key),
        )
        updated = self._get_agent(key)
        if not updated:
            raise KeyError(key)
        return updated

    def list_hooks(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall("SELECT * FROM ai_hooks ORDER BY stage ASC, key ASC")
        return [self._row_to_hook(row) for row in rows]

    def update_hook(self, key: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self._get_hook(key)
        if not current:
            raise KeyError(key)
        enabled = 1 if bool(patch.get("enabled", current.get("enabled", True))) else 0
        config = patch.get("config", current.get("config", {}))
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        self.db.execute(
            "UPDATE ai_hooks SET enabled = ?, config_json = ?, updated_at = ? WHERE key = ?",
            (enabled, json.dumps(config, ensure_ascii=False), utc_now(), key),
        )
        updated = self._get_hook(key)
        if not updated:
            raise KeyError(key)
        return updated

    def list_plugins(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall("SELECT * FROM ai_plugins ORDER BY type ASC, key ASC")
        return [self._row_to_plugin(row) for row in rows]

    def update_plugin(self, key: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self._get_plugin(key)
        if not current:
            raise KeyError(key)
        enabled = 1 if bool(patch.get("enabled", current.get("enabled", True))) else 0
        config = patch.get("config", current.get("config", {}))
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        self.db.execute(
            "UPDATE ai_plugins SET enabled = ?, config_json = ?, updated_at = ? WHERE key = ?",
            (enabled, json.dumps(config, ensure_ascii=False), utc_now(), key),
        )
        updated = self._get_plugin(key)
        if not updated:
            raise KeyError(key)
        return updated

    def _get_agent(self, key: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT a.*, t.task_type, t.title AS template_title
            FROM ai_agents a
            LEFT JOIN ai_prompt_templates t ON t.id = a.prompt_template_id
            WHERE a.key = ?
            """,
            (key,),
        )
        return self._row_to_agent(row) if row else None

    def _get_hook(self, key: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT * FROM ai_hooks WHERE key = ?", (key,))
        return self._row_to_hook(row) if row else None

    def _get_plugin(self, key: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT * FROM ai_plugins WHERE key = ?", (key,))
        return self._row_to_plugin(row) if row else None

    @staticmethod
    def _json_obj(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _json_list(raw: Any) -> list[Any]:
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def _row_to_agent(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "key": row.get("key"),
            "title": row.get("title"),
            "description": row.get("description") or "",
            "promptTemplateId": row.get("prompt_template_id"),
            "taskType": row.get("task_type"),
            "templateTitle": row.get("template_title"),
            "allowedTools": [str(item) for item in self._json_list(row.get("allowed_tools_json"))],
            "enabled": bool(row.get("enabled")),
            "priority": int(row.get("priority") or 100),
            "createdAt": row.get("created_at"),
            "updatedAt": row.get("updated_at"),
        }

    def _row_to_hook(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "key": row.get("key"),
            "stage": row.get("stage"),
            "title": row.get("title"),
            "enabled": bool(row.get("enabled")),
            "config": self._json_obj(row.get("config_json")),
            "createdAt": row.get("created_at"),
            "updatedAt": row.get("updated_at"),
        }

    def _row_to_plugin(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "key": row.get("key"),
            "title": row.get("title"),
            "type": row.get("type"),
            "enabled": bool(row.get("enabled")),
            "config": self._json_obj(row.get("config_json")),
            "createdAt": row.get("created_at"),
            "updatedAt": row.get("updated_at"),
        }

    def _enabled_agents_by_key(self) -> dict[str, dict[str, Any]]:
        return {str(item["key"]): item for item in self.list_agents() if item.get("enabled")}

    def _select_agents(self, task_type: str, messages: list[dict[str, Any]], context: str | None = None) -> list[dict[str, Any]]:
        enabled = self._enabled_agents_by_key()
        if self._is_smalltalk(messages):
            return [
                enabled.get("orchestrator")
                or {"key": "orchestrator", "title": "测试编排 Agent", "description": "", "allowedTools": []}
            ]
        keys = list(TASK_AGENT_MAP.get(task_type) or ["orchestrator"])
        text = "\n".join(str(item.get("content") or "") for item in messages[-6:]).lower()
        if task_type == "api_testing" and any(word in text for word in ("失败", "报错", "500", "timeout", "超时")):
            keys = ["failure_agent", "api_agent"]
        if task_type == "security_testing" and any(word in text for word in ("性能", "压测", "tps", "p95")):
            keys = ["security_agent", "performance_agent"]
        if task_type == "performance_testing" and any(word in text for word in ("安全", "漏洞", "扫描")):
            keys = ["security_agent", "performance_agent"]
        selected: list[dict[str, Any]] = []
        for key in keys[:3]:
            agent = enabled.get(key)
            if agent:
                selected.append(agent)
        if not selected:
            selected = [enabled.get("orchestrator") or {"key": "orchestrator", "title": "测试编排 Agent", "description": "", "allowedTools": []}]
        return selected[:3]

    def _limit_context(self, context: str | None) -> str | None:
        if not context:
            return None
        limit = 8000
        hook = self._get_hook("context_limit_hook")
        if hook and hook.get("enabled"):
            cfg = hook.get("config") if isinstance(hook.get("config"), dict) else {}
            try:
                limit = int(cfg.get("maxContextChars") or limit)
            except Exception:
                limit = 8000
        text = str(context).strip()
        return text[: max(500, min(limit, 20000))]

    def _allowed_tools_for_agents(self, agents: list[dict[str, Any]] | None) -> set[str]:
        return set(self._allowed_tool_names_for_agents(agents))

    def _allowed_tool_names_for_agents(self, agents: list[dict[str, Any]] | None) -> list[str]:
        if not agents:
            return [str(item.get("function", {}).get("name")) for item in SYSTEM_TOOLS if item.get("function")]
        allowed: list[str] = []
        for agent in agents:
            for tool_name in agent.get("allowedTools") or agent.get("allowed_tools") or []:
                if str(tool_name).strip():
                    allowed.append(str(tool_name).strip())
        if "orchestrator" in {str(agent.get("key")) for agent in agents}:
            allowed.extend(["invoke_mcp_tool", "orchestrate_testing_workflow"])
        return list(dict.fromkeys(allowed))

    def _tools_for_agents(self, agents: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        plugin = self._get_plugin("platform-testing-tools")
        if plugin and not plugin.get("enabled"):
            return []
        allowed_names = self._allowed_tool_names_for_agents(agents)
        allowed = set(allowed_names)
        if not allowed:
            return []
        tools_by_name = {
            str(tool.get("function", {}).get("name") or ""): tool
            for tool in SYSTEM_TOOLS
            if str(tool.get("function", {}).get("name") or "") in allowed
        }
        return [tools_by_name[name] for name in allowed_names if name in tools_by_name]

    def _tool_manifest_for_agents(self, agents: list[dict[str, Any]] | None) -> list[dict[str, str]]:
        manifest: list[dict[str, str]] = []
        for tool in self._tools_for_agents(agents):
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            parameters = function.get("parameters") if isinstance(function.get("parameters"), dict) else {}
            properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
            required = parameters.get("required") if isinstance(parameters.get("required"), list) else []
            arg_names = [str(key) for key in properties.keys() if str(key).strip()]
            manifest.append(
                {
                    "name": name,
                    "description": str(function.get("description") or "").strip(),
                    "args": ", ".join(arg_names[:36]),
                    "required": ", ".join(str(item) for item in required if str(item).strip()),
                }
            )
        return manifest

    def _mcp_manifest_from_config(self, runtime_config: dict[str, Any]) -> list[dict[str, Any]]:
        plugin = self._get_plugin("smithery-mcp")
        if plugin and not plugin.get("enabled"):
            return []
        servers = runtime_config.get("mcp_servers")
        if not isinstance(servers, list):
            return []
        manifest: list[dict[str, Any]] = []
        for server in servers[:10]:
            if not isinstance(server, dict):
                continue
            connection_id = str(
                server.get("connectionId")
                or server.get("connection_id")
                or server.get("id")
                or server.get("name")
                or server.get("server")
                or ""
            ).strip()
            server_name = str(server.get("name") or server.get("server") or connection_id).strip()
            if not connection_id and not server_name:
                continue
            tools_raw = server.get("tools") if isinstance(server.get("tools"), list) else []
            tools = [str(tool).strip() for tool in tools_raw if str(tool).strip()]
            hint_key = (connection_id or server_name).lower()
            if not tools:
                tools = [str(tool) for tool in MCP_NPM_PACKAGE_HINTS.get(hint_key, {}).get("tools", [])]
            manifest.append(
                {
                    "connectionId": connection_id or server_name,
                    "name": server_name or connection_id,
                    "status": str(server.get("status") or "").strip(),
                    "tools": tools[:8],
                }
            )
        return manifest

    def _validate_tool_call(self, tool_name: str, arguments_json: str, agents: list[dict[str, Any]] | None) -> str | None:
        permission_hook = self._get_hook("tool_permission_hook")
        if not permission_hook or permission_hook.get("enabled"):
            if tool_name not in self._allowed_tools_for_agents(agents):
                return json.dumps(
                    {"ok": False, "error": {"code": "TOOL_NOT_ALLOWED", "message": f"当前 Agent 不允许调用工具 {tool_name}"}},
                    ensure_ascii=False,
                )
        destructive_hook = self._get_hook("destructive_action_hook")
        if destructive_hook and destructive_hook.get("enabled"):
            cfg = destructive_hook.get("config") if isinstance(destructive_hook.get("config"), dict) else {}
            markers = [str(item).lower() for item in (cfg.get("destructiveTools") or [])]
            raw = f"{tool_name} {arguments_json}".lower()
            if any(marker and marker in raw for marker in markers) and "confirm" not in raw:
                return json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "CONFIRM_REQUIRED",
                            "message": "该操作可能修改或删除数据，请用户明确确认后再执行。",
                        },
                    },
                    ensure_ascii=False,
                )
        return None

    def prepare_chat_turn(
        self,
        *,
        user_id: str,
        messages: list[dict[str, Any]],
        session_id: str | None = None,
        project_id: str | None = None,
        page: str | None = None,
        context: str | None = None,
        rag_context: str | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        latest_user = next(
            (msg for msg in reversed(messages) if str(msg.get("role") or "") == "user"),
            None,
        )
        title = str((latest_user or {}).get("content") or "AI 对话").strip()[:80] or "AI 对话"
        session = self.ensure_chat_session(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            title=title,
        )
        task_type = self._detect_task_type(messages, "\n\n".join([part for part in [context, rag_context] if part]))
        agents = self._select_agents(task_type, messages, context)
        is_smalltalk = self._is_smalltalk(messages)
        recent_messages = [] if is_smalltalk else self.list_chat_messages(
            user_id=user_id,
            session_id=str(session.get("id") or ""),
            limit=12,
        )
        history_messages = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in recent_messages
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        incoming = list(messages)
        if history_messages and incoming:
            # Keep current request authoritative, but provide recent persisted turns before it.
            incoming = [*history_messages, *incoming]
        merged_context = None if is_smalltalk else "\n\n".join(
            [part for part in [rag_context, context] if isinstance(part, str) and part.strip()]
        ) or None
        cfg = dict(runtime_config or {})
        tool_manifest = [] if is_smalltalk else self._tool_manifest_for_agents(agents)
        mcp_manifest = [] if is_smalltalk else self._mcp_manifest_from_config(cfg)
        cfg.update(
            {
                "task_type": task_type,
                "agents": agents,
                "agents_used": [str(agent.get("key")) for agent in agents],
                "session_summary": str(session.get("summary") or ""),
                "page": page,
                "tool_manifest": tool_manifest,
                "mcp_manifest": mcp_manifest,
            }
        )
        return {
            "session": session,
            "sessionId": session.get("id"),
            "taskType": task_type,
            "agents": agents,
            "agentsUsed": [str(agent.get("key")) for agent in agents],
            "toolsAvailable": [item["name"] for item in tool_manifest],
            "mcpAvailable": mcp_manifest,
            "messages": incoming[-24:],
            "context": merged_context,
            "runtimeConfig": cfg,
        }

    def maybe_summarize_session(self, *, session_id: str, user_id: str) -> dict[str, Any] | None:
        hook = self._get_hook("session_summary_hook")
        if hook and not hook.get("enabled"):
            return None
        cfg = hook.get("config") if hook and isinstance(hook.get("config"), dict) else {}
        try:
            threshold = int(cfg.get("messageThreshold") or 30)
        except Exception:
            threshold = 30
        session = self.get_chat_session(session_id=session_id, user_id=user_id)
        if not session:
            return None
        if int(session.get("messageCount") or 0) < threshold:
            return None
        return self.summarize_chat_session(session_id=session_id, user_id=user_id)

    def _detect_task_type(self, messages: list[dict[str, Any]], context: str | None = None) -> str:
        if self._is_smalltalk(messages):
            return "general"
        text_parts: list[str] = []
        for item in messages[-6:]:
            if str(item.get("role") or "") == "user":
                text_parts.append(str(item.get("content") or ""))
        if context:
            text_parts.append(str(context))
        text = "\n".join(text_parts).lower()

        keyword_map: list[tuple[str, tuple[str, ...]]] = [
            ("workflow_bootstrap", ("全流程", "从零", "一键", "一次性", "批量推进", "搭建项目", "项目需求用例", "需求用例接口", "示范接口", "模范接口", "样例接口", "full_e2e_bootstrap")),
            ("failure_diagnosis", ("报错", "错误", "失败", "异常", "500", "404", "traceback", "not found", "timeout", "超时", "断言失败")),
            ("security_testing", ("安全", "漏洞", "越权", "鉴权", "注入", "xss", "csrf", "cors", "ssrf", "扫描", "敏感信息")),
            ("performance_testing", ("压测", "性能", "并发", "tps", "p95", "p99", "吞吐", "响应时间", "瓶颈", "sla")),
            ("api_testing", ("接口", "api", "headers", "body", "query", "参数", "断言", "请求", "postman", "curl")),
            ("requirement_analysis", ("需求", "验收", "业务规则", "prd", "用户故事", "场景")),
            ("case_generation", ("用例", "测试点", "测试步骤", "覆盖", "边界值", "生成测试", "补用例")),
            ("reporting", ("报告", "总结", "质量", "通过率", "趋势", "风险清单", "上线")),
        ]
        for task_type, keywords in keyword_map:
            if any(keyword in text for keyword in keywords):
                return task_type
        return "general"

    def _load_prompt_template(self, task_type: str) -> dict[str, str]:
        fallback = DEFAULT_TASK_PROMPTS.get(task_type) or DEFAULT_TASK_PROMPTS["general"]
        try:
            row = self.db.fetchone(
                """
                SELECT task_type, title, instruction, output_contract
                FROM ai_prompt_templates
                WHERE task_type = ? AND enabled = 1
                """,
                (task_type,),
            )
        except Exception:
            row = None
        if not row:
            return {
                "task_type": task_type,
                "title": fallback["title"],
                "instruction": fallback["instruction"],
                "output_contract": self._sanitize_template_contract(task_type, fallback.get("output_contract", "")),
            }
        return {
            "task_type": str(row.get("task_type") or task_type),
            "title": str(row.get("title") or fallback["title"]),
            "instruction": str(row.get("instruction") or fallback["instruction"]),
            "output_contract": self._sanitize_template_contract(
                task_type,
                str(row.get("output_contract") or fallback.get("output_contract", "")),
            ),
        }

    def list_prompt_templates(self) -> list[dict[str, Any]]:
        try:
            rows = self.db.fetchall(
                """
                SELECT id, task_type, title, instruction, output_contract, enabled, version, created_at, updated_at
                FROM ai_prompt_templates
                ORDER BY task_type ASC
                """
            )
        except Exception:
            rows = []
        if not rows:
            return [
                {
                    "taskType": task_type,
                    "title": item["title"],
                    "instruction": item["instruction"],
                    "outputContract": item.get("output_contract", ""),
                    "enabled": True,
                    "version": 1,
                }
                for task_type, item in DEFAULT_TASK_PROMPTS.items()
            ]
        return [
            {
                "id": row.get("id"),
                "taskType": row.get("task_type"),
                "title": row.get("title"),
                "instruction": row.get("instruction"),
                "outputContract": row.get("output_contract"),
                "enabled": bool(row.get("enabled")),
                "version": int(row.get("version") or 1),
                "createdAt": row.get("created_at"),
                "updatedAt": row.get("updated_at"),
            }
            for row in rows
        ]

    def update_prompt_template(self, task_type: str, patch: dict[str, Any]) -> dict[str, Any]:
        normalized = str(task_type or "").strip()
        if not normalized:
            raise ValueError("task_type is required")
        current = self._load_prompt_template(normalized)
        title = str(patch.get("title") or current["title"]).strip()
        instruction = str(patch.get("instruction") or current["instruction"]).strip()
        output_contract = str(
            patch.get("outputContract")
            or patch.get("output_contract")
            or current.get("output_contract")
            or ""
        ).strip()
        enabled = 1 if bool(patch.get("enabled", True)) else 0
        if not title or not instruction:
            raise ValueError("title and instruction are required")
        now = utc_now()
        self.db.execute(
            """
            INSERT INTO ai_prompt_templates (
                id, task_type, title, instruction, output_contract, enabled, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (task_type) DO UPDATE SET
                title = excluded.title,
                instruction = excluded.instruction,
                output_contract = excluded.output_contract,
                enabled = excluded.enabled,
                version = ai_prompt_templates.version + 1,
                updated_at = excluded.updated_at
            """,
            (
                new_id("aipt"),
                normalized,
                title,
                instruction,
                output_contract,
                enabled,
                1,
                now,
                now,
            ),
        )
        return self._load_prompt_template(normalized)

    def _compose_system_prompt(
        self,
        *,
        messages: list[dict[str, Any]],
        system_prompt: str | None,
        context: str | None,
        runtime_config: dict[str, Any] | None,
    ) -> str:
        cfg = runtime_config or {}
        custom_system = str(system_prompt or "").strip()
        base_prompt = "\n\n".join(part for part in [CORE_SYSTEM_PROMPT, custom_system] if part)
        task_type = str(cfg.get("task_type") or self._detect_task_type(messages, context))
        task_prompt = self._load_prompt_template(task_type)
        agents = cfg.get("agents") if isinstance(cfg.get("agents"), list) else self._select_agents(task_type, messages, context)
        agents_used = [str(agent.get("key") or "") for agent in agents if str(agent.get("key") or "")]
        session_summary = str(cfg.get("session_summary") or "").strip()
        is_smalltalk = self._is_smalltalk(messages)

        sections = [
            base_prompt,
            (
                "### 当前 Agent 协作\n"
                f"- orchestrator: 负责路由、取舍和最终合并\n"
                f"- agents_used: {', '.join(agents_used) if agents_used else 'orchestrator'}\n"
                + "\n".join(
                    [
                        f"- {agent.get('key')}: {agent.get('title')}；{agent.get('description')}"
                        for agent in agents
                    ]
                )
            ),
            (
                "### 当前任务路由\n"
                f"- task_type: {task_prompt['task_type']}\n"
                f"- task_name: {task_prompt['title']}\n"
                f"- instruction: {task_prompt['instruction']}\n"
                f"- output_contract: {task_prompt['output_contract']}"
            ),
        ]

        if is_smalltalk:
            sections.append("### 轻量寒暄模式\n只回复一句自然中文，例如“在，我在。把问题发我就行。”不要使用任何 Markdown 小标题、列表、分级说明或验收文字。")

        custom_rules = cfg.get("custom_rules") if isinstance(cfg.get("custom_rules"), list) else []
        if custom_rules:
            lines = ["### 用户偏好规则（低于系统边界，高于默认风格）"]
            lines.extend([f"- {str(rule)}" for rule in custom_rules[:12] if str(rule).strip()])
            if len(lines) > 1:
                sections.append("\n".join(lines))

        tool_manifest = [] if is_smalltalk else (
            cfg.get("tool_manifest") if isinstance(cfg.get("tool_manifest"), list) else self._tool_manifest_for_agents(agents)
        )
        if tool_manifest:
            tool_lines = [
                "### 当前可调用平台工具（已按 Agent 权限过滤）",
                "当用户要求真实创建、修改、执行、扫描、压测、诊断或汇总时，优先调用这些工具；证据不足时先查询或预检查。",
            ]
            for tool in tool_manifest[:18]:
                name = str(tool.get("name") or "").strip()
                description = str(tool.get("description") or "").strip()
                args = str(tool.get("args") or "").strip()
                required = str(tool.get("required") or "").strip()
                if name:
                    line = f"- `{name}`: {description or '平台内部工具'}"
                    if required:
                        line += f"；必填参数: {required}"
                    if args:
                        line += f"；可用参数: {args}"
                    tool_lines.append(line)
            sections.append("\n".join(tool_lines))

        mcp_manifest = [] if is_smalltalk else (
            cfg.get("mcp_manifest") if isinstance(cfg.get("mcp_manifest"), list) else self._mcp_manifest_from_config(cfg)
        )
        if mcp_manifest:
            mcp_lines = [
                "### 当前可调用 MCP 能力",
                "需要外部能力时，通过 `invoke_mcp_tool(connection_id, tool_name, payload)` 调用；只调用下列已配置连接。",
            ]
            for server in mcp_manifest[:10]:
                connection_id = str(server.get("connectionId") or "").strip()
                name = str(server.get("name") or connection_id).strip()
                status = str(server.get("status") or "").strip()
                tools = server.get("tools") if isinstance(server.get("tools"), list) else []
                tool_names = [str(tool).strip() for tool in tools if str(tool).strip()][:8]
                if not connection_id:
                    continue
                line = f"- `{connection_id}`"
                if name and name != connection_id:
                    line += f" ({name})"
                if status:
                    line += f" [{status}]"
                if tool_names:
                    line += f": {', '.join(tool_names)}"
                mcp_lines.append(line)
            if len(mcp_lines) > 2:
                sections.append("\n".join(mcp_lines))

        skill_search_paths = cfg.get("skill_search_paths") if isinstance(cfg.get("skill_search_paths"), list) else []
        if skill_search_paths:
            lines = ["### 用户导入的能力线索"]
            lines.extend([f"- {str(item)}" for item in skill_search_paths[:10] if str(item).strip()])
            if len(lines) > 1:
                sections.append("\n".join(lines))

        enabled_plugins = [item for item in self.list_plugins() if item.get("enabled")]
        if enabled_plugins:
            sections.append(
                "### 已启用插件\n"
                + "\n".join(
                    [
                        f"- {item.get('key')} ({item.get('type')}): {item.get('title')}"
                        for item in enabled_plugins[:8]
                    ]
                )
            )

        if session_summary:
            sections.append(f"### 会话压缩摘要\n{session_summary[:3000]}")

        if context and str(context).strip():
            limited_context = self._limit_context(context) or ""
            sections.append(f"### 当前界面与测试对象上下文\n{limited_context}")

        return "\n\n".join(section for section in sections if section.strip())

    def _build_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None,
        context: str | None,
        runtime_config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        sys_text = self._compose_system_prompt(
            messages=messages,
            system_prompt=system_prompt,
            context=context,
            runtime_config=runtime_config,
        )
        result.append({"role": "system", "content": sys_text})
        
        # 兼容传过来没有 content 的情况（比如只是一些空状态）
        for m in messages:
            if m.get("role"):
                result.append(m)
        return result
