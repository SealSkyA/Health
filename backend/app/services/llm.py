"""OpenAI 兼容 LLM 调用封装（chat/completions + function calling）。"""
import json
import socket
import threading
import time
import urllib.error
import urllib.request

from fastapi import HTTPException


class AgentCancelled(Exception):
    """用户主动取消 AI 任务。"""


# 限流/瞬时错误退避等待序列（秒）。用尽后固定取最后一项（60s）；
# 不设重试次数上限——"只要服务器不断开就一直执行"，由调用方通过 cancel_event 主动取消。
BASE_WAITS = (3, 6, 12, 24, 40, 60)
# 兼容旧引用（_stream_reader 退避序列）
RETRY_WAITS = BASE_WAITS

# 可自动重试的 HTTP 状态码（其余如 400/401/404 属于配置问题，直接抛错）
_RETRYABLE_HTTP = (429, 500, 502, 503, 504)


def _wait_or_cancel(wait: float, cancel_event) -> None:
    """等待退避；若 cancel_event 已 set（用户取消）则抛 AgentCancelled。"""
    if cancel_event is not None:
        if cancel_event.wait(wait):
            raise AgentCancelled("用户已取消")
    else:
        time.sleep(wait)


def call_chat(addr: str, api_key: str, model: str, messages: list,
              tools: list | None = None, tool_choice: str | dict | None = None,
              temperature: float = 0.3, timeout: int = 120,
              on_retry=None, cancel_event=None) -> dict:
    """调用 /chat/completions，返回 choices[0].message（dict）。

    限流(429)与瞬时故障(5xx/网络/超时)自动无限退避重试（间隔递增、60s 封顶）；
    复现"慢但能用"体验。on_retry(attempt_no, wait_seconds) 在每次重试前回调（可能是子线程），
    用于向前端推送排队进度；cancel_event（threading.Event）set 后立即中断本轮等待并抛 AgentCancelled。
    """
    if not addr:
        raise HTTPException(status_code=400, detail="该模型未配置接入地址")
    body = {"model": model, "messages": messages, "temperature": temperature}
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    headers = {"Content-Type": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    attempt = 0
    while True:
        attempt += 1
        wait = BASE_WAITS[min(attempt - 1, len(BASE_WAITS) - 1)]
        req = urllib.request.Request(
            addr.rstrip("/") + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read().decode("utf-8"))
        except HTTPException:
            raise
        except urllib.error.HTTPError as e:
            if e.code in _RETRYABLE_HTTP:
                if on_retry:
                    try:
                        on_retry(attempt, wait)
                    except Exception:
                        pass
                _wait_or_cancel(wait, cancel_event)
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise HTTPException(status_code=502, detail=f"AI 服务返回 {e.code}：{detail}")
        except (urllib.error.URLError, OSError, socket.timeout, TimeoutError) as ex:
            # 网络抖动 / 连接重置 / 响应超时：同样自动重试
            if on_retry:
                try:
                    on_retry(attempt, wait)
                except Exception:
                    pass
            _wait_or_cancel(wait, cancel_event)
            continue
        except Exception as ex:
            raise HTTPException(status_code=502, detail=f"AI 服务调用失败：{ex}")
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise HTTPException(status_code=502, detail=f"AI 响应格式异常：{str(data)[:300]}")


def call_chat_stream(addr: str, api_key: str, model: str, messages: list,
                     tools: list | None = None, temperature: float = 0.3, timeout: int = 300,
                     on_event=None, cancel_event=None) -> dict:
    """流式调用 /chat/completions：逐块回调（含推理过程与工具调用），返回完整 message。

    on_event(kind, value) 在流读取线程被回调（需自行线程安全地处理）：
      ("delta", str)          正文增量
      ("think", str)          推理过程增量（reasoning_content / reasoning）
      ("reset", dict)         网络中断：本调用实际已流出的字符数 {"content": n, "think": m}，
                              前端应将已拼接文本截断到该长度再续，避免重试重复
      ("retry", (attempt, w)) 自动退避重试进度（429/5xx/网络抖动）
    返回聚合后的 choices[0].message（tool_calls 的 arguments 已拼接为完整 JSON 字符串）。
    """
    if not addr:
        raise HTTPException(status_code=400, detail="该模型未配置接入地址")
    body = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
    if tools:
        body["tools"] = tools
    headers = {"Content-Type": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    def _cb(kind, val):
        if on_event:
            try:
                on_event(kind, val)
            except Exception:
                pass

    attempt = 0
    while True:
        attempt += 1
        wait = BASE_WAITS[min(attempt - 1, len(BASE_WAITS) - 1)]
        req = urllib.request.Request(
            addr.rstrip("/") + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        content_parts, think_parts = [], []
        tcalls = {}
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            for raw in resp:
                for line in raw.decode("utf-8", "replace").split("\n"):
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except ValueError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    c = delta.get("content")
                    if c:
                        content_parts.append(c)
                        _cb("delta", c)
                    r = delta.get("reasoning_content") or delta.get("reasoning")
                    if r:
                        think_parts.append(r)
                        _cb("think", r)
                    for tc in (delta.get("tool_calls") or []):
                        idx = tc.get("index", 0)
                        slot = tcalls.setdefault(idx, {"id": "", "type": "function",
                                                       "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
            return {
                "content": "".join(content_parts),
                "reasoning_content": "".join(think_parts) or None,
                "tool_calls": [tcalls[i] for i in sorted(tcalls) if tcalls[i]["function"]["name"]],
            }
        except urllib.error.HTTPError as e:
            if e.code in _RETRYABLE_HTTP:
                _cb("retry", (attempt, wait))
                _wait_or_cancel(wait, cancel_event)
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise HTTPException(status_code=502, detail=f"AI 服务返回 {e.code}：{detail}")
        except (urllib.error.URLError, OSError, socket.timeout, TimeoutError) as ex:
            # 已流出的内容通知前端截断（避免重试从头输出造成重复），然后整体重试
            _cb("reset", {"content": sum(len(x) for x in content_parts),
                          "think": sum(len(x) for x in think_parts)})
            _cb("retry", (attempt, wait))
            _wait_or_cancel(wait, cancel_event)
            continue
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(status_code=502, detail=f"AI 服务调用失败：{ex}")


def tool_result_message(tool_call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


__all__ = ["AgentCancelled", "BASE_WAITS", "RETRY_WAITS", "call_chat", "call_chat_stream",
           "tool_result_message", "threading"]