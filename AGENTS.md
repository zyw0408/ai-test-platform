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
- **报告归档与命名规范（强制执行）**：
  1. **统一存放目录**：所有新生成的 HTML/数据报告统一存放在 `reports/` 目录下，严禁与根目录测试脚本混放。
  2. **标准化命名格式**：文件名必须严格按照 `<渠道名或纯数字渠道号>_<测试项>.html` 规范命名（多渠道时使用 `channel_<ID1>_<ID2>_<测试项>.html`）。
  3. **严禁别称修饰**：严禁在文件名中添加如“新疆渠道”、“精简版”、“完美版”、“最终版”、“full_rendered”等主观或别称字眼，只保留纯粹的渠道标识与测试项核心描述（如 `channel_335_1h_cache_read_write.html`、`channel_332_327_338_364_1h_cache_audit.html`）。
- **修改原则**：保持 `compatibility_suite` 和 `replay_bench` 独立且使用 Python 标准库，避免引入繁重的非必备外源依赖。

## Notes
- 今后如有新的准入测试场景或排查工具，在此补充记录。
- **Kimi-k3 官方原厂协议基准样本 (已存入记忆库)**：
  - 以 **渠道 166 (Moonshot 官方原厂 `api.moonshot.cn`)** 为基准样本源。
  - 完整记录了三大协议（Anthropic Messages / OpenAI Responses / OpenAI Chat）的流式与非流式实测抓包报文。
  - 新渠道进入时，直接与本套官方基准样本进行协议字段与结构对齐比对即可，不附加主观判定。
  - 详细基准样本存档于 Obsidian 知识库：`Kimi-k3-Official-Protocol-Standard.md`。
- **办公模式核心业务站点与服务导航 (已存入记忆库)**：
  - **国内网站 (控制台)**：`http://www.pinducloud.com.cn/console/channel`
  - **国外网站**：`https://pinducloud.cc/`
  - **超管后台**：`http://124.220.201.99:8080/`
  - **杭州联通平台**：`https://ai-hz.com.cn/`
  - **嘉兴电信平台**：`http://115.228.159.110:18080/`
  - **国内视频站点**：`http://video.pinducloud.com.cn`
  - 同步存档于 Obsidian 知识库：`agent/办公模式核心站点与系统导航.md` 及 `agent/DSH_办公模式系统架构与协同体系.md`。


