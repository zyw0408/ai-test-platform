# API 兼容性精选 30 例

本文件包含 26 个原始测试用例和 4 个新增 Token 计数用例。新增请求仅使用通用合成数据；模型名由运行参数传入。每个用例执行一次，合计 30 次调用。

| 序号 | 用例 ID | 类别 | 测试目的 |
|---:|---|---|---|
| 1 | `control.json` | 对照组 | 基础非流式请求 |
| 2 | `control.stream` | 对照组 | 基础流式请求 |
| 3 | `control.badreq` | 对照组 | 空消息负向请求 |
| 4 | `tokens.identical` | Token | 固定请求的 Token 计数 |
| 5 | `tokens.ids_present` | Token | 保留历史工具调用 ID |
| 6 | `tokens.ids_stripped` | Token | 替换历史工具调用 ID 后的对照 |
| 7 | `tokens.maxtok1` | Token | `max_tokens=1` 截断 |
| 8 | `tokens.maxcompletion_alias` | Token | `max_completion_tokens=1` |
| 9 | `tokens.truncate_toolcall` | Token | 工具参数截断时的结束状态 |
| 10 | `tokens.stop` | Token | `stop` 参数处理 |
| 11 | `tokens.feedback.short_plain` | Token | 短文本 Token 计数基准 |
| 12 | `tokens.feedback.long_plain` | Token | 长文本 Token 计数基准 |
| 13 | `tokens.feedback.short_tool` | Token | 短工具请求 Token 计数与参数校验 |
| 14 | `tokens.feedback.long_tool` | Token | 长工具请求 Token 计数与汇总参数校验 |
| 15 | `conf.seed` | 参数 | `seed=42` |
| 16 | `conf.usage_on` | 流式 | 请求流式 usage |
| 17 | `conf.usage_empty_opts` | 流式 | 空 `stream_options` |
| 18 | `conf.tool_absent` | 工具 | 提供工具但不传 `tool_choice` |
| 19 | `conf.tool_auto` | 工具 | `tool_choice=auto` |
| 20 | `conf.tool_required` | 工具 | `tool_choice=required` |
| 21 | `conf.tool_nonexistent` | 工具 | 指定未声明工具的负向请求 |
| 22 | `conf.tool_empty_list` | 工具 | 空工具列表 |
| 23 | `conf.tool_parallel_off` | 工具 | 关闭并行工具调用 |
| 24 | `conf.rf_json_object` | 结构化输出 | JSON object 输出 |
| 25 | `conf.rf_json_schema` | 结构化输出 | JSON schema 输出 |
| 26 | `conf.two_system` | 消息 | 连续两个 system 消息 |
| 27 | `tc.single` | 工具 | 单个流式工具调用 |
| 28 | `tc.parallel4` | 工具 | 四个并行工具调用 |
| 29 | `tc.echo_args` | 工具 | 工具参数逐字回传 |
| 30 | `tc.id_history` | 工具 | 长历史中的工具调用 ID 续接 |

## Token 用例判定要求

- 4 条 Token 用例的参考 `prompt_tokens` 依次为 `126 / 14075 / 214 / 5886`。
- 实际 `prompt_tokens` 与对应参考值的相对偏差不超过 3% 即通过。
- 工具用例还必须返回指定工具、合法 JSON 参数及正确的计算结果。
