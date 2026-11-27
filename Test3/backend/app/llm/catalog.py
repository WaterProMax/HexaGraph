"""OpenAI-compatible endpoints of the supported domestic providers.

``dashscope`` is deliberately absent: its base URL stays in ``config/models.yaml``
(``ModelsFile.base_url``) so the existing workbench configuration keeps working.
Keep the ids in sync with ``PROVIDER_CATALOG`` in ``frontend/src/pages/bots/BotForm.tsx``.
"""

from __future__ import annotations

PROVIDER_ENDPOINTS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "minimax": "https://api.minimaxi.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
    "qianfan": "https://qianfan.baidubce.com/v2",
    "stepfun": "https://api.stepfun.com/v1",
}

DEFAULT_PROVIDER = "dashscope"


def is_known_provider(provider_ref: str) -> bool:
    return provider_ref == DEFAULT_PROVIDER or provider_ref in PROVIDER_ENDPOINTS


def endpoint_for(provider_ref: str, default_base_url: str) -> str | None:
    """Base URL for ``provider_ref``; ``default_base_url`` serves dashscope."""
    if provider_ref == DEFAULT_PROVIDER:
        return default_base_url
    return PROVIDER_ENDPOINTS.get(provider_ref)
