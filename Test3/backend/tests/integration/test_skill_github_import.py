from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.runtime import RoleRegistry
from app.llm.gateway import Gateway
from app.llm.providers import ScriptedProvider
from app.main import create_app
from app.services.runtime import Workbench
from app.settings import load_models, load_roles
from app.skills.github_import import parse_github_url

SHA = "a" * 40
SKILL_MD = "---\nname: Code Review\ndescription: 审查代码\n---\n# 步骤\n先读 diff。\n"


def _github(handler_log: list[str], *, skill: str | None = SKILL_MD, commit_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        handler_log.append(str(request.url))
        if request.url.host == "api.github.com":
            if commit_status != 200:
                return httpx.Response(commit_status, json={})
            return httpx.Response(200, json={"sha": SHA})
        if request.url.host == "raw.githubusercontent.com":
            if skill is None:
                return httpx.Response(404)
            return httpx.Response(200, content=skill.encode())
        return httpx.Response(500)

    return httpx.MockTransport(handler)


def _app(tmp_path, transport):
    app = create_app()
    app.state.workbench = Workbench(Gateway(load_models(), ScriptedProvider()), RoleRegistry(load_roles()), tmp_path)
    app.state.skill_import_transport = transport
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def test_parse_github_url_variants():
    assert parse_github_url("https://github.com/acme/skills").path == ""
    tree = parse_github_url("https://github.com/acme/skills/tree/main/review/")
    assert (tree.ref, tree.path) == ("main", "review")
    blob = parse_github_url("https://github.com/acme/skills/blob/v1/a/b/SKILL.md")
    assert (blob.ref, blob.path) == ("v1", "a/b")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/acme/skills",
        "https://evil.com/acme/skills",
        "https://github.com.evil.com/acme/skills",
        "https://github.com/acme",
        "https://github.com/acme/skills/tree/main/../x",
        "https://github.com/acme/skills/blob/main/README.md",
        "https://user:pw@github.com/acme/skills",
        "",
    ],
)
def test_parse_github_url_rejects(url):
    from app.skills.github_import import SkillImportError

    with pytest.raises(SkillImportError):
        parse_github_url(url)


@pytest.mark.asyncio
async def test_import_registers_skill_pinned_to_commit_without_tools(tmp_path):
    log: list[str] = []
    async with _client(_app(tmp_path, _github(log))) as client:
        res = await client.post("/api/skills/import", json={"url": "https://github.com/Acme/skills/tree/main/review"})
        assert res.status_code == 201
        skill = res.json()
        assert skill["skill_id"] == "acme-code-review"
        assert skill["version"] == SHA[:7]
        assert skill["allowed_tool_refs"] == []
        assert "来源：https://github.com/Acme/skills/tree/" + SHA + "/review" in skill["description_md"]
        assert "先读 diff" in skill["description_md"]
        assert any(url.endswith(f"/{SHA}/review/SKILL.md") for url in log)

        again = await client.post("/api/skills/import", json={"url": "https://github.com/Acme/skills/tree/main/review"})
        assert again.status_code == 200 and again.json() == skill
        listed = (await client.get("/api/skills")).json()["items"]
        assert [item["skill_id"] for item in listed] == ["acme-code-review"]


@pytest.mark.asyncio
async def test_import_error_mapping(tmp_path):
    async with _client(_app(tmp_path, _github([], skill=None))) as client:
        assert (await client.post("/api/skills/import", json={"url": "https://github.com/a/b"})).status_code == 404
        assert (await client.post("/api/skills/import", json={"url": "https://x.com/a/b"})).status_code == 400
        assert (await client.post("/api/skills/import", json={})).status_code == 400
    async with _client(_app(tmp_path, _github([], commit_status=404))) as client:
        assert (await client.post("/api/skills/import", json={"url": "https://github.com/a/b"})).status_code == 404
    async with _client(_app(tmp_path, _github([], commit_status=403))) as client:
        assert (await client.post("/api/skills/import", json={"url": "https://github.com/a/b"})).status_code == 502
    big = "x" * (64 * 1024 + 1)
    async with _client(_app(tmp_path, _github([], skill=big))) as client:
        res = await client.post("/api/skills/import", json={"url": "https://github.com/a/b"})
        assert res.status_code == 400 and res.json()["error_category"] == "skill_too_large"
