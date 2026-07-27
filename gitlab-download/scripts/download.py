"""
GitLab 群组批量下载工具（自包含版本）。

递归扫描 GITLAB_ROOT_GROUP 下的所有项目（含子群组），按 GitLab 层级结构
clone 到本地。已存在的仓库执行 fetch + ff-only pull，不强制覆盖。

环境变量:
  GITLAB_URL           GitLab 服务器地址 (如 https://192.168.1.218)
  GITLAB_TOKEN         Personal access token
  GITLAB_ROOT_GROUP    根群组路径 (如 embedded/bcmu/standard)
  LOCAL_ROOT           本地根目录（默认当前目录）
  GITLAB_VERIFY_SSL    是否验证 SSL 证书 (默认 false，兼容内网自签)
  CLONE_BRANCH         指定 clone 分支 (可选)
  CLONE_DEPTH          浅克隆深度 (可选，0=完整克隆)

用法:
  python download.py                   # dry-run 预览
  python download.py --execute         # 实际执行
  python download.py --filter <关键词>  # 仅处理匹配项目
  python download.py --include-archived # 含已归档项目
  python download.py --report report.json  # 输出 JSON 报告
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
LOG = logging.getLogger("gitlab_downloader")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Config:
    gitlab_url: str
    token: str
    root_group: str
    local_root: Path
    verify_ssl: bool
    branch: Optional[str]
    depth: int

    @classmethod
    def from_env(cls) -> "Config":
        gitlab_url = os.environ.get("GITLAB_URL", "").strip().rstrip("/")
        token = os.environ.get("GITLAB_TOKEN", "").strip()
        root_group = os.environ.get("GITLAB_ROOT_GROUP", "").strip().strip("/")

        if not gitlab_url:
            raise SystemExit("GITLAB_URL 未设置")
        if not token:
            raise SystemExit("GITLAB_TOKEN 未设置")
        if not root_group:
            raise SystemExit("GITLAB_ROOT_GROUP 未设置")

        local_root_env = os.environ.get("LOCAL_ROOT", "").strip()
        local_root = Path(local_root_env).expanduser().resolve() if local_root_env else Path.cwd()

        verify_ssl = os.environ.get("GITLAB_VERIFY_SSL", "false").strip().lower() in {
            "true", "1", "yes",
        }

        branch = os.environ.get("CLONE_BRANCH", "").strip() or None
        depth_raw = os.environ.get("CLONE_DEPTH", "").strip()
        try:
            depth = int(depth_raw) if depth_raw else 0
        except ValueError:
            depth = 0

        return cls(
            gitlab_url=gitlab_url,
            token=token,
            root_group=root_group,
            local_root=local_root,
            verify_ssl=verify_ssl,
            branch=branch,
            depth=depth,
        )


# ---------------------------------------------------------------------------
# GitLab API 客户端
# ---------------------------------------------------------------------------

class GitLabClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"PRIVATE-TOKEN": cfg.token})
        self.session.verify = cfg.verify_ssl

    def _get_paginated(self, url: str, params: Optional[dict] = None) -> List[dict]:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        results: List[dict] = []
        page = 1
        while True:
            params["page"] = page
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            results.extend(data)
            next_page = resp.headers.get("X-Next-Page", "").strip()
            if not next_page:
                break
            page = int(next_page)
        return results

    def get_group(self, group_path: str) -> dict:
        encoded = urllib.parse.quote(group_path, safe="")
        url = f"{self.cfg.gitlab_url}/api/v4/groups/{encoded}"
        resp = self.session.get(url, timeout=30)
        if resp.status_code == 404:
            raise SystemExit(f"GitLab 群组未找到: {group_path}")
        resp.raise_for_status()
        return resp.json()

    def get_group_or_none(self, group_path: str) -> Optional[dict]:
        encoded = urllib.parse.quote(group_path, safe="")
        url = f"{self.cfg.gitlab_url}/api/v4/groups/{encoded}"
        resp = self.session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def list_projects(self, group_id: int, include_archived: bool) -> List[dict]:
        url = f"{self.cfg.gitlab_url}/api/v4/groups/{group_id}/projects"
        params = {"include_subgroups": "true"}
        if not include_archived:
            params["archived"] = "false"
        return self._get_paginated(url, params=params)


# ---------------------------------------------------------------------------
# 路径映射
# ---------------------------------------------------------------------------

_WIN_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_leaf_name(name: str, fallback: str) -> str:
    if not name:
        return fallback
    cleaned = name.strip().rstrip(". ")
    if not cleaned or _WIN_INVALID_RE.search(cleaned):
        return fallback
    return cleaned


def build_authenticated_url(http_url: str, token: str) -> str:
    parsed = urllib.parse.urlsplit(http_url)
    netloc = f"oauth2:{token}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


class GroupNameResolver:
    """缓存中间 group 的显示名，用于中文路径映射。"""

    def __init__(self, client: "GitLabClient") -> None:
        self._client = client
        self._cache: Dict[str, Optional[str]] = {}

    def resolve(self, sub_path: str) -> Optional[str]:
        if sub_path in self._cache:
            return self._cache[sub_path]
        full = f"{self._client.cfg.root_group}/{sub_path}"
        try:
            grp = self._client.get_group_or_none(full)
        except Exception as exc:
            LOG.debug("查询 group %s 失败: %s", full, exc)
            grp = None
        name = grp.get("name") if grp else None
        self._cache[sub_path] = name
        return name


def relative_dest(
    project: dict,
    root_group: str,
    group_name_resolver: Optional["GroupNameResolver"] = None,
) -> Path:
    """把 GitLab project 映射到本地相对路径，保留中文显示名。"""
    project_path = project["path_with_namespace"]
    prefix = root_group.rstrip("/") + "/"
    sub = project_path[len(prefix):] if project_path.startswith(prefix) else project_path
    parts = sub.split("/")
    leaf_slug = parts[-1]
    leaf = _safe_leaf_name(project.get("name", ""), leaf_slug)

    group_segments: List[str] = []
    if len(parts) > 1 and group_name_resolver is not None:
        accumulated_slug: List[str] = []
        for slug_seg in parts[:-1]:
            accumulated_slug.append(slug_seg)
            full_under_root = "/".join(accumulated_slug)
            display = group_name_resolver.resolve(full_under_root)
            group_segments.append(_safe_leaf_name(display, slug_seg))
    else:
        group_segments = list(parts[:-1])

    return Path(*group_segments, leaf)


# ---------------------------------------------------------------------------
# Git 操作
# ---------------------------------------------------------------------------

def run_git(args: List[str], cwd: Optional[Path] = None, env_extra: Optional[dict] = None) -> int:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    LOG.debug("git %s (cwd=%s)", " ".join(args), cwd)
    result = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, env=env,
                          capture_output=True, text=True)
    return result.returncode


def _find_legacy_dir(dest: Path, project: dict, cfg: Config) -> Optional[Path]:
    """检测按旧 slug 命名的同名目录，用于提示重命名。"""
    parent = dest.parent
    if not parent.exists():
        return None
    leaf_slug = project["path_with_namespace"].rsplit("/", 1)[-1]
    candidate = parent / leaf_slug
    if candidate == dest or not (candidate / ".git").exists():
        return None
    try:
        cfg_path = candidate / ".git" / "config"
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    expected = project["path_with_namespace"]
    if expected in text or project["http_url_to_repo"] in text:
        return candidate
    return None


# ---------------------------------------------------------------------------
# 克隆 / 同步（含去重检查）
# ---------------------------------------------------------------------------

def clone_or_update(
    project: dict,
    cfg: Config,
    execute: bool,
    group_name_resolver: Optional[GroupNameResolver] = None,
) -> str:
    """
    克隆或更新单个项目。返回状态: CLONED / PULLED / SKIPPED / FAILED
    去重规则: 本地已存在 + pull 结果为 Already up to date → SKIPPED
    """
    rel = relative_dest(project, cfg.root_group, group_name_resolver)
    dest = (cfg.local_root / rel).resolve()
    auth_url = build_authenticated_url(project["http_url_to_repo"], cfg.token)
    safe_url = project["http_url_to_repo"]

    git_env = {}
    if not cfg.verify_ssl:
        git_env["GIT_SSL_NO_VERIFY"] = "true"

    git_dir = dest / ".git"

    if not git_dir.exists():
        legacy = _find_legacy_dir(dest, project, cfg)
        if legacy is not None:
            LOG.warning(
                "检测到旧目录 %s 已是该项目的本地副本；请手动重命名为 %s 后再运行，"
                "否则会重复克隆。本次仍按新名称克隆。",
                legacy, dest.name,
            )

    if git_dir.exists():
        LOG.info("[PULL] %s -> %s", project["path_with_namespace"], dest)
        if not execute:
            return "PULL"

        # 临时设置 origin 为带 token 的 URL
        if run_git(["remote", "set-url", "origin", auth_url], cwd=dest, env_extra=git_env) != 0:
            return "FAILED"
        try:
            if run_git(["fetch", "--all", "--prune"], cwd=dest, env_extra=git_env) != 0:
                return "FAILED"

            # 检查是否需要 pull
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(dest), env={**os.environ, **git_env},
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                LOG.warning("pull --ff-only 失败（可能本地有改动），跳过：%s", dest)
                return "FAILED"

            # 去重: 已是最新 → 标记 SKIPPED
            output = (result.stdout + result.stderr).strip()
            if "Already up to date." in output or "Already up-to-date." in output:
                return "SKIPPED"
            return "PULLED"
        finally:
            run_git(["remote", "set-url", "origin", safe_url], cwd=dest, env_extra=git_env)

    # 新克隆
    LOG.info("[CLONE] %s -> %s", project["path_with_namespace"], dest)
    if not execute:
        return "CLONE"

    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["clone"]
    if cfg.depth > 0:
        args += ["--depth", str(cfg.depth)]
    if cfg.branch:
        args += ["--branch", cfg.branch]
    args += [auth_url, str(dest)]
    if run_git(args, env_extra=git_env) != 0:
        return "FAILED"
    run_git(["remote", "set-url", "origin", safe_url], cwd=dest, env_extra=git_env)
    return "CLONED"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="递归下载 GitLab 群组下所有项目")
    parser.add_argument("--execute", action="store_true",
                      help="实际执行 git clone/pull，否则只预览")
    parser.add_argument("--include-archived", action="store_true",
                      help="同时下载已归档项目")
    parser.add_argument("--filter", default=None,
                      help="仅处理 path_with_namespace 包含该子串的项目")
    parser.add_argument("-v", "--verbose", action="store_true",
                      help="打印调试日志")
    parser.add_argument("--report", default=None, type=Path,
                      help="下载完成后写入 JSON 报告文件")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = Config.from_env()
    LOG.info("GitLab: %s", cfg.gitlab_url)
    LOG.info("根群组: %s", cfg.root_group)
    LOG.info("本地根: %s", cfg.local_root)
    LOG.info("模式  : %s", "EXECUTE" if args.execute else "DRY-RUN（加 --execute 才会真正执行）")

    client = GitLabClient(cfg)
    group = client.get_group(cfg.root_group)
    projects = client.list_projects(group["id"], include_archived=args.include_archived)
    resolver = GroupNameResolver(client)

    if args.filter:
        projects = [p for p in projects if args.filter in p["path_with_namespace"]]

    projects.sort(key=lambda p: p["path_with_namespace"])
    LOG.info("匹配项目数: %d", len(projects))

    cfg.local_root.mkdir(parents=True, exist_ok=True)

    # 统计
    stats = {"CLONED": 0, "PULLED": 0, "SKIPPED": 0, "FAILED": 0}
    results: List[dict] = []

    for proj in projects:
        try:
            status = clone_or_update(proj, cfg, execute=args.execute,
                                     group_name_resolver=resolver)
            stats[status] = stats.get(status, 0) + 1
            results.append({
                "path": proj["path_with_namespace"],
                "status": status,
            })
        except Exception as exc:
            LOG.error("处理 %s 时出错: %s", proj["path_with_namespace"], exc)
            stats["FAILED"] += 1
            results.append({
                "path": proj["path_with_namespace"],
                "status": "FAILED",
                "error": str(exc),
            })

    # 摘要
    LOG.info("─" * 50)
    LOG.info("结果: %d 新克隆, %d 已更新, %d 已是最新跳过, %d 失败",
             stats["CLONED"], stats["PULLED"], stats["SKIPPED"], stats["FAILED"])

    # --report
    if args.report:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gitlab_url": cfg.gitlab_url,
            "root_group": cfg.root_group,
            "local_root": str(cfg.local_root),
            "executed": args.execute,
            "total": len(projects),
            "stats": stats,
            "results": results,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        LOG.info("报告已写入: %s", args.report)

    return 1 if stats["FAILED"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
