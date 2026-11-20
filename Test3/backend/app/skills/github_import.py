"""Import a skill definition from a public GitHub repository.

Only two fixed hosts are ever contacted (``api.github.com`` to resolve a commit,
``raw.githubusercontent.com`` to read ``SKILL.md`` at that commit), redirects are
not followed, and the file size is capped.  The version is the short commit sha,
so a bot's pinned skill never changes underneath it.  Imported skills never get
tool permissions: ``allowed_tool_refs`` is always empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import yaml

from app.schemas.skill_definition import SkillCreate

API_HOST = "https://api.github.com"
RAW_HOST = "https://raw.githubusercontent.com"
MAX_SKILL_BYTES = 64 * 1024
SKILL_FILE = "SKILL.md"

_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class SkillImportError(Exception):
    def __init__(self, status_code: int, category: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.category = category
        self.detail = detail


@dataclass(frozen=True)
class GithubSource:
    owner: str
    repo: str
    ref: str | None
    path: str  # directory inside the repo, "" for the root


def _bad_url(detail: str) -> SkillImportError:
    return SkillImportError(400, "validation_error", detail)


def parse_github_url(url: str) -> GithubSource:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise _bad_url("请填写 https://github.com/ 开头的仓库地址")
    if parsed.port or parsed.username or parsed.password:
        raise _bad_url("地址格式不正确")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise _bad_url("地址需要包含 owner 和仓库名")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    rest = parts[2:]
    ref: str | None = None
    path_parts: list[str] = []
    if rest:
        if rest[0] not in {"tree", "blob"} or len(rest) < 2:
            raise _bad_url("只支持仓库主页，或 /tree/、/blob/ 形式的目录与文件地址")
        ref = rest[1]
        path_parts = rest[2:]
        if rest[0] == "blob":
            if not path_parts or path_parts[-1] != SKILL_FILE:
                raise _bad_url("文件地址必须指向 SKILL.md")
            path_parts = path_parts[:-1]
    for segment in (owner, repo, *(path_parts), *([ref] if ref else [])):
        if not _SEGMENT.match(segment) or segment in {".", ".."}:
            raise _bad_url("地址里含有不支持的字符")
    return GithubSource(owner=owner, repo=repo, ref=ref, path="/".join(path_parts))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-_")[:64]


def parse_skill_markdown(text: str) -> tuple[dict, str]:
    """Split optional YAML front matter from the markdown body."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end]) or {}
            except yaml.YAMLError:
                meta = {}
            body = text[end + 4 :].lstrip("\n")
            return (meta if isinstance(meta, dict) else {}), body
    return {}, text


def build_skill(source: GithubSource, sha: str, text: str) -> SkillCreate:
    meta, body = parse_skill_markdown(text)
    name = str(meta.get("name") or "").strip() or (source.path.rsplit("/", 1)[-1] if source.path else source.repo)
    slug = _slug(name)
    if not slug:
        raise SkillImportError(400, "validation_error", "无法从 SKILL.md 得到 skill 名称")
    owner = _slug(source.owner)
    folder = f"/{source.path}" if source.path else ""
    origin = f"https://github.com/{source.owner}/{source.repo}/tree/{sha}{folder}"
    description = str(meta.get("description") or "").strip()
    header = f"来源：{origin}\n\n" + (f"{description}\n\n" if description else "")
    return SkillCreate(
        skill_id=f"{owner}-{slug}",
        version=sha[:7],
        description_md=header + body,
        allowed_tool_refs=[],
    )


async def _read_limited(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_SKILL_BYTES:
            raise SkillImportError(400, "skill_too_large", "SKILL.md 超过 64KB")
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_skill(url: str, client: httpx.AsyncClient) -> SkillCreate:
    source = parse_github_url(url)
    try:
        commit = await client.get(
            f"{API_HOST}/repos/{source.owner}/{source.repo}/commits/{source.ref or 'HEAD'}",
            headers={"Accept": "application/vnd.github+json"},
        )
        if commit.status_code in {404, 422}:
            raise SkillImportError(404, "skill_source_not_found", "找不到这个仓库或分支，请确认它是公开的")
        if commit.status_code in {403, 429}:
            raise SkillImportError(502, "github_unavailable", "GitHub 请求太频繁，请稍后再试")
        if commit.status_code != 200:
            raise SkillImportError(502, "github_unavailable", f"GitHub 返回 {commit.status_code}")
        sha = str(commit.json().get("sha") or "")
        if not _SHA.match(sha):
            raise SkillImportError(502, "github_unavailable", "GitHub 返回了无法识别的提交")

        file_path = f"{source.path}/{SKILL_FILE}" if source.path else SKILL_FILE
        async with client.stream(
            "GET", f"{RAW_HOST}/{source.owner}/{source.repo}/{sha}/{file_path}"
        ) as raw:
            if raw.status_code == 404:
                raise SkillImportError(404, "skill_source_not_found", "这个位置没有 SKILL.md")
            if raw.status_code != 200:
                raise SkillImportError(502, "github_unavailable", f"GitHub 返回 {raw.status_code}")
            data = await _read_limited(raw)
    except httpx.HTTPError as exc:
        raise SkillImportError(502, "github_unavailable", "无法连接 GitHub") from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillImportError(400, "validation_error", "SKILL.md 不是 UTF-8 文本") from exc
    return build_skill(source, sha, text)


__all__ = ["GithubSource", "SkillImportError", "build_skill", "fetch_skill", "parse_github_url"]
