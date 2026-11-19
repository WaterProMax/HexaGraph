from __future__ import annotations

DESIGN_ERROR_CATEGORIES = (
    "connection",
    "auth",
    "rate_limit",
    "timeout",
    "missing_fields",
    "invalid_structure",
    "environment",
)

CATEGORY_TITLES = {
    "connection": "无法连接模型服务，未完成整理",
    "auth": "模型配置或凭据不可用",
    "rate_limit": "模型服务繁忙或请求受限",
    "timeout": "整理超过 10 分钟，未进入设计确认",
    "missing_fields": "文档缺项",
    "invalid_structure": "模型输出未通过结构校验",
    "environment": "本地运行环境错误，未完成整理",
}

_AUTH_STATUSES = {401, 403}
_RATE_STATUSES = {429}
_TIMEOUT_STATUSES = {408, 504}
_CONNECTION_STATUSES = {502, 503}


class Test3Error(Exception):
    code = "TEST3_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class IllegalTransition(Test3Error):
    code = "ILLEGAL_TRANSITION"


class AgentOutputError(Test3Error):
    code = "AGENT_OUTPUT_ERROR"

    def __init__(self, message: str, *, code: str | None = None, category: str | None = None) -> None:
        super().__init__(message, code=code)
        self.category = category


class ConfigError(Test3Error):
    code = "CONFIG_ERROR"


DEEPSEEK_RETIRED_MESSAGE = (
    "DeepSeek 专用入口已下线，未发起请求；该历史运行仅支持只读查看，不支持继续调用。"
)


class DeepSeekRetired(Test3Error):
    """Raised when a retired DeepSeek-only path would otherwise call a model.

    The message is user-facing and deliberately mentions that no request was sent.
    Historical snapshots keep ``provenance.mode == "deepseek"``; callers must not
    rewrite them into another provider/mode.
    """

    code = "DEEPSEEK_RETIRED"

    def __init__(self, message: str = DEEPSEEK_RETIRED_MESSAGE) -> None:
        super().__init__(message)
        self.category = "deepseek_retired"


class RevisionConflict(Test3Error):
    code = "REVISION_CONFLICT"


class WriteDenied(Test3Error):
    code = "WRITE_DENIED"


class CommandDenied(Test3Error):
    code = "COMMAND_DENIED"


class BudgetExceeded(Test3Error):
    code = "BUDGET_EXCEEDED"


class ReplayMissing(Test3Error):
    code = "REPLAY_MISSING"


class ValidationFailed(Test3Error):
    code = "VALIDATION_FAILED"


class GrantRejected(Test3Error):
    """Grant scope/baseline rejection mapped to contracts C.5.4 HTTP codes."""

    code = "GRANT_REJECTED"

    def __init__(self, category: str, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.category = category
        self.status_code = status_code


class GitHubWriteDenied(Test3Error):
    code = "GITHUB_WRITE_DENIED"


class IsolationUnavailable(Test3Error):
    """No preflighted isolation backend: granted execution must block."""

    code = "ISOLATION_UNAVAILABLE"

    def __init__(
        self,
        message: str,
        *,
        backend: str = "",
        reason: str = "",
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.backend = backend
        self.reason = reason or message
        self.details = dict(details or {})


class EvidenceWriteFailed(Test3Error):
    """Evidence could not be written safely; callers must not report success."""

    code = "EVIDENCE_WRITE_FAILED"


class ImportInProgress(Test3Error):
    code = "IMPORT_IN_PROGRESS"

    def __init__(self, message: str, *, run_id: str, category: str = "import_in_progress") -> None:
        super().__init__(message)
        self.run_id = run_id
        self.category = category


def _walk_exceptions(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_of(exc: BaseException) -> int | None:
    raw = getattr(exc, "status_code", None)
    if raw is None:
        raw = getattr(exc, "status", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def classify_llm_error(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    names: list[str] = []
    texts: list[str] = []
    statuses: list[int] = []
    for item in _walk_exceptions(exc):
        category = getattr(item, "category", None)
        if category in DESIGN_ERROR_CATEGORIES:
            return category
        names.append(type(item).__name__.lower())
        texts.append(str(item).lower()[:240])
        status = _status_of(item)
        if status is not None:
            statuses.append(status)
    name_blob = " ".join(names)
    text_blob = " ".join(texts)
    # 依赖缺失/本机代理配置（如 all_proxy=socks5h:// 但未装 socksio）会在发请求前抛 ImportError，
    # 既不是网络错误也不是模型输出错误，单独归为本地环境问题。
    if isinstance(exc, ImportError) or "importerror" in name_blob or "socksio" in text_blob:
        return "environment"
    if any(status in _AUTH_STATUSES for status in statuses):
        return "auth"
    if any(status in _RATE_STATUSES for status in statuses) or "ratelimit" in name_blob or "rate_limit" in name_blob:
        return "rate_limit"
    if any(status in _TIMEOUT_STATUSES for status in statuses) or "timeout" in name_blob:
        return "timeout"
    if any(status in _CONNECTION_STATUSES for status in statuses):
        return "connection"
    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError, ConnectionAbortedError, ConnectionRefusedError)):
        return "connection"
    if "api_key" in text_blob or "unauthorized" in text_blob or "not configured" in text_blob:
        return "auth"
    if "auth" in name_blob or "permission" in name_blob:
        return "auth"
    if "timeout" in text_blob or "timed out" in text_blob:
        return "timeout"
    if "rate limit" in text_blob or "too many requests" in text_blob:
        return "rate_limit"
    if "connect" in name_blob or "connection" in name_blob:
        return "connection"
    if "connect" in text_blob or "network" in text_blob:
        return "connection"
    if "output invalid" in text_blob or "validationerror" in name_blob:
        return "invalid_structure"
    return None


def user_message_for_category(category: str | None) -> str:
    if not category:
        return ""
    return CATEGORY_TITLES.get(category, "")


def classified_llm_error(exc: BaseException | None) -> AgentOutputError:
    category = classify_llm_error(exc)
    message = user_message_for_error(exc) or "模型调用失败"
    return AgentOutputError(message, category=category)


def user_message_for_error(exc: BaseException | None) -> str:
    """Expose controlled diagnostics, never upstream exception text or credentials."""
    category = classify_llm_error(exc)
    if category == "auth" and exc is not None:
        for item in _walk_exceptions(exc):
            status = _status_of(item)
            if status == 401:
                return "模型服务返回 401：API 密钥无效或已失效，请更新对应服务的 API Key，重启后端后重新提交"
            if status == 403:
                return "模型服务返回 403：当前凭据无权访问，请检查 API Key 的权限与模型访问范围"
    return user_message_for_category(category)
