---
name: test-subagent-execution
description: 测试子代理执行规范与操作指南。用于大模型API接口兼容性测试、探针诊断、高并发压测、长工具回放及思考块泄漏排查。
---

# 测试子代理执行指南 (Test Subagent Execution Guide)

测试子代理专职执行大模型接口评测、兼容性准入检查、高并发性能压测与缺陷复现。

## 一、平台核心测试套件概览

本项目平台基于 Python 3 标准库构建，核心入口如下：

1. **兼容性测试探针 (`compatibility_suite/api_compat_probe.py`)**：
   - 快速自测（离线模拟，无需网络）：
     ```bash
     python3 compatibility_suite/api_compat_probe.py --self-test
     ```
   - 全量接口兼容性测试（涵盖 30 例探针：HTTP 状态码、SSE 数据流、Thinking 思考块规范、Tool Calls 规范等）：
     ```bash
     python3 compatibility_suite/api_compat_probe.py --url "$GATEWAY_URL" --key "$API_KEY" --model "$MODEL_NAME"
     ```

2. **高并发与长工具调用压测 (`replay_bench/kimi_k3_sep2_replay_bench.py`)**：
   - 针对超长工具 arguments (32k+)、并发延迟与 EOS 规范进行回放：
     ```bash
     python3 replay_bench/kimi_k3_sep2_replay_bench.py inputs/issue1_error_case1.json --bust-cache --force-long-tool-args --concurrency 3 --repeat 10
     ```

3. **思考块泄漏排查 (`check_thinking_blocks.py`)**：
   - 快速排查 SSE 数据流中是否有 `<thought>` 或 reasoning_content 泄漏。

4. **TokenHub 供应商验证套件 (`TokenHub-Vendor-Verifier-main/`)**：
   - 针对 TokenHub 渠道供应商的接口协议及质量进行自动化打分与验证。

---

## 二、测试规范与铁律

1. **安全与密钥规范**：
   - **绝对禁止**将真实 API Key、Token 密码写入任何脚本、提交记录或生成的报告文本中。
   - 所有密钥统一通过环境变量（如 `$env:API_KEY` 或 `$API_KEY`）或脱敏配置文件进行注入。

2. **报告真实性与证据链**：
   - 任何异常报错（如 HTTP 4xx/5xx、SSE chunk 畸变、字段缺失），必须保留原始报文片段与状态码。
   - 给出清晰的统计数据：总测试用例数、通过率、P50/P90/P99 响应延迟、失败原因分类。

3. **执行结果向主模型反馈格式**：
   - 测试执行完毕后，向主模型返回标准结构：
     - **测试目标与配置**：被测模型、网关、并发数、轮次。
     - **指标概览**：Success Rate、Average Latency、Throughput。
     - **发现问题清单**：协议偏离点、违规状态码、畸变 Chunk。
     - **诊断建议**：直接针对被测网关或模型适配层提出修复建议。
