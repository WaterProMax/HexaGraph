from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.errors import AgentOutputError, ReplayMissing, classified_llm_error
from app.llm.types import LLMResult
from app.settings import ModelsFile, get_settings


def validate_tool_protocol(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> None:
    if tools:
        for spec in tools:
            fn = spec.get("function") if isinstance(spec, dict) else None
            params = (fn or spec or {}).get("parameters") if isinstance(fn or spec, dict) else None
            if not isinstance(params, dict) or "properties" not in params:
                raise ValueError("tool schema missing properties")
            if params.get("type") != "object":
                raise ValueError("tool schema type must be object")
    pending_ids: set[str] | None = None
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            pending_ids = set()
            for call in message["tool_calls"]:
                call_id = str(call.get("id") or "")
                if not call_id:
                    raise ValueError("assistant tool_calls missing id")
                pending_ids.add(call_id)
            continue
        if role == "tool":
            if not pending_ids:
                raise ValueError("tool message without assistant tool_calls")
            call_id = str(message.get("tool_call_id") or "")
            if not call_id:
                raise ValueError("tool message missing tool_call_id")
            if call_id not in pending_ids:
                raise ValueError("tool_call_id mismatch")
            pending_ids.discard(call_id)
            if not pending_ids:
                pending_ids = None
            continue
        if pending_ids:
            raise ValueError("missing tool responses for assistant tool_calls")
        pending_ids = None


def _item_tokens(item: dict[str, Any]) -> tuple[int, int]:
    return int(item.get("tokens_in") or 0), int(item.get("tokens_out") or 0)


class ScriptedProvider:
    def __init__(self, queue: list[Any] | None = None) -> None:
        self.queue: list[Any] = list(queue or [])
        self.calls: list[dict[str, Any]] = []

    def push(self, item: Any) -> None:
        self.queue.append(item)

    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        self.calls.append({"slot": slot, "messages": messages, "schema": schema, "tools": tools})
        validate_tool_protocol(messages, tools)
        if not self.queue:
            raise RuntimeError(f"scripted queue empty for slot={slot}")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResult):
            return item
        if isinstance(item, dict) and item.get("tool_calls"):
            tokens_in, tokens_out = _item_tokens(item)
            return LLMResult(
                tool_calls=item["tool_calls"],
                parsed=item.get("parsed"),
                text=item.get("text", ""),
                model=slot,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        if isinstance(item, dict):
            tokens_in, tokens_out = _item_tokens(item)
            parsed = {k: v for k, v in item.items() if k not in {"tokens_in", "tokens_out", "tool_calls", "text"}}
            if item.get("parsed") is not None:
                parsed = item["parsed"]
            return LLMResult(
                text=item.get("text") or json.dumps(parsed or item, ensure_ascii=False),
                parsed=parsed or item,
                model=slot,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        return LLMResult(text=str(item), model=slot)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.queue and isinstance(self.queue[0], list):
            return self.queue.pop(0)
        return [[float((sum(ord(c) for c in t) + i) % 13) for i in range(8)] for t in texts]


class DeepSeekProvider:
    """DeepSeek official OpenAI-compatible API, isolated per real-model run."""

    def __init__(self, *, base_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = settings.deepseek_api_key.strip()
        self.base_url = (base_url if base_url is not None else settings.deepseek_base_url).strip().rstrip("/")
        self.timeout_s = max(1.0, float(settings.deepseek_timeout_s))
        self.max_tokens = max(1024, int(settings.deepseek_max_tokens))
        self.trust_env = bool(settings.test3_http_trust_env)

    async def complete(self, slot: str, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        if not self.api_key:
            raise AgentOutputError(
                "未配置 DeepSeek API Key，请在 Test3/.env 填写 DEEPSEEK_API_KEY",
                category="auth",
            )
        if not self.base_url:
            raise AgentOutputError("未配置 DEEPSEEK_BASE_URL", category="connection")
        model = str(kwargs.get("model") or get_settings().deepseek_model)
        validate_tool_protocol(messages, kwargs.get("tools"))
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(kwargs.get("max_tokens") or self.max_tokens),
        }
        for key in ("temperature", "max_tokens", "tools", "tool_choice"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]
        if not kwargs.get("tools"):
            body["response_format"] = {"type": "json_object"}
        if kwargs.get("extra_body"):
            body.update(kwargs["extra_body"])
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, trust_env=self.trust_env) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                if resp.status_code >= 400:
                    self._raise_http_error(resp)
                data = resp.json()
        except AgentOutputError:
            raise
        except httpx.TimeoutException as exc:
            raise AgentOutputError("DeepSeek 请求超时，请稍后重试", category="timeout") from exc
        except httpx.HTTPError as exc:
            raise AgentOutputError("无法连接 DeepSeek，请检查网络与 Base URL", category="connection") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise AgentOutputError("DeepSeek 返回了无法读取的响应", category="invalid_structure") from exc

        try:
            first = data["choices"][0]
            choice = first["message"]
            finish_reason = str(first.get("finish_reason") or "")
            text = choice.get("content") or ""
            calls: list[dict[str, Any]] = []
            for index, item in enumerate(choice.get("tool_calls") or []):
                raw_args = item["function"].get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    arguments = {}
                calls.append(
                    {
                        "id": str(item.get("id") or f"call_{index}"),
                        "type": item.get("type") or "function",
                        "name": item["function"]["name"],
                        "arguments": arguments,
                    }
                )
            try:
                parsed = json.loads(text) if text else None
            except json.JSONDecodeError:
                parsed = None
            usage = data.get("usage") or {}
            return LLMResult(
                text=text,
                parsed=parsed,
                tool_calls=calls,
                tokens_in=int(usage.get("prompt_tokens") or 0),
                tokens_out=int(usage.get("completion_tokens") or 0),
                latency_ms=int((time.perf_counter() - started) * 1000),
                model=str(data.get("model") or model),
                finish_reason=finish_reason,
                raw=data,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AgentOutputError("DeepSeek 响应缺少有效的 message 或 usage", category="invalid_structure") from exc

    def _raise_http_error(self, resp: httpx.Response) -> None:
        category = {
            400: "invalid_structure",
            401: "auth",
            403: "auth",
            402: "rate_limit",
            404: "invalid_structure",
            408: "timeout",
            429: "rate_limit",
        }.get(resp.status_code, "connection" if resp.status_code >= 500 else "invalid_structure")
        try:
            payload = resp.json()
            detail = str((payload.get("error") or {}).get("message") or "")
        except (ValueError, AttributeError):
            detail = ""
        if self.api_key:
            detail = detail.replace(self.api_key, "[REDACTED]")
        messages = {
            "auth": "DeepSeek 认证失败，请检查 DEEPSEEK_API_KEY",
            "rate_limit": "DeepSeek 余额不足或请求受限，请检查账户与限流状态",
            "timeout": "DeepSeek 请求超时，请稍后重试",
            "connection": "DeepSeek 服务暂时不可用，请稍后重试",
            "invalid_structure": "DeepSeek 请求未被接受，请检查模型名、Base URL 与请求参数",
        }
        suffix = f"（{detail[:240]}）" if detail else ""
        error = AgentOutputError(messages[category] + suffix, category=category)
        setattr(error, "status_code", resp.status_code)
        raise error

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AgentOutputError("DeepSeek 真实运行未启用 embedding 阶段", category="invalid_structure")


class ReplayProvider:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.index = 0

    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        self.index += 1
        role = kwargs.get("role") or "unknown"
        path = self.folder / f"{self.index:03d}-{role}.json"
        if not path.exists():
            raise ReplayMissing(f"missing replay {path.name} for role={role} index={self.index}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResult(
            text=data.get("text", json.dumps(data.get("parsed") or {}, ensure_ascii=False)),
            parsed=data.get("parsed"),
            tool_calls=data.get("tool_calls") or [],
            tokens_in=data.get("tokens_in", 0),
            tokens_out=data.get("tokens_out", 0),
            model=data.get("model", slot),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        path = self.folder / "embeddings.json"
        if not path.exists():
            raise ReplayMissing("missing replay embeddings.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data[: len(texts)]


class DashScopeProvider:
    def __init__(self, models: ModelsFile) -> None:
        self.models = models
        self._client = None

    def _client_obj(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI

            settings = get_settings()
            key = settings.dashscope_api_key
            # 【修改点】没有密钥时显式报错，不要带 "missing" 去发请求
            if not key:
                raise AgentOutputError("模型配置或凭据不可用", category="auth")
            # 与 DeepSeekProvider 一致：默认不继承 shell 里的 http(s)_proxy / all_proxy，
            # 避免 socks5h:// 未装 socksio 时在建连接前就失败。
            self._client = AsyncOpenAI(
                base_url=self.models.base_url,
                api_key=key,
                http_client=httpx.AsyncClient(
                    timeout=httpx.Timeout(600.0, connect=10.0),
                    trust_env=bool(settings.test3_http_trust_env),
                ),
            )
        return self._client

    async def complete(
        self,
        slot: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        cfg = self.models.slots[slot]
        started = time.perf_counter()
        extra: dict[str, Any] = {"extra_body": cfg.extra_body} if cfg.extra_body else {}
        if cfg.json_mode:
            extra["response_format"] = {"type": "json_object"}
        
        if tools:
            if cfg.tool_calls:
                extra["tools"] = tools
            else:
                # 【修改点】不支持 tool calls 的模型必须显式报错，不能静默忽略
                raise ValueError(f"Model {cfg.model} for slot {slot} does not support tool_calls (cfg.tool_calls is false).")

        try:
            completion = await self._client_obj().chat.completions.create(
                model=kwargs.get("model") or cfg.model,
                messages=messages,
                temperature=kwargs.get("temperature", cfg.temperature),
                max_tokens=cfg.max_tokens,
                **extra,
            )
        except AgentOutputError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise classified_llm_error(exc) from exc
        choice = completion.choices[0]
        text = choice.message.content or ""
        parsed = None
        try:
            parsed = json.loads(text) if text else None
        except json.JSONDecodeError:
            parsed = None
        usage = completion.usage
        return LLMResult(
            text=text,
            parsed=parsed,
            tool_calls=_dashscope_tool_calls(choice.message),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=completion.model,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        cfg = self.models.slots["embedding"]
        result = await self._client_obj().embeddings.create(model=cfg.model, input=texts)
        return [item.embedding for item in result.data]


def _dashscope_tool_calls(message: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or []):
        raw_args = getattr(getattr(call, "function", None), "arguments", None) or "{}"
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError:
            arguments = {}
        fn = getattr(call, "function", None)
        calls.append(
            {
                "id": getattr(call, "id", None) or f"call_{index}",
                "type": getattr(call, "type", None) or "function",
                "name": getattr(fn, "name", "") if fn is not None else "",
                "arguments": arguments,
            }
        )
    return calls