# API 兼容性测试工具（精简脱敏版）

本目录包含 30 个 OpenAI Chat Completions 兼容性测试用例：26 个来自原始套件，另加入 4 个脱敏后的 Token 计数用例，适合提供给接口服务方进行问题复现与整改。

测试内容全部采用通用合成数据，不包含任何真实业务实体、内部系统、真实域名、真实请求或真实凭据。

## 文件

- `api_compat_probe.py`：可直接运行的测试脚本，仅依赖 Python 3.8+ 标准库。
- `cases.json`：默认加载的 30 条测试用例与参考判定。
- `TEST_CASES.md`：30 个测试用例的目的、预期结果和问题说明。

## 快速使用

先执行离线自检：

```bash
python3 api_compat_probe.py --self-test
```

查看 30 个用例：

```bash
python3 api_compat_probe.py --list-cases
```

运行全部用例：

```bash
python3 api_compat_probe.py \
  --url https://api.example.com/v1 \
  --key YOUR_API_KEY \
  --model YOUR_MODEL_NAME
```

也可以通过环境变量提供密钥，避免密钥出现在命令历史中：

```bash
export API_COMPAT_KEY='YOUR_API_KEY'
python3 api_compat_probe.py \
  --url https://api.example.com/v1 \
  --model YOUR_MODEL_NAME
```

只运行指定用例：

```bash
python3 api_compat_probe.py \
  --url https://api.example.com/v1 \
  --model YOUR_MODEL_NAME \
  --case control.json --case conf.tool_required --case tc.parallel4
```

仅预览将要运行的用例，不发送请求：

```bash
python3 api_compat_probe.py --dry-run --model YOUR_MODEL_NAME
```

运行 30 个用例（默认每例一次，共 30 次调用）：

```bash
python3 api_compat_probe.py \
  --url https://api.example.com/v1 \
  --model YOUR_MODEL_NAME \
  --timeout 1200
```

## 输出结果

每次运行会生成一个 `api-compat-report-<时间>` 目录，其中包括：

- `report.json`：结构化汇总，记录每个用例是否通过以及问题原因。
- `wire/<用例ID>.json.gz`：对应请求与响应，便于复现。Authorization 不会写入文件。

退出码：

- `0`：全部通过。
- `1`：至少一个用例未通过或请求失败。
- `2`：命令行参数错误。

## 使用边界

- 本套件包含 30 个用例定义，默认共发送 30 次请求。
- 其中 4 条 Token 计数用例覆盖短文本、长文本、短工具调用和长工具调用；`prompt_tokens` 相对参考值偏差不超过 3% 即通过。
- 不包含并发压测、故障切换或后端识别。
- 工具调用只是检查模型返回的结构，脚本不会实际执行工具，也不会写入接口侧文件。
- `control.badreq` 和 `conf.tool_nonexistent` 是异常请求测试，预期返回 400；正确拒绝即视为通过。
- 不同兼容实现可能不支持全部可选参数。测试结果应结合服务方声明的兼容范围判断。
- “未通过”只用于明确的协议或结构问题；有明确数量要求的工具调用会严格判定，可能受模型随机性影响的文本偏差标记为“待确认”。
- `--insecure` 会关闭 TLS 证书校验，仅应在受控测试环境使用。

## 建议提供给接口服务方的材料

优先提供：

1. `report.json` 中失败用例的编号和问题描述；
2. 对应的 `wire/<用例ID>.json.gz`；
3. `TEST_CASES.md` 中该用例的预期结果。

请在对外发送报告前再次确认响应正文中没有业务数据。建议使用专门的测试账号、测试模型和测试环境运行。
