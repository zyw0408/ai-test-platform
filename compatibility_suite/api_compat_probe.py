#!/usr/bin/env python3
"""精简、脱敏的 OpenAI Chat Completions 兼容性测试工具。

仅使用 Python 标准库。测试数据均为通用合成数据，不包含任何真实业务实体、
内部系统、真实域名或真实凭据。
"""

import argparse
import gzip
import json
import os
import random
import re
import signal
import ssl
import string
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


VERSION = "1.1.0"


TOOL_WRITE = {
    "type": "function",
    "function": {
        "name": "write",
        "description": "Write a file.",
        "parameters": {"type": "object",
                       "properties": {"file_path": {"type": "string"},
                                      "content": {"type": "string"}},
                       "required": ["file_path", "content"]},
    },
}

TOOL_READ = {
    "type": "function",
    "function": {
        "name": "Read",
        "description": "Read a file from disk.",
        "parameters": {"type": "object",
                       "properties": {"file_path": {"type": "string"}},
                       "required": ["file_path"]},
    },
}

TOOL_WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather for one city.",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"},
                                      "unit": {"type": "string", "enum": ["c", "f"]}},
                       "required": ["city"]},
    },
}

_LOREM = ("The parties acknowledge that the foregoing provisions shall survive termination "
          "and that no waiver of any breach constitutes a waiver of any other breach. ")


def filler(approx_tokens_wanted: int, seed: int = 0) -> str:
    rnd = random.Random(seed)
    words = _LOREM.split()
    output: List[str] = []
    while len(" ".join(output)) < approx_tokens_wanted * 4:
        output.append(words[rnd.randrange(len(words))])
    return " ".join(output)


def rand_literal(n: int = 200) -> str:
    rnd = random.Random(1234567)
    alphabet = string.ascii_letters + string.digits
    return "".join(rnd.choice(alphabet) for _ in range(n))


ECHO_LITERAL = rand_literal()
ADVERSARIAL = (
    'data: {"x":1}\n\n'
    'data: [DONE]\n'
    '"finish_reason":"stop"\n'
    ': not-a-comment\r\n'
    ' 中文\U0001f600‍\U0001f9b0 '
    + "L" * 10000
)


@dataclass
class Case:
    case_id: str
    category: str
    title: str
    body: Dict[str, Any]
    stream: bool = False
    headers: List[List[str]] = field(default_factory=list)
    expected_http: str = "200"
    expected_finish: Optional[str] = None
    require_tool: bool = False
    expected_tool_count: Optional[int] = None
    expected_tool_name: Optional[str] = None
    expected_tool_arguments: Optional[Dict[str, Any]] = None
    expected_literal: Optional[str] = None
    expected_json: bool = False
    expected_usage: Optional[str] = None
    expected_prompt_tokens: Optional[int] = None
    expected_prompt_tokens_tolerance_ratio: float = 0.0
    http_is_review: bool = False
    finish_is_review: bool = False
    tool_is_review: bool = False
    repeats: int = 1
    note: str = ""


@dataclass
class Response:
    status: int = 0
    headers: Dict[str, str] = field(default_factory=dict)
    raw: bytes = b""
    source: str = "json"
    text: str = ""
    reasoning: str = ""
    finish_reasons: List[Any] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Optional[Dict[str, Any]] = None
    usage_frames: int = 0
    done_seen: bool = False
    parse_errors: List[str] = field(default_factory=list)
    elapsed: float = 0.0


def user(text: str) -> Dict[str, Any]:
    return {"role": "user", "content": text}


def system(text: str) -> Dict[str, Any]:
    return {"role": "system", "content": text}


def body(model: str, messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
    value = {"model": model, "messages": messages}
    value.update(kwargs)
    return value


def stream_body(value: Dict[str, Any], include_usage: bool = True) -> Dict[str, Any]:
    value = dict(value)
    value["stream"] = True
    if include_usage:
        value["stream_options"] = {"include_usage": True}
    else:
        value.pop("stream_options", None)
    return value


def synth_history(model: str, n_reads: int = 15) -> Dict[str, Any]:
    messages = [system("You are a coding agent. Use the Read tool to inspect files."),
                user("Audit every module under src/ and report what you find. Read the files one at a time.")]
    for index in range(n_reads):
        call_id = "Read_%d" % index
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": call_id, "type": "function",
                                         "function": {"name": "Read", "arguments": json.dumps(
                                             {"file_path": "src/mod%d.py" % index})}}]})
        messages.append({"role": "tool", "tool_call_id": call_id,
                         "content": "def mod%d():\n    return %d\n" % (index, index)})
    messages.append(user("Read src/final.py next, then stop."))
    return body(model, messages, tools=[TOOL_READ], max_tokens=2048)


def build_cases(model: str) -> List[Case]:
    """Thirty definitions selected directly from the source suite, in source order."""
    tiny = [user("Reply with exactly: OK")]
    stable = [system("You are terse."), user(filler(400, seed=7) + "\nSay OK.")]
    history = synth_history(model, n_reads=8)
    stripped = json.loads(json.dumps(history))
    for message in stripped["messages"]:
        if message.get("tool_calls"):
            for call in message["tool_calls"]:
                call["id"] = "x"
        if message.get("role") == "tool":
            message["tool_call_id"] = "x"
    history["max_tokens"] = stripped["max_tokens"] = 8

    cases = [
        Case("control.json", "对照组", "非流式基础对照", body(model, tiny, max_tokens=16)),
        Case("control.stream", "对照组", "流式基础对照", stream_body(body(model, tiny, max_tokens=16)), stream=True),
        Case("control.badreq", "对照组", "空消息负向对照", body(model, []), expected_http="400"),
        Case("tokens.identical", "Token", "完全相同请求的 Token 一致性", body(model, stable, max_tokens=8)),
        Case("tokens.ids_present", "Token", "保留历史工具调用 ID", history),
        Case("tokens.ids_stripped", "Token", "替换历史工具调用 ID", stripped),
        Case("tokens.maxtok1", "Token", "max_tokens=1 截断", body(model, [user("Write a long essay about turbines.")], max_tokens=1), expected_finish="length"),
        Case("tokens.maxcompletion_alias", "Token", "max_completion_tokens=1", body(model, [user("Write a long essay about turbines.")], max_completion_tokens=1), http_is_review=True),
        Case("tokens.truncate_toolcall", "Token", "工具参数截断", stream_body(body(model, [user(
             "Call write exactly once with file_path 'a.md' and at least 3000 words of content. Do not reply with text.")],
             tools=[TOOL_WRITE], max_tokens=96)), stream=True, expected_finish="length", expected_tool_name="write"),
        Case("tokens.stop", "Token", "stop 停止序列", body(model, [user("Count: one two three four five six")], max_tokens=64, stop=["four"])),
        Case("conf.temp1", "参数", "temperature=1", body(model, tiny, max_tokens=16, temperature=1)),
        Case("conf.temp_absent", "参数", "不传 temperature", body(model, tiny, max_tokens=16)),
        Case("conf.top_p", "参数", "top_p=0.95", body(model, tiny, max_tokens=16, temperature=1, top_p=0.95)),
        Case("conf.seed", "参数", "seed=42", body(model, tiny, max_tokens=16, seed=42)),
        Case("conf.n1", "参数", "n=1", body(model, tiny, max_tokens=16, n=1)),
        Case("conf.usage_on", "流式", "请求 usage", stream_body(body(model, tiny, max_tokens=16), True), stream=True),
        Case("conf.usage_empty_opts", "流式", "空 stream_options", dict(stream_body(body(model, tiny, max_tokens=16), False), stream_options={}), stream=True),
        Case("conf.tool_absent", "工具", "提供工具但不传 tool_choice", body(model, tiny, max_tokens=16, tools=[TOOL_WEATHER])),
        Case("conf.tool_auto", "工具", "tool_choice=auto", body(model, tiny, max_tokens=16, tools=[TOOL_WEATHER], tool_choice="auto")),
        Case("conf.tool_required", "工具", "tool_choice=required", body(model, tiny, max_tokens=256, tools=[TOOL_WEATHER], tool_choice="required"), require_tool=True),
        Case("conf.tool_nonexistent", "工具", "指定未声明的工具", body(model, tiny, max_tokens=16, tools=[TOOL_WEATHER],
             tool_choice={"type": "function", "function": {"name": "nope"}}), expected_http="400"),
        Case("conf.tool_empty_list", "工具", "空工具列表", body(model, tiny, max_tokens=16, tools=[]), http_is_review=True),
        Case("conf.tool_parallel_off", "工具", "关闭并行工具调用", body(model, tiny, max_tokens=16, tools=[TOOL_WEATHER], parallel_tool_calls=False)),
        Case("conf.rf_json_object", "结构化输出", "JSON object", body(model, [user('Reply with a JSON object {"ok": true}')],
             max_tokens=64, response_format={"type": "json_object"}), expected_json=True),
        Case("conf.rf_json_schema", "结构化输出", "JSON schema", body(model, [user("Reply with the answer object.")], max_tokens=64,
             response_format={"type": "json_schema", "json_schema": {"name": "ans", "strict": True,
             "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
             "additionalProperties": False}}}), expected_json=True, http_is_review=True),
        Case("conf.two_system", "消息", "连续两个 system 消息", body(model, [system("A."), system("B."),
             user("Reply with exactly: OK")], max_tokens=16)),
        Case("tc.single", "工具", "单个天气工具调用", stream_body(body(model, [user("What is the weather in Oslo? Use the tool.")],
             tools=[TOOL_WEATHER], max_tokens=512)), stream=True, require_tool=True, expected_tool_name="get_weather", tool_is_review=True),
        Case("tc.parallel4", "工具", "四个并行工具调用", stream_body(body(model, [user(
             "Get the weather for Oslo, Lima, Cairo and Perth. Issue all four tool calls in one turn.")],
             tools=[TOOL_WEATHER], max_tokens=1024)), stream=True, require_tool=True, expected_tool_count=4, expected_tool_name="get_weather", tool_is_review=True),
        Case("tc.echo_args", "工具", "工具参数原样回显", stream_body(body(model, [user(
             "Call write with file_path 'echo.md' and content set to exactly this token, unchanged and with nothing added:\n" + ECHO_LITERAL)],
             tools=[TOOL_WRITE], max_tokens=2048)), stream=True, require_tool=True, expected_tool_name="write", expected_literal=ECHO_LITERAL, tool_is_review=True),
        Case("tc.id_history", "工具", "历史工具调用 ID 续接", stream_body(synth_history(model, n_reads=15)), stream=True,
             require_tool=True, expected_tool_name="Read", tool_is_review=True),
    ]
    assert len(cases) == 30
    return cases


def endpoint_parts(base_url: str) -> Tuple[bool, str, int, str]:
    value = base_url.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if not parsed.hostname:
        raise ValueError("无法解析 --url")
    secure = parsed.scheme == "https"
    port = parsed.port or (443 if secure else 80)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        endpoint = path
    elif path.endswith("/v1"):
        endpoint = path + "/chat/completions"
    elif path:
        endpoint = path + "/v1/chat/completions"
    else:
        endpoint = "/v1/chat/completions"
    return secure, parsed.hostname, port, endpoint


def redact(value: str) -> str:
    value = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", r"\1***", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "sk-***", value)
    return value


def request(case: Case, base_url: str, api_key: Optional[str], timeout: float, insecure: bool) -> Response:
    secure, host, port, path = endpoint_parts(base_url)
    target = "%s://%s:%d%s" % ("https" if secure else "http", host, port, path)
    payload = json.dumps(case.body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if case.stream else "application/json",
               "User-Agent": "api-compat-probe/" + VERSION}
    for name, value in case.headers:
        if value is None:
            headers.pop(str(name), None)
        else:
            headers[str(name)] = str(value)
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    outgoing = Request(target, data=payload, headers=headers, method="POST")
    started = time.monotonic()
    previous_alarm = None
    alarm_enabled = hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")
    if alarm_enabled:
        def deadline_expired(signum: int, frame: Any) -> None:
            raise TimeoutError("总请求时间超过 %.0f 秒" % timeout)
        previous_alarm = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, deadline_expired)
        signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        try:
            raw_response = urlopen(outgoing, timeout=timeout, context=context if secure else None)
        except HTTPError as exc:
            raw_response = exc
        with raw_response:
            raw = raw_response.read()
            status = raw_response.getcode()
            response_headers = {k.lower(): v for k, v in raw_response.getheaders()}
    finally:
        if alarm_enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_alarm)
    result = Response(status=status, headers=response_headers, raw=raw,
                      source="stream" if case.stream else "json", elapsed=time.monotonic() - started)
    if case.stream:
        parse_stream(result)
    else:
        parse_json(result)
    return result


def parse_json(result: Response) -> None:
    try:
        obj = json.loads(result.raw.decode("utf-8"))
    except Exception as exc:
        result.parse_errors.append("响应不是有效 JSON: %s" % exc)
        return
    if not isinstance(obj, dict):
        result.parse_errors.append("JSON 顶层不是对象")
        return
    result.usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
    choices = obj.get("choices") or []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        if choice.get("finish_reason") is not None:
            result.finish_reasons.append(choice.get("finish_reason"))
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            result.text += content
        refusal = message.get("refusal")
        if isinstance(refusal, str):
            result.text += refusal
        for key in ("reasoning", "reasoning_content"):
            if isinstance(message.get(key), str):
                result.reasoning += message[key]
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict):
                result.tool_calls.append(call)


def parse_stream(result: Response) -> None:
    text = result.raw.decode("utf-8", "replace")
    if "\ufffd" in text:
        result.parse_errors.append("流式响应包含 UTF-8 替换字符")
    calls: Dict[int, Dict[str, Any]] = {}
    finish_seen = False
    call_name_seen: Dict[int, bool] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            result.parse_errors.append("SSE 行缺少 data: 前缀")
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            result.done_seen = True
            continue
        try:
            obj = json.loads(data)
        except Exception as exc:
            result.parse_errors.append("SSE data 不是有效 JSON: %s" % exc)
            continue
        if isinstance(obj.get("usage"), dict):
            result.usage = obj["usage"]
            result.usage_frames += 1
        for choice in obj.get("choices") or []:
            finish = choice.get("finish_reason")
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                if finish_seen and content:
                    result.parse_errors.append("finish_reason 之后仍有正文数据")
                result.text += content
            refusal = delta.get("refusal")
            if isinstance(refusal, str):
                result.text += refusal
            for key in ("reasoning", "reasoning_content"):
                if isinstance(delta.get(key), str):
                    result.reasoning += delta[key]
            for call in delta.get("tool_calls") or []:
                idx = call.get("index")
                if not isinstance(idx, int) or idx < 0:
                    result.parse_errors.append("工具调用 delta 缺少合法 index")
                    idx = 0
                if finish_seen:
                    result.parse_errors.append("finish_reason 之后仍有工具调用数据")
                current = calls.setdefault(idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    current["id"] += str(call["id"])
                function = call.get("function") or {}
                if function.get("name"):
                    current["function"]["name"] += str(function["name"])
                    call_name_seen[idx] = True
                if function.get("arguments"):
                    if not call_name_seen.get(idx):
                        result.parse_errors.append("工具参数 delta 出现在函数名之前")
                    current["function"]["arguments"] += str(function["arguments"])
            if finish is not None:
                result.finish_reasons.append(finish)
                finish_seen = True
    result.tool_calls = [calls[index] for index in sorted(calls)]


def status_matches(expected: str, actual: int) -> bool:
    if expected == "2xx":
        return 200 <= actual < 300
    if expected == "non-2xx":
        return not (200 <= actual < 300)
    return str(actual) == expected


def validate(case: Case, result: Response) -> Tuple[List[str], List[str]]:
    """Return (hard protocol/structure failures, observations needing review)."""
    issues: List[str] = []
    reviews: List[str] = []
    if not status_matches(case.expected_http, result.status):
        target = reviews if case.http_is_review else issues
        target.append("HTTP 状态不符合预期：期望 %s，实际 %s" % (case.expected_http, result.status))
        return issues, reviews
    if not (200 <= result.status < 300):
        return issues, reviews
    issues.extend(result.parse_errors)
    if not result.finish_reasons:
        issues.append("成功响应缺少 finish_reason")
    elif any(value not in ("stop", "length", "tool_calls", "content_filter", "function_call") for value in result.finish_reasons):
        issues.append("出现未知 finish_reason: %r" % result.finish_reasons)
    if case.expected_finish and case.expected_finish not in result.finish_reasons:
        target = reviews if case.finish_is_review else issues
        target.append("期望 finish_reason=%s，实际 %r" % (case.expected_finish, result.finish_reasons))
    if len(result.finish_reasons) > 1:
        issues.append("同一响应出现多个 finish_reason")
    if case.stream and not result.done_seen:
        issues.append("流式响应缺少 [DONE]")
    wants_usage = bool((case.body.get("stream_options") or {}).get("include_usage"))
    usage_expectation = case.expected_usage
    if usage_expectation == "present" and result.usage is None:
        issues.append("基准要求返回 usage，但响应未返回 usage")
    elif usage_expectation == "absent" and result.usage is not None:
        issues.append("基准要求不返回 usage，但响应返回了 usage")
    elif usage_expectation is None and wants_usage and result.usage is None:
        issues.append("已请求 usage，但流式响应未返回 usage")
    if usage_expectation is None and case.case_id == "conf.usage_off" and result.usage is not None:
        issues.append("未请求 usage，但流式响应仍返回了 usage")
    if result.usage_frames > 1:
        issues.append("流式响应返回了多个 usage 帧")
    if case.require_tool and not result.tool_calls:
        target = reviews if case.tool_is_review else issues
        target.append("未返回要求的工具调用")
    if case.expected_tool_count is not None and len(result.tool_calls) != case.expected_tool_count:
        target = reviews if case.tool_is_review else issues
        target.append("工具调用数量：期望 %d，实际 %d" % (case.expected_tool_count, len(result.tool_calls)))
    ids = []
    declared = {item["function"]["name"] for item in case.body.get("tools", [])}
    for index, call in enumerate(result.tool_calls):
        call_id = call.get("id")
        function = call.get("function") or {}
        name = function.get("name")
        arguments = function.get("arguments")
        if not call_id:
            issues.append("第 %d 个工具调用缺少 id" % (index + 1))
        else:
            ids.append(call_id)
        if not name:
            issues.append("第 %d 个工具调用缺少函数名" % (index + 1))
        elif declared and name not in declared:
            issues.append("调用了未声明的工具 %s" % name)
        if case.expected_tool_name and name and name != case.expected_tool_name:
            issues.append("工具名称不符：期望 %s，实际 %s" % (case.expected_tool_name, name))
        if arguments is None:
            issues.append("工具调用缺少 arguments")
        else:
            try:
                json.loads(arguments)
            except Exception:
                if case.expected_finish != "length":
                    issues.append("工具参数不是有效 JSON")
    if len(ids) != len(set(ids)):
        issues.append("同一响应内工具调用 id 重复")
    historical_ids = {
        call.get("id")
        for message in case.body.get("messages", []) if isinstance(message, dict)
        for call in message.get("tool_calls", []) if isinstance(call, dict) and call.get("id")
    }
    if historical_ids.intersection(ids):
        issues.append("新工具调用 id 与历史消息中的 id 冲突")
    if result.tool_calls and not any(value in ("tool_calls", "length") for value in result.finish_reasons):
        issues.append("已返回工具调用，但 finish_reason 不是 tool_calls")
    if "tool_calls" in result.finish_reasons and not result.tool_calls:
        issues.append("finish_reason=tool_calls，但响应中没有工具调用")
    if case.expected_tool_arguments is not None and result.tool_calls:
        matching = [call for call in result.tool_calls
                    if (call.get("function") or {}).get("name") == case.expected_tool_name]
        if matching:
            try:
                actual_arguments = json.loads((matching[0].get("function") or {}).get("arguments") or "")
                for key, expected_value in case.expected_tool_arguments.items():
                    if actual_arguments.get(key) != expected_value:
                        issues.append("工具参数 %s 不符：期望 %r，实际 %r" % (
                            key, expected_value, actual_arguments.get(key)))
            except Exception:
                pass
    if case.expected_literal:
        fragments = [str((call.get("function") or {}).get("arguments") or "") for call in result.tool_calls]
        searchable = result.text + " " + " ".join(fragments)
        if case.expected_literal not in searchable:
            reviews.append("响应未完整保留指定文本；需区分模型未遵循指令与传输损坏")
    if case.expected_json:
        if not result.text.strip():
            issues.append("已请求结构化输出，但响应正文为空")
        else:
            try:
                parsed = json.loads(result.text)
                if not isinstance(parsed, dict):
                    issues.append("结构化输出的 JSON 顶层不是对象")
                elif case.case_id == "conf.rf_json_schema" and parsed.get("ok") is not True:
                    issues.append("JSON schema 结果不满足 ok=true")
            except Exception:
                issues.append("结构化输出不是有效 JSON")
    usage = result.usage
    if usage:
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if all(isinstance(value, int) for value in (prompt, completion, total)):
            if min(prompt, completion, total) < 0 or prompt + completion != total:
                issues.append("usage token 计数不成立")
        if case.expected_prompt_tokens is not None:
            if not isinstance(prompt, int):
                issues.append("prompt_tokens 不是整数：实际 %r" % prompt)
            elif prompt != case.expected_prompt_tokens:
                difference_ratio = (abs(prompt - case.expected_prompt_tokens) /
                                    float(case.expected_prompt_tokens))
                if difference_ratio > case.expected_prompt_tokens_tolerance_ratio:
                    issues.append(
                        "prompt_tokens 超出容差：基准 %d，实际 %r，偏差 %.2f%%，容差 %.2f%%" % (
                            case.expected_prompt_tokens, prompt, difference_ratio * 100,
                            case.expected_prompt_tokens_tolerance_ratio * 100))
    if (not result.text and not result.reasoning and not result.tool_calls and result.finish_reasons
            and not any(value in ("length", "content_filter") for value in result.finish_reasons)):
        issues.append("响应正常结束但内容和工具调用均为空")
    if result.reasoning and not result.text and not result.tool_calls and "stop" in result.finish_reasons:
        reviews.append("仅返回推理内容，没有可见正文")
    return issues, reviews


def save_wire(out_dir: str, case: Case, result: Response, run_id: str) -> str:
    wire_dir = os.path.join(out_dir, "wire")
    os.makedirs(wire_dir, exist_ok=True)
    path = os.path.join(wire_dir, run_id + ".json.gz")
    record = {
        "case_id": case.case_id, "run_id": run_id,
        "request": case.body,
        "response": {
            "status": result.status,
            "headers": result.headers,
            "body": result.raw.decode("utf-8", "replace"),
            "elapsed_seconds": round(result.elapsed, 3),
        },
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    return path


def list_cases(cases: List[Case]) -> None:
    print("ID                         类别       次数  用例")
    print("-------------------------- ---------- ----  --------------------------------")
    for case in cases:
        print("%-26s %-10s %-4d  %s" % (case.case_id, case.category, case.repeats, case.title))
    print("\n共 %d 个用例，%d 次调用" % (len(cases), sum(case.repeats for case in cases)))


def load_dataset(path: str, model: str) -> List[Case]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    cases = []
    for entry in document.get("calls", []):
        expected = entry.get("expected") or {}
        request_body = json.loads(json.dumps(entry["body"]))
        if request_body.get("model") == "test-model":
            request_body["model"] = model
        elif request_body.get("model") == "test-model ":
            request_body["model"] = model + " "
        cases.append(Case(
            case_id=entry["run_id"],
            category=entry.get("category", "dataset"),
            title=entry.get("source_case_id", entry["run_id"]),
            body=request_body,
            stream=bool(entry.get("stream")),
            headers=entry.get("headers") or [],
            expected_http=str(expected.get("http", "200")),
            expected_finish=expected.get("finish_reason"),
            require_tool=bool(expected.get("require_tool", False)),
            expected_tool_count=expected.get("tool_count"),
            expected_tool_name=expected.get("tool_name"),
            expected_tool_arguments=expected.get("tool_arguments"),
            expected_literal=expected.get("literal"),
            expected_json=bool(expected.get("json", False)),
            expected_usage=expected.get("usage"),
            expected_prompt_tokens=expected.get("prompt_tokens"),
            expected_prompt_tokens_tolerance_ratio=float(
                expected.get("prompt_tokens_tolerance_ratio", 0.0)),
            http_is_review=bool(expected.get("http_is_review", False)),
            finish_is_review=bool(expected.get("finish_is_review", False)),
            tool_is_review=bool(expected.get("tool_is_review", False)),
        ))
    if not cases:
        raise ValueError("数据集不包含 calls")
    return cases


def self_test() -> int:
    cases = build_cases("test-model")
    assert len(cases) == 30
    sample = Response(status=200, raw=json.dumps({
        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }).encode("utf-8"))
    parse_json(sample)
    assert sample.text == "OK" and sample.finish_reasons == ["stop"]
    assert validate(cases[0], sample) == ([], [])
    streamed = Response(status=200, source="stream", raw=(
        'data: {"choices":[{"delta":{"content":"O"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":"K"},"finish_reason":"stop"}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}\n\n'
        'data: [DONE]\n\n').encode("utf-8"))
    parse_stream(streamed)
    assert streamed.text == "OK" and streamed.done_seen and streamed.finish_reasons == ["stop"]
    assert validate(cases[1], streamed) == ([], [])

    bad_usage = Response(status=200, text="OK", finish_reasons=["stop"],
                         usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 99})
    assert "usage token 计数不成立" in validate(cases[0], bad_usage)[0]
    dropped_tool = Response(status=200, finish_reasons=["tool_calls"], done_seen=True)
    hard, _ = validate(next(case for case in cases if case.case_id == "conf.tool_required"), dropped_tool)
    assert any("没有工具调用" in item or "未返回" in item for item in hard)
    optional_reject = Response(status=400)
    hard, review = validate(next(case for case in cases if case.case_id == "tokens.maxcompletion_alias"), optional_reject)
    assert not hard and review
    negative_ok = Response(status=400)
    assert validate(next(case for case in cases if case.case_id == "control.badreq"), negative_ok) == ([], [])
    duplicate_finish = Response(status=200, text="OK", finish_reasons=["stop", "stop"], done_seen=True)
    assert "同一响应出现多个 finish_reason" in validate(cases[1], duplicate_finish)[0]
    empty_structured = Response(status=200, finish_reasons=["length"])
    structured_case = next(case for case in cases if case.case_id == "conf.rf_json_object")
    assert "已请求结构化输出，但响应正文为空" in validate(structured_case, empty_structured)[0]
    tolerant_case = Case(
        case_id="tokens.tolerance.selftest", category="tokens", title="tolerance",
        body=body("test-model", [user("OK")]), expected_usage="present",
        expected_prompt_tokens=100, expected_prompt_tokens_tolerance_ratio=0.03,
    )
    within_tolerance = Response(
        status=200, text="OK", finish_reasons=["stop"],
        usage={"prompt_tokens": 103, "completion_tokens": 1, "total_tokens": 104},
    )
    outside_tolerance = Response(
        status=200, text="OK", finish_reasons=["stop"],
        usage={"prompt_tokens": 104, "completion_tokens": 1, "total_tokens": 105},
    )
    assert validate(tolerant_case, within_tolerance) == ([], [])
    assert any("超出容差" in item for item in validate(tolerant_case, outside_tolerance)[0])
    packaged_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.json")
    packaged_count = 0
    if os.path.exists(packaged_path):
        packaged = load_dataset(packaged_path, "test-model")
        packaged_count = len(packaged)
        assert len({case.case_id for case in packaged}) == packaged_count
        required_feedback = {
            "tokens.feedback.short_plain", "tokens.feedback.long_plain",
            "tokens.feedback.short_tool", "tokens.feedback.long_tool",
        }
        assert required_feedback.issubset({case.case_id for case in packaged})
    print("self-test PASSED: parsers, verdict boundaries and %d packaged cases verified" % packaged_count)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="精简、脱敏的 OpenAI Chat Completions 兼容性测试工具")
    parser.add_argument("--url", help="基础 URL，例如 https://api.example.com/v1")
    parser.add_argument("--key", help="API Key；也可使用 API_COMPAT_KEY 环境变量")
    parser.add_argument("--model", default="test-model", help="待测模型名")
    parser.add_argument("--dataset", help="从 JSON 数据集加载用例")
    parser.add_argument("--capture-only", action="store_true", help="仅采集响应，不执行判断")
    parser.add_argument("--case", action="append", dest="case_ids", help="只运行指定用例 ID；可重复")
    parser.add_argument("--single-run", action="store_true", help="每个选中用例只调用一次，忽略原始重复次数")
    parser.add_argument("--list-cases", action="store_true", help="列出全部用例")
    parser.add_argument("--self-test", action="store_true", help="离线自检")
    parser.add_argument("--dry-run", action="store_true", help="仅显示将运行的用例")
    parser.add_argument("--timeout", type=float, default=180.0, help="单次请求超时秒数")
    parser.add_argument("--out", default=None, help="报告输出目录")
    parser.add_argument("--insecure", action="store_true", help="跳过 TLS 证书校验，仅限测试环境")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    packaged_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.json")
    dataset_path = args.dataset or (packaged_path if os.path.exists(packaged_path) else None)
    cases = load_dataset(dataset_path, args.model) if dataset_path else build_cases(args.model)
    if args.list_cases:
        list_cases(cases)
        return 0
    if args.case_ids:
        wanted = {value.upper() for value in args.case_ids}
        cases = [case for case in cases if case.case_id.upper() in wanted]
        missing = wanted - {case.case_id.upper() for case in cases}
        if missing:
            parser.error("未知用例 ID: " + ", ".join(sorted(missing)))
    if args.single_run:
        for case in cases:
            case.repeats = 1
    if args.dry_run:
        list_cases(cases)
        return 0
    if not args.url:
        parser.error("运行测试需要 --url；查看清单可用 --list-cases")

    api_key = args.key or os.environ.get("API_COMPAT_KEY")
    out_dir = args.out or ("api-compat-report-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    results = []
    failures = 0
    total_calls = sum(case.repeats for case in cases)
    print("api-compat-probe %s | %d cases / %d calls | model=%s" % (
        VERSION, len(cases), total_calls, args.model))
    call_index = 0
    for case in cases:
        for repeat_index in range(1, case.repeats + 1):
            call_index += 1
            run_id = case.case_id if case.repeats == 1 else "%s.%d" % (case.case_id, repeat_index)
            try:
                response = request(case, args.url, api_key, args.timeout, args.insecure)
                issues, reviews = ([], []) if args.capture_only else validate(case, response)
                wire = save_wire(out_dir, case, response, run_id)
            except Exception as exc:
                response = Response()
                issues = ["请求失败: " + redact(str(exc))]
                reviews = []
                wire = ""
            passed = not issues
            failures += 0 if passed else 1
            marker = "未通过" if issues else ("待确认" if reviews else "通过")
            print("[%02d/%02d] %s %s %s (HTTP %s, %.2fs)" % (
                call_index, total_calls, marker, run_id, case.title, response.status or "-", response.elapsed))
            for issue in issues:
                print("         - " + redact(issue))
            for review in reviews:
                print("         - [待确认] " + redact(review))
            results.append({
                "case_id": case.case_id, "run_id": run_id, "repeat": repeat_index,
                "category": case.category, "title": case.title,
                "status": "failed" if issues else ("review" if reviews else "passed"),
                "passed": passed, "http_status": response.status, "elapsed_seconds": round(response.elapsed, 3),
                "issues": issues, "reviews": reviews, "wire": wire,
            })

    passed_count = sum(item["status"] == "passed" for item in results)
    review_count = sum(item["status"] == "review" for item in results)
    report = {
        "tool": "api-compat-probe", "version": VERSION, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": args.model, "summary": {"cases": len(cases), "calls": len(results), "passed": passed_count,
        "review": review_count, "failed": failures},
        "results": results,
    }
    report_path = os.path.join(out_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("\n结果：通过 %d，待确认 %d，未通过 %d；报告：%s" % (
        passed_count, review_count, failures, report_path))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
