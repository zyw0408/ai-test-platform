#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回放 kimi-k3 JSON 入参，扫描是否出现已知异常（不按 bug 类型分用例）。

主要盯的问题：
  - finish_reason=error
  - finish_reason=length（含 32k：length + tool arguments 非法 JSON）
  - finish_reason 全程为 null（含有正文仍 null、以及 [DONE] 可能被中继补发）
  - null + 空 content

其它也会标不健康：工具 JSON 残缺、声明 tool_calls 却无工具、缺 [DONE]、
stop 空输出、传输/SSE 失败、客户端截断、强制长 args 却未调工具、
超长耗时却几乎无 completion、冲突的 finish_reason 历史等。

一次请求可命中多类异常；unhealthy_reason 取优先级最高的一类。
出现任一则该次不健康，进程退出码 1。

用法：
  python3 scripts/kimi_k3_sep2_replay_bench.py
  python3 scripts/kimi_k3_sep2_replay_bench.py scripts/inputs/foo.json
  python3 scripts/kimi_k3_sep2_replay_bench.py --input a.json --concurrency 1

  # 专测 ~32k tool_call.arguments 截断（推荐）：
  # hard 模式会嵌入必须原样 write 的大 blob，并默认关掉 thinking
  # --tool-choice required|write 可强制走工具，避免纯文本逃逸
  python3 scripts/kimi_k3_sep2_replay_bench.py scripts/inputs/issue1_error_case1.json \\
    --bust-cache --force-long-tool-args --tool-choice write \\
    --max-tokens 8192 --target-tool-arg-chars 80000 \\
    --concurrency 1 --repeat 8

报告写到 temp/kimi_k3_sep2_replay_<时间戳>/ （report.md + report.json）
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import secrets
import ssl
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ======== 直接改这里 ========
CONFIG: Dict[str, Any] = {
    "url": "",
    "api_key": "",
    # 空=跑 scripts/inputs/ 下全部 *.json；也可填相对/绝对路径
    "inputs": [],
    "repeat": 30,
    # 1=一个个串行
    "concurrency": 30,
    # 建连 + 等 HTTP 响应头/首包（不是流式读超时）。高并发长 thinking 经常超过 60s
    "connect_timeout": 1200,
    "read_timeout": 3600,
    # None=沿用入参 JSON；设成 32768 便于贴 32k 输出上限复现 arguments 截断
    "max_tokens": None,
    # 每次请求在 system/首条消息前插入随机 nonce，降低 prefix cache 命中
    "bust_cache": False,
    # 追加/硬造超长 tool arguments（默认硬模式：嵌入必须原样写入的固定 blob）
    "force_long_tool_args": False,
    # soft=只在原对话末尾加指令（易被模型忽略）；hard=替换成「复制 blob→write」专用对话
    "force_long_tool_args_mode": "hard",
    "target_tool_arg_chars": 40000,
    # 逼 arguments 吃满额度时关掉长思考，避免 completion 都被 reasoning 占掉
    "disable_thinking": False,
    # 可选：强制工具调用。""=不改入参；required；write=强制调用 write 类函数
    "tool_choice": "",
    "extra_headers": {
        # 客户抓包里带过；不需要可改成 {}
        "X-Use-Deployment-As-Model": "true",
    },
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(SCRIPT_DIR, "inputs")

# 报告总览优先展示的异常（顺序即 unhealthy_reason 优先级）
ANOMALY_PRIORITY = (
    "transport_or_sse_error",
    "truncated_by_client",
    "finish_reason_error",
    "null_empty_content",
    "tool_args_truncated_by_length",
    "incomplete_tool_call_json",
    "finish_reason_length",
    "tool_calls_finish_without_tools",
    "finish_reason_null",
    "missing_done",
    "conflicting_finish_reasons",
    "forced_tool_missing",
    "suspected_upstream_stall",
    "finish_reason_content_filter",
    "abnormal_finish_reason",
    "stop_with_empty_output",
)

# 兼容旧字段名
NAMED_ANOMALIES = (
    "finish_reason_error",
    "null_empty_content",
    "finish_reason_null",
    "finish_reason_length",
    "incomplete_tool_call_json",
    "tool_args_truncated_by_length",
)

# 超长耗时但几乎无 completion：疑似上游 hang / 被掐断后中继补 [DONE]
STALL_DURATION_MS = 600_000
STALL_MAX_COMPLETION_TOKENS = 1


class _NoRedirect(urllib.request.HTTPErrorProcessor):
    def http_response(self, request, response):  # type: ignore[no-untyped-def]
        return response

    https_response = http_response


def normalize_api_key(api_key: str) -> str:
    key = str(api_key or "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def load_payload(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("%s 不是 JSON 对象" % path)
    data["stream"] = True
    return data


def summarize_input(payload: Dict[str, Any], path: str) -> Dict[str, Any]:
    messages = payload.get("messages") or []
    tools = payload.get("tools") or []
    raw = json.dumps(payload, ensure_ascii=False)
    roles: List[str] = []
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                roles.append(str(msg.get("role") or ""))
    tool_names: List[str] = []
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
                name = fn.get("name") or tool.get("name")
                if name:
                    tool_names.append(str(name))
    skip = {"messages", "tools"}
    out: Dict[str, Any] = {
        "payload_file": path,
        "char_count": len(raw),
        "byte_count": len(raw.encode("utf-8")),
    }
    for key, value in payload.items():
        if key in skip:
            continue
        out[key] = value
    out["message_count"] = len(messages) if isinstance(messages, list) else 0
    out["message_roles"] = roles
    out["tool_count"] = len(tools) if isinstance(tools, list) else 0
    out["tool_names"] = tool_names
    out["top_level_keys"] = sorted(payload.keys())
    return out


def parse_sse_data_line(line: str) -> Optional[str]:
    if not line.startswith("data:"):
        return None
    data = line[5:]
    if data.startswith(" "):
        data = data[1:]
    data = data.strip()
    return data or None


def set_socket_timeout(resp: Any, seconds: float) -> None:
    candidates = []
    fp = getattr(resp, "fp", None)
    if fp is not None:
        candidates.append(fp)
        raw = getattr(fp, "raw", None)
        if raw is not None:
            candidates.append(raw)
        inner = getattr(fp, "fp", None)
        if inner is not None:
            candidates.append(inner)
    for obj in candidates:
        try:
            if hasattr(obj, "settimeout"):
                obj.settimeout(seconds)
                return
        except Exception:
            continue


def headers_to_dict(headers: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if headers is None:
        return out
    try:
        for k, v in headers.items():
            out[str(k)] = str(v)
    except Exception:
        out["raw"] = str(headers)
    return out


def extract_choice_fields(obj: Dict[str, Any]) -> Tuple[str, str, Optional[str], Any, Any]:
    choices = obj.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return "", "", None, None, None
    first = choices[0]
    finish = first.get("finish_reason")
    if finish == "null":
        finish = None
    delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    src = delta or message
    reasoning = src.get("reasoning_content") or src.get("reasoning") or ""
    content = src.get("content") or ""
    if not isinstance(reasoning, str):
        reasoning = "" if reasoning is None else str(reasoning)
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    tool_calls = src.get("tool_calls")
    usage = obj.get("usage")
    return reasoning, content, finish if isinstance(finish, str) else None, tool_calls, usage


def merge_tool_calls(dst: List[Dict[str, Any]], incoming: Any) -> None:
    if not incoming:
        return
    if isinstance(incoming, dict):
        incoming = [incoming]
    if not isinstance(incoming, list):
        return
    for item in incoming:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int) or idx < 0:
            idx = len(dst)
        while len(dst) <= idx:
            dst.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        slot = dst[idx]
        if item.get("id"):
            slot["id"] = str(item.get("id"))
        if item.get("type"):
            slot["type"] = str(item.get("type"))
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        if fn.get("name"):
            slot["function"]["name"] = str(fn.get("name"))
        if fn.get("arguments"):
            slot["function"]["arguments"] += str(fn.get("arguments"))


def tool_call_args_complete(tool_calls: Any) -> bool:
    if not isinstance(tool_calls, list) or not tool_calls:
        return True
    for tc in tool_calls:
        if not isinstance(tc, dict):
            return False
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        raw = fn.get("arguments")
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str):
            raw = json.dumps(raw, ensure_ascii=False)
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            return False
    return True


def tool_call_arg_stats(tool_calls: Any) -> Dict[str, Any]:
    """汇总 tool_call.arguments 长度，便于判断是否逼近 32k 截断。"""
    total = 0
    max_one = 0
    names: List[str] = []
    incomplete = False
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name") or "")
            if name:
                names.append(name)
            raw = fn.get("arguments")
            if raw is None:
                continue
            if not isinstance(raw, str):
                raw = json.dumps(raw, ensure_ascii=False)
            n = len(raw)
            total += n
            if n > max_one:
                max_one = n
            if raw:
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    incomplete = True
    return {
        "tool_args_chars_total": total,
        "tool_args_chars_max": max_one,
        "tool_names": names,
        "tool_args_incomplete": incomplete,
    }


def prepend_text_to_message_content(content: Any, prefix: str) -> Any:
    if content is None or content == "":
        return prefix
    if isinstance(content, str):
        return prefix + content
    if isinstance(content, list):
        parts = list(content)
        for i, part in enumerate(parts):
            if isinstance(part, dict) and str(part.get("type") or "") in {"text", "input_text"}:
                text = str(part.get("text") or "")
                new_part = dict(part)
                new_part["text"] = prefix + text
                parts[i] = new_part
                return parts
        parts.insert(0, {"type": "text", "text": prefix})
        return parts
    return prefix + str(content)


def bust_cache_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """破坏公共前缀，降低 Kimi prefix cache 命中（每次请求唯一 nonce）。"""
    out = copy.deepcopy(payload)
    nonce = secrets.token_hex(8)
    prefix = "[cache-bust nonce=%s ts=%.6f]\n" % (nonce, time.time())
    messages = out.get("messages")
    if not isinstance(messages, list):
        messages = []
        out["messages"] = messages
    if messages and isinstance(messages[0], dict) and str(messages[0].get("role") or "") == "system":
        messages[0] = dict(messages[0])
        messages[0]["content"] = prepend_text_to_message_content(messages[0].get("content"), prefix)
    else:
        messages.insert(0, {"role": "system", "content": prefix.strip()})
    return out, nonce


def build_embed_blob(target_chars: int, nonce: str) -> str:
    """生成定长可校验文本，供模型原样拷进 tool arguments。"""
    target = max(1000, int(target_chars))
    header = "BENCH_BLOB nonce=%s target=%d\n" % (nonce, target)
    lines: List[str] = [header]
    i = 0
    while sum(len(x) for x in lines) < target:
        # 每行约 80 chars，带行号便于肉眼核对是否截断
        lines.append("L%06d %s\n" % (i, ("x%04d-" % (i % 10000)) * 8))
        i += 1
    blob = "".join(lines)
    if len(blob) > target:
        blob = blob[:target]
    elif len(blob) < target:
        blob += "Y" * (target - len(blob))
    return blob


def default_write_tool() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write full file contents to a path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "contents": {"type": "string"},
                },
                "required": ["path", "contents"],
            },
        },
    }


def pick_write_like_tools(tools: Any) -> List[Dict[str, Any]]:
    """优先保留 write/edit；没有则注入默认 write。"""
    kept: List[Dict[str, Any]] = []
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            name = str(fn.get("name") or tool.get("name") or "").lower()
            if name in {"write", "edit", "create_file", "write_file"}:
                kept.append(tool)
    if not kept:
        kept = [default_write_tool()]
    return kept


def force_long_tool_args_payload(
    payload: Dict[str, Any],
    target_chars: int,
    *,
    mode: str = "hard",
    worker_id: int = 0,
    nonce: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """逼出超长 tool_call.arguments。

    soft: 在原对话末尾加文字约束（模型常忽略，继续短 bash）。
    hard: 丢掉原 messages，改成「把嵌入 blob 原样写入 write.contents」——arguments 长度几乎由 blob 决定。
    """
    out = copy.deepcopy(payload)
    target = max(1000, int(target_chars or 40000))
    mode = (mode or "hard").strip().lower()
    meta: Dict[str, Any] = {"force_mode": mode, "embed_blob_chars": 0, "embed_nonce": nonce}

    if mode == "soft":
        instruction = (
            "\n\n[REPLAY BENCH FORCE LONG TOOL ARGS / SOFT]\n"
            "You MUST end with tool_calls. Prefer write/edit. "
            "arguments MUST contain >= %d characters. No short bash.\n"
        ) % target
        messages = out.get("messages")
        if not isinstance(messages, list):
            messages = []
            out["messages"] = messages
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, dict) and str(msg.get("role") or "") == "user":
                messages[i] = dict(msg)
                content = messages[i].get("content")
                if isinstance(content, str):
                    messages[i]["content"] = content + instruction
                elif isinstance(content, list):
                    parts = list(content)
                    parts.append({"type": "text", "text": instruction})
                    messages[i]["content"] = parts
                else:
                    messages[i]["content"] = str(content or "") + instruction
                break
        else:
            messages.append({"role": "user", "content": instruction.strip()})
        return out, meta

    # hard mode
    blob_nonce = nonce or secrets.token_hex(4)
    blob = build_embed_blob(target, blob_nonce)
    meta["embed_blob_chars"] = len(blob)
    meta["embed_nonce"] = blob_nonce
    out["tools"] = pick_write_like_tools(out.get("tools"))
    # 只留 write 类，避免模型逃到 bash
    path = "work/bench_force_args_w%02d_%s.txt" % (worker_id, blob_nonce)
    user = (
        "Call the write (or edit) tool EXACTLY once.\n"
        "Set path to: %s\n"
        "Set contents to EXACTLY the text between BEGIN_PAYLOAD and END_PAYLOAD "
        "(copy verbatim, do not shorten, do not summarize, do not escape differently).\n"
        "Do not call bash. Do not reply with plain text.\n\n"
        "BEGIN_PAYLOAD\n%s\nEND_PAYLOAD\n"
    ) % (path, blob)
    out["messages"] = [
        {
            "role": "system",
            "content": "You are a tool-calling assistant. Respond only with a single write/edit tool call.",
        },
        {"role": "user", "content": user},
    ]
    return out, meta


def disable_thinking_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(payload)
    out.pop("thinking", None)
    out.pop("reasoning_effort", None)
    # 部分上游用 enable_thinking
    if isinstance(out.get("extra_body"), dict):
        extra = dict(out["extra_body"])
        extra["enable_thinking"] = False
        out["extra_body"] = extra
    return out


def first_write_like_tool_name(tools: Any) -> str:
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            name = str(fn.get("name") or tool.get("name") or "")
            if name.lower() in {"write", "edit", "create_file", "write_file"}:
                return name
    return "write"


def apply_tool_choice(payload: Dict[str, Any], choice: str) -> Tuple[Dict[str, Any], str]:
    """设置 tool_choice。返回 (payload, 实际写入的模式说明)。"""
    out = payload
    mode = str(choice or "").strip().lower()
    if not mode or mode in {"auto", "none"}:
        return out, ""
    if mode == "required":
        out["tool_choice"] = "required"
        return out, "required"
    if mode == "write":
        tools = out.get("tools")
        if not isinstance(tools, list) or not tools:
            out["tools"] = [default_write_tool()]
        name = first_write_like_tool_name(out.get("tools"))
        if name.lower() not in {"write", "edit", "create_file", "write_file"}:
            out["tools"] = list(out.get("tools") or []) + [default_write_tool()]
            name = "write"
        out["tool_choice"] = {"type": "function", "function": {"name": name}}
        return out, "write:%s" % name
    raise ValueError("unsupported tool_choice=%r (use required|write)" % choice)


def prepare_payload_for_run(base_payload: Dict[str, Any], cfg: Dict[str, Any], worker_id: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """按 worker 生成独立 payload，避免并发共享同一 dict，并应用缓存破坏/长 tool 指令。"""
    meta: Dict[str, Any] = {
        "worker_id": worker_id,
        "cache_bust_nonce": "",
        "force_long_tool_args": False,
        "disable_thinking": False,
        "tool_choice": "",
    }
    payload = copy.deepcopy(base_payload)
    max_tokens = cfg.get("max_tokens")
    if max_tokens is not None and int(max_tokens) > 0:
        payload["max_tokens"] = int(max_tokens)

    bust_nonce = ""
    if cfg.get("bust_cache"):
        payload, bust_nonce = bust_cache_payload(payload)
        meta["cache_bust_nonce"] = bust_nonce

    if cfg.get("force_long_tool_args"):
        mode = str(cfg.get("force_long_tool_args_mode") or "hard")
        payload, force_meta = force_long_tool_args_payload(
            payload,
            int(cfg.get("target_tool_arg_chars") or 40000),
            mode=mode,
            worker_id=worker_id,
            nonce=bust_nonce or secrets.token_hex(4),
        )
        meta["force_long_tool_args"] = True
        meta["target_tool_arg_chars"] = int(cfg.get("target_tool_arg_chars") or 40000)
        meta.update(force_meta)
        # hard 模式默认关思考，否则 reasoning 吃光 max_tokens，arguments 仍到不了 30k+
        if mode != "soft" and not cfg.get("keep_thinking"):
            payload = disable_thinking_payload(payload)
            meta["disable_thinking"] = True

    if cfg.get("disable_thinking") and not meta.get("disable_thinking"):
        payload = disable_thinking_payload(payload)
        meta["disable_thinking"] = True

    tool_choice = str(cfg.get("tool_choice") or "").strip()
    if tool_choice:
        payload, applied = apply_tool_choice(payload, tool_choice)
        meta["tool_choice"] = applied or tool_choice

    return payload, meta


def classify_run(result: Dict[str, Any]) -> Dict[str, Any]:
    finish = result.get("finish_reason")
    if finish == "null":
        finish = None
    content = str(result.get("content") or "")
    reasoning = str(result.get("reasoning_content") or "")
    content_empty = content.strip() == ""
    reasoning_empty = reasoning.strip() == ""
    tool_calls = result.get("tool_calls") or []
    has_tools = bool(tool_calls) and any(
        (tc.get("function") or {}).get("name") or (tc.get("function") or {}).get("arguments")
        for tc in tool_calls
        if isinstance(tc, dict)
    )
    args_ok = tool_call_args_complete(tool_calls)
    arg_stats = tool_call_arg_stats(tool_calls)
    got_done = bool(result.get("got_done"))
    transport_error = bool(result.get("error"))
    sse_error = bool(result.get("sse_error"))
    truncated = bool(result.get("truncated_by_client"))
    chunk_count = int(result.get("chunk_count") or 0)
    http_status = int(result.get("http_status") or 0)
    duration_ms = int(result.get("duration_ms") or 0)
    completion_tokens = result.get("completion_tokens")
    try:
        completion_tokens_n = int(completion_tokens) if completion_tokens is not None else None
    except (TypeError, ValueError):
        completion_tokens_n = None

    history = result.get("finish_reason_history") or []
    history_norm = []
    for item in history:
        if item is None or item == "null":
            continue
        s = str(item).strip()
        if s:
            history_norm.append(s)
    unique_finishes = sorted(set(history_norm))

    prep = result.get("prep") if isinstance(result.get("prep"), dict) else {}
    forced_long = bool(prep.get("force_long_tool_args"))

    ok_finishes = {"stop", "tool_calls", "length", "content_filter"}
    terminal = finish in ok_finishes

    anomalies: List[str] = []

    if transport_error or sse_error or http_status >= 400:
        # http>=400 通常已写入 error；仍显式归入传输类
        anomalies.append("transport_or_sse_error")
    if truncated:
        anomalies.append("truncated_by_client")

    hit_issue1 = finish == "error" or "error" in unique_finishes
    if hit_issue1:
        anomalies.append("finish_reason_error")

    # issue2：全程 null 且无正文（历史空 content 断流）
    hit_issue2 = (
        finish is None
        and content_empty
        and not has_tools
        and chunk_count > 0
        and not truncated
    )
    if hit_issue2:
        anomalies.append("null_empty_content")

    hit_tool_args_trunc = bool(has_tools and (not args_ok) and finish == "length")
    if hit_tool_args_trunc:
        anomalies.append("tool_args_truncated_by_length")
    if has_tools and not args_ok and not hit_tool_args_trunc:
        anomalies.append("incomplete_tool_call_json")
    if finish == "length":
        anomalies.append("finish_reason_length")

    if finish == "tool_calls" and not has_tools:
        anomalies.append("tool_calls_finish_without_tools")

    # 收尾异常：没有任何非 null finish_reason（含「有正文/工具碎片 + [DONE]」）
    # 注意：中继在上游未发 [DONE] 时可能补发 [DONE]，会表现为 got_done=True 但仍 null
    if finish is None and not hit_issue2 and chunk_count > 0 and not truncated and not transport_error:
        anomalies.append("finish_reason_null")
    elif finish is None and not hit_issue2 and got_done and not truncated:
        anomalies.append("finish_reason_null")

    if not got_done and chunk_count > 0 and not truncated and not transport_error:
        anomalies.append("missing_done")
    if len(unique_finishes) > 1:
        anomalies.append("conflicting_finish_reasons")

    if forced_long and not has_tools and finish in {None, "stop", "content_filter"} and not truncated:
        anomalies.append("forced_tool_missing")

    if (
        duration_ms >= STALL_DURATION_MS
        and completion_tokens_n is not None
        and completion_tokens_n <= STALL_MAX_COMPLETION_TOKENS
        and not truncated
    ):
        anomalies.append("suspected_upstream_stall")

    if finish == "content_filter":
        anomalies.append("finish_reason_content_filter")
    if finish is not None and finish not in ok_finishes and finish != "error":
        anomalies.append("abnormal_finish_reason")
    if finish == "stop" and content_empty and reasoning_empty and not has_tools:
        anomalies.append("stop_with_empty_output")

    # 去重并按优先级排序
    seen = set()
    ordered: List[str] = []
    for name in ANOMALY_PRIORITY:
        if name in anomalies and name not in seen:
            ordered.append(name)
            seen.add(name)
    for name in anomalies:
        if name not in seen:
            ordered.append(name)
            seen.add(name)

    unhealthy_reason = ordered[0] if ordered else ""
    interrupted = (not terminal) or (not got_done and finish is None)

    return {
        "hit_issue1_finish_reason_error": hit_issue1,
        "hit_issue2_null_empty_content": hit_issue2,
        "hit_tool_args_truncated_by_length": hit_tool_args_trunc,
        "hit_finish_reason_null": "finish_reason_null" in ordered,
        "hit_finish_reason_length": "finish_reason_length" in ordered,
        "anomalies": ordered,
        "interrupted": interrupted,
        "content_empty": content_empty,
        "has_tool_calls": has_tools,
        "tool_call_args_complete": args_ok,
        "tool_args_chars_total": arg_stats["tool_args_chars_total"],
        "tool_args_chars_max": arg_stats["tool_args_chars_max"],
        "got_done": got_done,
        "terminal_finish_reason": terminal,
        "transport_or_sse_error": transport_error or sse_error,
        "healthy": unhealthy_reason == "",
        "unhealthy_reason": unhealthy_reason,
    }


def open_stream(url: str, api_key: str, body: Dict[str, Any], connect_timeout: float, extra_headers: Dict[str, str]):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    req.add_header("Authorization", "Bearer " + normalize_api_key(api_key))
    for k, v in (extra_headers or {}).items():
        if k and v:
            req.add_header(str(k), str(v))
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    return opener.open(req, timeout=connect_timeout)


def run_one(
    case: Dict[str, str],
    worker_id: int,
    base_payload: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    url = str(cfg["url"]).strip()
    api_key = str(cfg["api_key"]).strip()
    read_timeout = float(cfg["read_timeout"])
    connect_timeout = float(cfg["connect_timeout"])
    extra_headers = cfg.get("extra_headers") or {}
    payload, prep_meta = prepare_payload_for_run(base_payload, cfg, worker_id)

    t0 = time.time()
    deadline = t0 + read_timeout
    last_packets: deque[str] = deque(maxlen=5)
    content = ""
    reasoning = ""
    finish_reason: Optional[str] = None
    finish_reason_history: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    usage: Any = None
    chunk_count = 0
    got_done = False
    sse_error: Any = None
    error = ""
    status = 0
    headers: Dict[str, str] = {}
    truncated_by_client = False

    try:
        resp = open_stream(url, api_key, payload, connect_timeout, extra_headers)
        status = int(getattr(resp, "status", 200) or 200)
        headers = headers_to_dict(getattr(resp, "headers", None))
        if status >= 400:
            text = resp.read().decode("utf-8", errors="replace")
            error = "http_%s: %s" % (status, text[:2000])
            if text.strip():
                last_packets.append(text[:8000])
        else:
            while True:
                now = time.time()
                if now >= deadline:
                    truncated_by_client = True
                    error = "client_read_timeout: exceeded %.0fs" % read_timeout
                    break
                remain = max(0.1, deadline - now)
                set_socket_timeout(resp, remain)
                try:
                    line_b = resp.readline()
                except Exception as exc:  # noqa: BLE001
                    elapsed = time.time() - t0
                    if elapsed >= read_timeout - 0.5:
                        truncated_by_client = True
                        error = "client_read_timeout: %s" % exc
                    else:
                        error = "stream_read_error: %s" % exc
                    break
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="replace").rstrip("\r\n")
                data = parse_sse_data_line(line)
                if data is None:
                    continue
                last_packets.append(data)
                chunk_count += 1
                if data == "[DONE]":
                    got_done = True
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("error"):
                    sse_error = obj.get("error")
                    error = "sse_error: %s" % json.dumps(obj.get("error"), ensure_ascii=False)[:1500]
                    continue
                r_delta, c_delta, fr, tc, usg = extract_choice_fields(obj)
                if r_delta:
                    reasoning += r_delta
                if c_delta:
                    content += c_delta
                if fr:
                    finish_reason = fr
                    finish_reason_history.append(fr)
                merge_tool_calls(tool_calls, tc)
                if usg:
                    usage = usg
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        headers = headers_to_dict(getattr(exc, "headers", None))
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        error = "http_%s: %s" % (status, (body or str(exc))[:2000])
        if body:
            last_packets.append(body[:8000])
    except Exception as exc:  # noqa: BLE001
        error = "request_failed: %s" % exc
        if not last_packets:
            last_packets.append(traceback.format_exc()[-2000:])

    elapsed_ms = int((time.time() - t0) * 1000)
    arg_stats = tool_call_arg_stats(tool_calls)
    cached_tokens = None
    prompt_tokens = None
    completion_tokens = None
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict) and details.get("cached_tokens") is not None:
            cached_tokens = details.get("cached_tokens")
        elif usage.get("cached_tokens") is not None:
            cached_tokens = usage.get("cached_tokens")

    result = {
        "case_id": case["id"],
        "payload_file": case.get("payload_file") or "",
        "worker_id": worker_id,
        "prep": prep_meta,
        "http_status": status,
        "response_headers": headers,
        "duration_ms": elapsed_ms,
        "chunk_count": chunk_count,
        "got_done": got_done,
        "finish_reason": finish_reason,
        "finish_reason_history": finish_reason_history,
        "content": content,
        "content_chars": len(content),
        "reasoning_content": reasoning,
        "reasoning_chars": len(reasoning),
        "tool_calls": tool_calls,
        "tool_args_chars_total": arg_stats["tool_args_chars_total"],
        "tool_args_chars_max": arg_stats["tool_args_chars_max"],
        "usage": usage,
        "cached_tokens": cached_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "last_5_packets": list(last_packets),
        "sse_error": sse_error,
        "error": error,
        "truncated_by_client": truncated_by_client,
    }
    result["verdict"] = classify_run(result)
    return result


def clip(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated %d chars]..." % (len(text) - limit)


def render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Kimi K3 入参回放报告")
    lines.append("")
    lines.append("- 开始时间: %s" % report["started_at"])
    lines.append("- 结束时间: %s" % report["finished_at"])
    lines.append("- URL: `%s`" % report["url"])
    files = report.get("input_files") or []
    lines.append("- 入参: %s" % (", ".join("`%s`" % p for p in files) if files else "（未记录）"))
    lines.append("- 每文件次数: %s" % report.get("repeat", report["concurrency"]))
    lines.append("- 并发: %s" % report["concurrency"])
    lines.append("- 读超时: %ss" % report["read_timeout"])
    lines.append("- connect 超时: %ss" % report.get("connect_timeout"))
    lines.append("- bust_cache: %s" % report.get("bust_cache"))
    lines.append("- force_long_tool_args: %s" % report.get("force_long_tool_args"))
    lines.append("- max_tokens override: %s" % report.get("max_tokens"))
    lines.append("- target_tool_arg_chars: %s" % report.get("target_tool_arg_chars"))
    lines.append("- tool_choice: %s" % (report.get("tool_choice") or "(入参原样)"))
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append(
        "| 入参 | **不健康** | 健康 | error | null+空content | **finish_null** | length | length+args截断 | 工具JSON残缺 | 其它 |"
    )
    lines.append(
        "|------|------------|------|-------|----------------|-----------------|--------|-----------------|--------------|------|"
    )
    for case in report["cases"]:
        s = case["stats"]
        lines.append(
            "| %s | **%d/%d** | %d | %d | %d | %d | %d | %d | %d | %d |"
            % (
                case["id"],
                s.get("unhealthy", 0),
                s["total"],
                s.get("healthy", 0),
                s.get("hit_issue1", 0),
                s.get("hit_issue2", 0),
                s.get("finish_reason_null", 0),
                s.get("finish_length", 0),
                s.get("tool_args_truncated_by_length", 0),
                s.get("incomplete_tool_call_json", 0),
                s.get("other_unhealthy", 0),
            )
        )
    lines.append("")
    lines.append(
        "判定：每次请求可命中多类异常（见 `verdict.anomalies`）；`unhealthy_reason` 取优先级最高的一类。"
    )
    lines.append(
        "- 原问题：`finish_reason_error` / `null_empty_content` / `finish_reason_length` / "
        "`tool_args_truncated_by_length`（length + arguments 非法 JSON，32k 典型）"
    )
    lines.append(
        "- 新问题：`finish_reason_null`（有输出或 `[DONE]` 但全程无非 null finish；"
        "中继可能在上游未发 `[DONE]` 时补发）"
    )
    lines.append(
        "- 其它：`incomplete_tool_call_json` / `tool_calls_finish_without_tools` / `missing_done` / "
        "`forced_tool_missing` / `suspected_upstream_stall`（≥10min 且 completion≤1）/ "
        "`conflicting_finish_reasons` / 传输失败与客户端截断等"
    )
    lines.append("")

    for case in report["cases"]:
        lines.append("## %s" % case["id"])
        lines.append("")
        lines.append("- 文件: `%s`" % (case.get("payload_file") or (case.get("input") or {}).get("payload_file") or ""))
        lines.append("- 健康 **%d** / 不健康 **%d** / 共 %d" % (
            case["stats"].get("healthy", 0),
            case["stats"].get("unhealthy", 0),
            case["stats"]["total"],
        ))
        reasons = case["stats"].get("reason_counts") or {}
        if reasons:
            lines.append("- 异常分布: %s" % json.dumps(reasons, ensure_ascii=False))
        lines.append("")
        lines.append("### 输入摘要")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(case["input"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        for run in case["runs"]:
            v = run["verdict"]
            health = "健康" if v.get("healthy") else "不健康(%s)" % (v.get("unhealthy_reason") or "unknown")
            lines.append("### worker-%02d  %s" % (run["worker_id"], health))
            lines.append("")
            lines.append("- HTTP: %s" % run.get("http_status"))
            lines.append("- 耗时: %s ms" % run.get("duration_ms"))
            lines.append("- finish_reason: `%s`" % run.get("finish_reason"))
            lines.append("- finish_reason 历史: %s" % (run.get("finish_reason_history") or []))
            lines.append("- content_chars: %s" % run.get("content_chars"))
            lines.append("- reasoning_chars: %s" % run.get("reasoning_chars"))
            lines.append(
                "- tool_args_chars: total=%s max=%s"
                % (run.get("tool_args_chars_total"), run.get("tool_args_chars_max"))
            )
            lines.append(
                "- tokens: prompt=%s cached=%s completion=%s"
                % (run.get("prompt_tokens"), run.get("cached_tokens"), run.get("completion_tokens"))
            )
            lines.append("- prep: %s" % json.dumps(run.get("prep") or {}, ensure_ascii=False))
            lines.append("- tool_calls: %s" % json.dumps(run.get("tool_calls") or [], ensure_ascii=False)[:500])
            lines.append("- got_done: %s" % run.get("got_done"))
            lines.append("- chunk_count: %s" % run.get("chunk_count"))
            lines.append("- error: %s" % (run.get("error") or "-"))
            lines.append("- truncated_by_client: %s" % run.get("truncated_by_client"))
            lines.append("- anomalies: %s" % json.dumps(v.get("anomalies") or [], ensure_ascii=False))
            lines.append("- verdict: `%s`" % json.dumps(v, ensure_ascii=False))
            lines.append("")
            lines.append("#### response headers")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(run.get("response_headers") or {}, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
            lines.append("#### 输出末 5 包")
            lines.append("")
            packets = run.get("last_5_packets") or []
            if not packets:
                lines.append("(无 SSE 包)")
                lines.append("")
            else:
                for i, pkt in enumerate(packets, 1):
                    lines.append("```")
                    lines.append("# packet %d/%d" % (i, len(packets)))
                    lines.append(clip(str(pkt), 8000))
                    lines.append("```")
                    lines.append("")
            if run.get("content_head") or run.get("content_tail"):
                if run.get("content_head"):
                    lines.append("#### 聚合 content 开头")
                    lines.append("")
                    lines.append("```")
                    lines.append(str(run.get("content_head") or ""))
                    lines.append("```")
                    lines.append("")
                if run.get("content_tail"):
                    lines.append("#### 聚合 content 末尾")
                    lines.append("")
                    lines.append("```")
                    lines.append(str(run.get("content_tail") or ""))
                    lines.append("```")
                    lines.append("")
            elif run.get("content"):
                lines.append("#### 聚合 content")
                lines.append("")
                lines.append("```")
                lines.append(str(run.get("content") or ""))
                lines.append("```")
                lines.append("")
            if run.get("reasoning_content_head") or run.get("reasoning_content_tail"):
                if run.get("reasoning_content_head"):
                    lines.append("#### 聚合 reasoning 开头")
                    lines.append("")
                    lines.append("```")
                    lines.append(str(run.get("reasoning_content_head") or ""))
                    lines.append("```")
                    lines.append("")
                if run.get("reasoning_content_tail"):
                    lines.append("#### 聚合 reasoning 末尾")
                    lines.append("")
                    lines.append("```")
                    lines.append(str(run.get("reasoning_content_tail") or ""))
                    lines.append("```")
                    lines.append("")
            elif run.get("reasoning_content"):
                lines.append("#### 聚合 reasoning_content 末尾")
                lines.append("")
                rc = str(run.get("reasoning_content") or "")
                tail = rc[-1500:] if len(rc) > 1500 else rc
                lines.append("```")
                lines.append(tail)
                lines.append("```")
                lines.append("")
    return "\n".join(lines) + "\n"


def case_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "total": len(runs),
        "hit_issue1": 0,
        "hit_issue2": 0,
        "finish_reason_null": 0,
        "finish_length": 0,
        "incomplete_tool_call_json": 0,
        "tool_args_truncated_by_length": 0,
        "forced_tool_missing": 0,
        "suspected_upstream_stall": 0,
        "other_unhealthy": 0,
        "healthy": 0,
        "unhealthy": 0,
        "reason_counts": {},
        "anomaly_counts": {},
        "cached_tokens_avg": None,
        "tool_args_chars_max_seen": 0,
    }
    reasons: Dict[str, int] = {}
    anomaly_counts: Dict[str, int] = {}
    cached_vals: List[float] = []
    max_args = 0
    core_named = set(NAMED_ANOMALIES)
    for run in runs:
        v = run.get("verdict") or {}
        reason = str(v.get("unhealthy_reason") or "")
        anomalies = v.get("anomalies") or []
        if not isinstance(anomalies, list):
            anomalies = [reason] if reason else []
        for a in anomalies:
            key = str(a)
            if not key:
                continue
            anomaly_counts[key] = anomaly_counts.get(key, 0) + 1
        if v.get("hit_issue1_finish_reason_error") or "finish_reason_error" in anomalies:
            stats["hit_issue1"] += 1
        if v.get("hit_issue2_null_empty_content") or "null_empty_content" in anomalies:
            stats["hit_issue2"] += 1
        if v.get("hit_finish_reason_null") or "finish_reason_null" in anomalies:
            stats["finish_reason_null"] += 1
        if (
            run.get("finish_reason") == "length"
            or "finish_reason_length" in anomalies
            or reason == "finish_reason_length"
        ):
            stats["finish_length"] += 1
        if "incomplete_tool_call_json" in anomalies or reason == "incomplete_tool_call_json":
            stats["incomplete_tool_call_json"] += 1
        if (
            "tool_args_truncated_by_length" in anomalies
            or v.get("hit_tool_args_truncated_by_length")
            or reason == "tool_args_truncated_by_length"
        ):
            stats["tool_args_truncated_by_length"] += 1
        if "forced_tool_missing" in anomalies:
            stats["forced_tool_missing"] += 1
        if "suspected_upstream_stall" in anomalies:
            stats["suspected_upstream_stall"] += 1
        arg_max = int(run.get("tool_args_chars_max") or v.get("tool_args_chars_max") or 0)
        if arg_max > max_args:
            max_args = arg_max
        cached = run.get("cached_tokens")
        if cached is not None:
            try:
                cached_vals.append(float(cached))
            except (TypeError, ValueError):
                pass
        if v.get("healthy"):
            stats["healthy"] += 1
        else:
            stats["unhealthy"] += 1
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
            # 其它 = 未命中「核心命名异常」集合的不健康次数
            if not any(a in core_named for a in anomalies) and reason not in core_named:
                stats["other_unhealthy"] += 1
    stats["reason_counts"] = reasons
    stats["anomaly_counts"] = anomaly_counts
    stats["tool_args_chars_max_seen"] = max_args
    if cached_vals:
        stats["cached_tokens_avg"] = round(sum(cached_vals) / len(cached_vals), 1)
    return stats


def failed_run(case: Dict[str, str], worker_id: int, err: str) -> Dict[str, Any]:
    result = {
        "case_id": case["id"],
        "payload_file": case.get("payload_file") or "",
        "worker_id": worker_id,
        "prep": {},
        "http_status": 0,
        "response_headers": {},
        "duration_ms": 0,
        "chunk_count": 0,
        "got_done": False,
        "finish_reason": None,
        "finish_reason_history": [],
        "content": "",
        "content_chars": 0,
        "reasoning_content": "",
        "reasoning_chars": 0,
        "tool_calls": [],
        "tool_args_chars_total": 0,
        "tool_args_chars_max": 0,
        "usage": None,
        "cached_tokens": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "last_5_packets": [],
        "sse_error": None,
        "error": err,
        "truncated_by_client": False,
    }
    result["verdict"] = classify_run(result)
    return result


def print_run_line(result: Dict[str, Any]) -> None:
    v = result["verdict"]
    anomalies = v.get("anomalies") or []
    print(
        "  worker-%02d healthy=%s reason=%s anomalies=%s finish=%s args=%s/%s cached=%s content=%s reasoning=%s chunks=%s done=%s dur=%sms err=%s"
        % (
            result["worker_id"],
            "Y" if v.get("healthy") else "N",
            v.get("unhealthy_reason") or "-",
            ",".join(anomalies) if anomalies else "-",
            result.get("finish_reason"),
            result.get("tool_args_chars_max"),
            result.get("tool_args_chars_total"),
            result.get("cached_tokens"),
            result.get("content_chars"),
            result.get("reasoning_chars"),
            result.get("chunk_count"),
            result.get("got_done"),
            result.get("duration_ms"),
            (result.get("error") or "-")[:80],
        )
    )


def case_id_from_path(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def list_fixture_jsons() -> List[str]:
    if not os.path.isdir(FIXTURE_DIR):
        return []
    out: List[str] = []
    for name in sorted(os.listdir(FIXTURE_DIR)):
        if name.endswith(".json") and not name.startswith("."):
            out.append(os.path.join(FIXTURE_DIR, name))
    return out


def resolve_input_path(raw: str) -> str:
    path = os.path.expanduser(str(raw or "").strip())
    if not path:
        raise SystemExit("入参路径为空")
    candidates = []
    if os.path.isabs(path):
        candidates.append(path)
    else:
        candidates.append(os.path.abspath(path))
        candidates.append(os.path.join(FIXTURE_DIR, path))
        candidates.append(os.path.join(FIXTURE_DIR, os.path.basename(path)))
    if not path.endswith(".json"):
        for c in list(candidates):
            candidates.append(c + ".json")
        candidates.append(os.path.join(FIXTURE_DIR, os.path.basename(path) + ".json"))
    seen = set()
    for c in candidates:
        ap = os.path.abspath(c)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.isfile(ap):
            return ap
    raise SystemExit("找不到入参文件: %s" % raw)


def make_case(path: str) -> Dict[str, str]:
    path = os.path.abspath(path)
    cid = case_id_from_path(path)
    return {"id": cid, "title": cid, "payload_file": path}


def select_cases(cfg: Dict[str, Any]) -> List[Dict[str, str]]:
    files: List[str] = []
    for raw in cfg.get("cli_inputs") or []:
        files.append(resolve_input_path(str(raw)))
    if not files:
        for raw in cfg.get("inputs") or []:
            files.append(resolve_input_path(str(raw)))
    if not files:
        files = list_fixture_jsons()
    if not files:
        raise SystemExit("没有入参 JSON。请用位置参数 / --input 指定文件，或放到 %s" % FIXTURE_DIR)
    seen = set()
    cases: List[Dict[str, str]] = []
    for path in files:
        ap = os.path.abspath(path)
        if ap in seen:
            continue
        seen.add(ap)
        cases.append(make_case(ap))
    return cases


def parse_args(cfg: Dict[str, Any]) -> Dict[str, Any]:
    parser = argparse.ArgumentParser(description="回放 kimi-k3 JSON 入参并扫描异常")
    parser.add_argument("files", nargs="*", help="JSON 入参文件（相对/绝对路径，或 scripts/inputs 下的文件名）")
    parser.add_argument("--list", action="store_true", help="列出 scripts/inputs 下的 JSON 后退出")
    parser.add_argument("--input", "-i", action="append", default=[], dest="inputs", help="JSON 入参，可重复")
    parser.add_argument("--only", default=None, help="兼容旧用法：一个文件名或路径")
    parser.add_argument("--concurrency", type=int, default=None, help="同一入参并发数，1=串行")
    parser.add_argument("--repeat", type=int, default=None, help="每个入参跑几次")
    parser.add_argument("--connect-timeout", type=int, default=None, help="等响应头/首包超时秒数，默认 300")
    parser.add_argument("--read-timeout", type=int, default=None, help="SSE 读超时秒数，默认 3600")
    parser.add_argument("--max-tokens", type=int, default=None, help="覆盖入参 max_tokens；测 32k 截断建议 32768")
    parser.add_argument(
        "--bust-cache",
        action="store_true",
        help="每次请求插入随机 nonce，降低 prefix cache 命中",
    )
    parser.add_argument(
        "--force-long-tool-args",
        action="store_true",
        help="逼超长 tool arguments（默认 hard：嵌入定长 blob 并只保留 write/edit）",
    )
    parser.add_argument(
        "--soft-long-tool-args",
        action="store_true",
        help="force-long 用 soft 模式（只追加文字指令，不替换对话；易被忽略）",
    )
    parser.add_argument(
        "--target-tool-arg-chars",
        type=int,
        default=None,
        help="嵌入/要求的 contents 字符数，默认 40000；建议 36000 贴 32k",
    )
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        help="去掉 thinking/reasoning_effort，让额度留给 tool arguments",
    )
    parser.add_argument(
        "--keep-thinking",
        action="store_true",
        help="hard 模式下仍保留原 thinking（默认 hard 会关掉）",
    )
    parser.add_argument(
        "--tool-choice",
        choices=["required", "write"],
        default=None,
        help="强制工具调用：required=必须调工具；write=强制调用 write/edit 类函数（测 32k 推荐 write）",
    )
    args = parser.parse_args()
    if args.list:
        files = list_fixture_jsons()
        if not files:
            print("scripts/inputs 下没有 JSON:", FIXTURE_DIR)
        else:
            print("可用入参:")
            for path in files:
                print("  %s" % path)
        raise SystemExit(0)
    cli_inputs: List[str] = []
    cli_inputs.extend(args.files or [])
    cli_inputs.extend(args.inputs or [])
    if args.only:
        cli_inputs.append(args.only)
    cfg["cli_inputs"] = cli_inputs
    if args.concurrency is not None:
        cfg["concurrency"] = args.concurrency
    if args.repeat is not None:
        cfg["repeat"] = args.repeat
    if args.connect_timeout is not None:
        cfg["connect_timeout"] = args.connect_timeout
    if args.read_timeout is not None:
        cfg["read_timeout"] = args.read_timeout
    if args.max_tokens is not None:
        cfg["max_tokens"] = args.max_tokens
    if args.bust_cache:
        cfg["bust_cache"] = True
    if args.force_long_tool_args:
        cfg["force_long_tool_args"] = True
    if args.soft_long_tool_args:
        cfg["force_long_tool_args"] = True
        cfg["force_long_tool_args_mode"] = "soft"
    if args.target_tool_arg_chars is not None:
        cfg["target_tool_arg_chars"] = args.target_tool_arg_chars
    if args.disable_thinking:
        cfg["disable_thinking"] = True
    if args.keep_thinking:
        cfg["keep_thinking"] = True
    if args.tool_choice:
        cfg["tool_choice"] = args.tool_choice
    return cfg


def run_case_workers(
    case: Dict[str, str],
    payload: Dict[str, Any],
    cfg: Dict[str, Any],
    repeat: int,
    concurrency: int,
) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    if concurrency <= 1:
        for i in range(repeat):
            try:
                result = run_one(case, i + 1, payload, cfg)
            except Exception as exc:  # noqa: BLE001
                result = failed_run(case, i + 1, "worker_crash: %s" % exc)
            runs.append(result)
            print_run_line(result)
        return runs

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {
            pool.submit(run_one, case, i + 1, payload, cfg): i + 1
            for i in range(repeat)
        }
        for fut in as_completed(futs):
            worker_id = futs[fut]
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                result = failed_run(case, worker_id, "worker_crash: %s" % exc)
            runs.append(result)
            print_run_line(result)
    runs.sort(key=lambda r: int(r.get("worker_id") or 0))
    return runs


def slim_run_for_json(run: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(run)
    rc = str(out.get("reasoning_content") or "")
    if len(rc) > 4000:
        out["reasoning_content_head"] = rc[:2000]
        out["reasoning_content_tail"] = rc[-2000:]
        out.pop("reasoning_content", None)
    content = str(out.get("content") or "")
    if len(content) > 8000:
        out["content_head"] = content[:4000]
        out["content_tail"] = content[-4000:]
        out.pop("content", None)
    return out


def main() -> int:
    cfg = parse_args(dict(CONFIG))
    url = str(cfg.get("url") or "").strip()
    api_key = str(cfg.get("api_key") or "").strip()
    if not url:
        print("请先在脚本 CONFIG 里填写 url", file=sys.stderr)
        return 2
    if not api_key:
        print("请先在脚本 CONFIG 里填写 api_key", file=sys.stderr)
        return 2

    selected = select_cases(cfg)
    missing = [c["payload_file"] for c in selected if not os.path.isfile(c["payload_file"])]
    if missing:
        print("缺少入参文件:", file=sys.stderr)
        for path in missing:
            print("  -", path, file=sys.stderr)
        print("请指定 JSON 路径，或把文件放到", FIXTURE_DIR, file=sys.stderr)
        return 2

    concurrency = max(1, int(cfg["concurrency"]))
    repeat = max(1, int(cfg.get("repeat") or concurrency))
    started = datetime.now().astimezone()
    stamp = started.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(SCRIPT_DIR, "..", "temp", "kimi_k3_sep2_replay_%s" % stamp)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    report: Dict[str, Any] = {
        "started_at": started.isoformat(timespec="seconds"),
        "url": url,
        "input_files": [c["payload_file"] for c in selected],
        "repeat": repeat,
        "concurrency": concurrency,
        "read_timeout": cfg["read_timeout"],
        "connect_timeout": cfg["connect_timeout"],
        "max_tokens": cfg.get("max_tokens"),
        "bust_cache": bool(cfg.get("bust_cache")),
        "force_long_tool_args": bool(cfg.get("force_long_tool_args")),
        "force_long_tool_args_mode": cfg.get("force_long_tool_args_mode") or "hard",
        "target_tool_arg_chars": cfg.get("target_tool_arg_chars"),
        "disable_thinking": bool(cfg.get("disable_thinking")),
        "keep_thinking": bool(cfg.get("keep_thinking")),
        "tool_choice": cfg.get("tool_choice") or "",
        "cases": [],
    }

    print("报告目录:", out_dir)
    print("url:", url)
    print("inputs:", ", ".join(c["payload_file"] for c in selected))
    print("repeat:", repeat)
    print("concurrency:", concurrency, "(1=串行)" if concurrency == 1 else "")
    print("bust_cache:", bool(cfg.get("bust_cache")))
    print("force_long_tool_args:", bool(cfg.get("force_long_tool_args")),
          "mode=", cfg.get("force_long_tool_args_mode") or "hard")
    print("max_tokens override:", cfg.get("max_tokens"))
    print("target_tool_arg_chars:", cfg.get("target_tool_arg_chars"))
    print("keep_thinking:", bool(cfg.get("keep_thinking")))
    print("tool_choice:", cfg.get("tool_choice") or "(入参原样)")
    print("")

    for case in selected:
        payload = load_payload(case["payload_file"])
        input_summary = summarize_input(payload, case["payload_file"])
        mode = "串行" if concurrency <= 1 else ("%d 并发" % concurrency)
        print("==== %s  %s x%d ====" % (case["payload_file"], mode, repeat))
        print("  chars=%s messages=%s tools=%s" % (
            input_summary["char_count"],
            input_summary["message_count"],
            input_summary["tool_count"],
        ))
        runs = run_case_workers(case, payload, cfg, repeat, concurrency)
        case_report = {
            "id": case["id"],
            "payload_file": case["payload_file"],
            "input": input_summary,
            "stats": case_stats(runs),
            "runs": [slim_run_for_json(r) for r in runs],
        }
        report["cases"].append(case_report)
        print(
            "==== %s 结束  健康 %d/%d  不健康 %d  args_max_seen=%s  cached_avg=%s  主因 %s  全量异常 %s ====\n"
            % (
                case["id"],
                case_report["stats"].get("healthy", 0),
                case_report["stats"]["total"],
                case_report["stats"].get("unhealthy", 0),
                case_report["stats"].get("tool_args_chars_max_seen"),
                case_report["stats"].get("cached_tokens_avg"),
                json.dumps(case_report["stats"].get("reason_counts") or {}, ensure_ascii=False),
                json.dumps(case_report["stats"].get("anomaly_counts") or {}, ensure_ascii=False),
            )
        )

    report["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    md_path = os.path.join(out_dir, "report.md")
    json_path = os.path.join(out_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    print("JSON:", json_path)
    print("Markdown:", md_path)

    unhealthy = sum(int((c.get("stats") or {}).get("unhealthy") or 0) for c in report["cases"])
    if unhealthy:
        print(
            "有 %d 次不健康（error / length / 32k-args / finish_null / 传输失败等），退出码 1"
            % unhealthy
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
