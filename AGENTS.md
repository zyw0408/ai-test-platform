# AI 接入测试平台 (AI Gateway & Compatibility Test Platform)

大模型 API 接口兼容性、准入测试、流式 SSE 规范与长文本/并发性能自动化测试平台。

## Project
- **语言与栈**：Python 3 (纯标准库开发为主，无需额外第三方包依赖即可跑基础 Probe/Bench)；部分辅助脚本使用 Node.js。
- **环境要求**：Python 3.10+，无需必须构建，直接通过 CLI 运行脚本。
- **核心入口**：
  - 兼容性测试套件：`compatibility_suite/api_compat_probe.py`
  - 压测与长工具回放：`replay_bench/kimi_k3_sep2_replay_bench.py`

## Commands
- **兼容性测试自测 (无需网络)**：`python3 compatibility_suite/api_compat_probe.py --self-test`
- **全量兼容性测试**：`python3 compatibility_suite/api_compat_probe.py --url <GATEWAY_URL> --key "$API_KEY" --model <MODEL_NAME>`
- **长工具/高并发回放压测**：`python3 replay_bench/kimi_k3_sep2_replay_bench.py inputs/issue1_error_case1.json --bust-cache --force-long-tool-args --concurrency 3 --repeat 10`
- **思考块泄漏排查**：`python3 check_thinking_blocks.py`

## Architecture
- `compatibility_suite/`：OpenAI 兼容性 30 例探针脚本，自动分析 HTTP 状态码、SSE 数据流、Thinking 块与 Tool Calls 规范。
- `replay_bench/`：针对复杂入参、长工具 arguments (32k+)、高并发耗时与 EOS 规范的复现与压测套件。
- `inputs/`：各类脱敏请求 payload 样本，供 replay_bench 直接调用。
- `TokenHub-Vendor-Verifier-main/`：基于 CLI 的 TokenHub 供应商验证评测套件。
- 根目录脚本 (`long_output_test*.py`, `check_thinking_blocks.py` 等)：针对特定缺陷（如空 finish_reason、思考块泄漏、超大 Token 截断）的离散诊断工具。

## Conventions
- **安全第一**：切勿将真实 API Key 硬编码入脚本、命令或生成的报告文件中，必须通过环境变量或测试环境配置文件注入。
- **测试报告规范**：生成测试报告时，必须保留原始 SSE 报文与 HTTP 响应状态码，确保异常结论有据可查。
- **修改原则**：保持 `compatibility_suite` 和 `replay_bench` 独立且使用 Python 标准库，避免引入繁重的非必备外源依赖。

## Notes
- 今后如有新的准入测试场景或排查工具，在此补充记录。
