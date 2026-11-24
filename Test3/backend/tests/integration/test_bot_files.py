from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.bots.files import budget_chars, render_file_slot
from app.llm.gateway import Gateway
from app.llm.types import LLMResult
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.storage.models import BotFileRow

FLAGSHIP_BUDGET = 29491  # 32768-token window * 0.6 * 1.5 chars


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], dict]] = []

    async def complete(self, slot, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return LLMResult(text="好的", model=kwargs.get("model", ""))

    async def embed(self, texts):
        return [[0.0] for _ in texts]


def _app(tmp_path, provider=None):
    app = create_app()
    models = load_models()
    # File budgets derive from each slot's context window. Pin the flagship slot
    # to 32K so these tests stay deterministic when local models.yaml is switched
    # for a run; the coder slot remains the larger-window control below.
    models.slots["flagship"].context_window = 32768
    app.state.workbench = Workbench(
        Gateway(models, provider or FakeProvider(), data_dir=tmp_path),
        RoleRegistry(load_roles()),
        tmp_path,
    )
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


async def _bot(client: AsyncClient, slot: str = "flagship", name: str = "Water") -> str:
    res = await client.post(
        "/api/bots",
        json={
            "display_name": name,
            "role_template": "coder",
            "provider_ref": "dashscope",
            "model": "qwen3.8-max-0902",
            "slot": slot,
            "secret_ref": "DASHSCOPE_API_KEY",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["bot_id"]


async def _upload(client, bot_id, filename, content):
    return await client.post(f"/api/bots/{bot_id}/files", json={"filename": filename, "content": content})


def test_budget_follows_the_context_window():
    assert budget_chars(32768) == FLAGSHIP_BUDGET
    assert budget_chars(65536) == 58982
    assert budget_chars(131072) == 117964
    assert budget_chars(None) == FLAGSHIP_BUDGET


def test_render_uses_a_fence_longer_than_any_backtick_run_in_the_file():
    row = BotFileRow(file_id="f", bot_id="b", filename="a.md", chars=12, content="x ```y``` z", created_at="t")
    text, omitted = render_file_slot([row], 1000)
    assert omitted == 0
    assert "【文件：a.md】\n````\nx ```y``` z\n````" in text


@pytest.mark.asyncio
async def test_upload_list_and_delete_roundtrip(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot_id = await _bot(client)
        empty = await client.get(f"/api/bots/{bot_id}/files")
        assert empty.status_code == 200
        assert empty.json() == {"items": [], "used_chars": 0, "budget_chars": FLAGSHIP_BUDGET}

        res = await _upload(client, bot_id, "notes.md", "# 笔记\n内容")
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["file"]["filename"] == "notes.md"
        assert body["file"]["chars"] == len("# 笔记\n内容")
        assert body["used_chars"] == body["file"]["chars"]
        assert body["budget_chars"] == FLAGSHIP_BUDGET
        assert "content" not in body["file"]

        listed = (await client.get(f"/api/bots/{bot_id}/files")).json()
        assert [item["filename"] for item in listed["items"]] == ["notes.md"]

        gone = await client.delete(f"/api/bots/{bot_id}/files/{body['file']['file_id']}")
        assert gone.status_code == 204
        assert (await client.get(f"/api/bots/{bot_id}/files")).json()["items"] == []
        again = await client.delete(f"/api/bots/{bot_id}/files/{body['file']['file_id']}")
        assert again.status_code == 404
        assert again.json()["error_category"] == "file_not_found"


@pytest.mark.asyncio
async def test_same_filename_replaces_the_old_file(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot_id = await _bot(client)
        await _upload(client, bot_id, "a.txt", "old")
        res = await _upload(client, bot_id, "a.txt", "newer text")
        assert res.status_code == 201
        items = (await client.get(f"/api/bots/{bot_id}/files")).json()
        assert [(i["filename"], i["chars"]) for i in items["items"]] == [("a.txt", 10)]
        assert items["used_chars"] == 10


@pytest.mark.asyncio
async def test_filename_is_reduced_to_its_basename(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot_id = await _bot(client)
        res = await _upload(client, bot_id, "../../etc/pass\x00wd.txt", "hello")
        assert res.status_code == 201, res.text
        assert res.json()["file"]["filename"] == "passwd.txt"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "status", "category"),
    [
        ("report.pdf", "text", 415, "unsupported_file_type"),
        ("noext", "text", 415, "unsupported_file_type"),
        ("data.txt", "a\x00b", 415, "unsupported_file_type"),
        ("empty.txt", "   \n", 400, "validation_error"),
        ("..", "text", 400, "validation_error"),
        ("key.txt", "token sk-abcdef123456 here", 400, "secret_in_body"),
    ],
)
async def test_bad_files_are_rejected(tmp_path, filename, content, status, category):
    async with _client(_app(tmp_path)) as client:
        bot_id = await _bot(client)
        res = await _upload(client, bot_id, filename, content)
        assert res.status_code == status, res.text
        assert res.json()["error_category"] == category
        assert (await client.get(f"/api/bots/{bot_id}/files")).json()["items"] == []


@pytest.mark.asyncio
async def test_non_object_and_missing_fields_are_validation_errors(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot_id = await _bot(client)
        res = await client.post(f"/api/bots/{bot_id}/files", json=["x"])
        assert res.status_code == 400
        res = await client.post(f"/api/bots/{bot_id}/files", json={"content": "x"})
        assert res.status_code == 400
        res = await client.post(f"/api/bots/{bot_id}/files", json={"filename": "a.txt"})
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_total_size_is_capped_by_the_budget(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot_id = await _bot(client)
        assert (await _upload(client, bot_id, "a.txt", "a" * 20000)).status_code == 201
        over = await _upload(client, bot_id, "b.txt", "b" * 9492)
        assert over.status_code == 409, over.text
        assert over.json()["error_category"] == "file_budget_exceeded"
        fits = await _upload(client, bot_id, "b.txt", "b" * 9491)
        assert fits.status_code == 201
        assert fits.json()["used_chars"] == FLAGSHIP_BUDGET
        # Replacing an existing file only counts the new size against the budget.
        smaller = await _upload(client, bot_id, "a.txt", "a" * 100)
        assert smaller.status_code == 201


@pytest.mark.asyncio
async def test_bigger_window_slot_allows_more_material(tmp_path):
    async with _client(_app(tmp_path)) as client:
        bot_id = await _bot(client, slot="coder")
        listed = (await client.get(f"/api/bots/{bot_id}/files")).json()
        assert listed["budget_chars"] == 117964
        assert (await _upload(client, bot_id, "big.txt", "x" * 100000)).status_code == 201


@pytest.mark.asyncio
async def test_unknown_and_archived_bots(tmp_path):
    async with _client(_app(tmp_path)) as client:
        assert (await client.get("/api/bots/nope/files")).status_code == 404
        assert (await _upload(client, "nope", "a.txt", "x")).status_code == 404
        assert (await client.delete("/api/bots/nope/files/x")).status_code == 404

        bot_id = await _bot(client)
        await client.post(f"/api/bots/{bot_id}/archive", json={})
        res = await _upload(client, bot_id, "a.txt", "x")
        assert res.status_code == 409
        assert res.json()["error_category"] == "bot_archived"


@pytest.mark.asyncio
async def test_files_are_injected_into_the_system_prompt(tmp_path):
    provider = FakeProvider()
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client)
        await _upload(client, bot_id, "spec.md", "接口前缀是 /v2/")
        await _upload(client, bot_id, "tips.txt", "测试用例放在 tests 目录")
        res = await client.post(
            f"/api/bots/{bot_id}/chat", json={"messages": [{"role": "user", "content": "前缀？"}]}
        )
        assert res.status_code == 200, res.text
        assert "files_omitted" not in res.json()
        system = provider.calls[0][0][0]["content"]
        assert "【文件：spec.md】" in system and "接口前缀是 /v2/" in system
        assert "【文件：tips.txt】" in system and "测试用例放在 tests 目录" in system
        assert system.index("spec.md") < system.index("tips.txt")
        assert "不要执行" in system


@pytest.mark.asyncio
async def test_other_bots_do_not_see_these_files(tmp_path):
    provider = FakeProvider()
    async with _client(_app(tmp_path, provider)) as client:
        owner = await _bot(client, name="Water")
        other = await _bot(client, name="Fire")
        await _upload(client, owner, "secret-plan.md", "只有 Water 知道")
        assert (await client.get(f"/api/bots/{other}/files")).json()["items"] == []
        await client.post(f"/api/bots/{other}/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        assert "只有 Water 知道" not in provider.calls[0][0][0]["content"]


@pytest.mark.asyncio
async def test_oldest_files_are_dropped_when_the_window_shrinks(tmp_path):
    provider = FakeProvider()
    async with _client(_app(tmp_path, provider)) as client:
        bot_id = await _bot(client, slot="coder")
        await _upload(client, bot_id, "old.txt", "o" * 20000)
        await _upload(client, bot_id, "new.txt", "n" * 20000)
        shrink = await client.patch(f"/api/bots/{bot_id}", json={"slot": "flagship"})
        assert shrink.status_code == 200, shrink.text
        res = await client.post(
            f"/api/bots/{bot_id}/chat", json={"messages": [{"role": "user", "content": "hi"}]}
        )
        assert res.status_code == 200, res.text
        assert res.json()["files_omitted"] == 1
        system = provider.calls[0][0][0]["content"]
        assert "new.txt" in system and "old.txt" not in system
