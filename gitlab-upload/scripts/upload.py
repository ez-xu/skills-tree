"""
GitLab 批量上传工具（自包含版本，L1/L2/L3 混合深度发现）。

扫描 LOCAL_ROOT 下的目录结构，自动判断仓库深度：
    - L1 仓库：<LOCAL_ROOT>/<L1>/.git 存在 → project（直接挂在根群组下）
    - L2 仓库：<LOCAL_ROOT>/<L1>/<L2>/.git 存在 → L1=subgroup, L2=project
    - L3 仓库：<LOCAL_ROOT>/<L1>/<L2>/<L3>/.git 存在 → L1=subgroup, L2=subgroup, L3=project
同一遍历中三种模式可以共存。

在 GitLab 的 GITLAB_ROOT_GROUP 下：
    - 子群组 → 幂等创建/复用
    - 项目 → 幂等创建/复用，推送本地仓库

环境变量:
  GITLAB_URL           GitLab 服务器地址
  GITLAB_TOKEN         Personal access token
  GITLAB_ROOT_GROUP    根群组路径 (如 embedded/bcmu/standard)
  LOCAL_ROOT           本地根目录（默认当前目录）
  GITLAB_VERIFY_SSL    是否验证 SSL 证书 (默认 false)

用法:
  python upload.py --dry-run                  # 预览
  python upload.py --execute                  # 执行
  python upload.py --dry-run --limit 5        # 仅预览前 5 个
  python upload.py --execute --only <关键词>   # 仅处理匹配目录
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
logger = logging.getLogger("gitlab_uploader")

# 扫描时跳过这些目录名
SKIP_DIRECTORY_NAMES = {
    ".git", ".hg", ".svn", ".vs", ".vscode", "_tools", "__pycache__",
}

GITIGNORE_TEMPLATE = SCRIPT_DIR / ".gitignore"
README_NAME = "README.md"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def slugify_path(name: str) -> str:
    """中文/特殊字符 → GitLab 合法 path slug [A-Za-z0-9_.-]"""
    s = re.sub(r"[^A-Za-z0-9_.\-]", "-", name)
    s = re.sub(r"-+", "-", s)
    s = re.sub(r"-_", "_", s)
    s = re.sub(r"_-", "_", s)
    s = re.sub(r"_{2,}", "_", s)
    s = s.strip("-.")
    return s or "repo"


def sanitize_name(name: str) -> str:
    if not name or name != name.strip():
        raise ValueError(f"目录名不合法（首尾不能有空白，且不能为空）: {name!r}")
    return name


def mask_sensitive(text: str, sensitive_values: Sequence[str] = ()) -> str:
    masked = text
    for value in sensitive_values:
        if value:
            masked = masked.replace(value, "***")
    return masked


def read_gitignore_template() -> str:
    if GITIGNORE_TEMPLATE.is_file():
        return GITIGNORE_TEMPLATE.read_text(encoding="utf-8", errors="replace")
    # 内置默认模板
    return (
        "# 编译产物\n*.o\n*.obj\n*.elf\n*.hex\n*.bin\n*.map\n"
        "# 依赖\nnode_modules/\nvendor/\n"
        "# IDE\n.vs/\n.vscode/\n.idea/\n*.user\n"
        "# 临时文件\n*.tmp\n*.swp\n*~\n.DS_Store\nThumbs.db\n"
        "# 日志\n*.log\n"
        "# Python\n__pycache__/\n*.pyc\n*.pyo\n"
        "# 环境\n.env\n.env.local\n"
    )


def _make_simple_readme(repo_name: str, workspace_root: Path, repo_path: Path) -> str:
    rel = repo_path.relative_to(workspace_root).as_posix()
    return (
        f"# {repo_name}\n\n"
        f"- 相对路径：`{rel}`\n"
        f"- 此文件由 gitlab-upload 工具自动生成。\n"
        f"- 请补充项目说明、使用方法、硬件接线等关键信息。\n"
    )


def run_git(args: List[str], cwd: Path, check: bool = True,
            capture: bool = True,
            sensitive_values: Sequence[str] = (),
            env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    logger.debug("git %s  (cwd=%s)", mask_sensitive(" ".join(args), sensitive_values), cwd)
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    res = subprocess.run(
        ["git"] + args, cwd=str(cwd), check=False, text=True,
        capture_output=capture, encoding="utf-8", errors="replace",
        env=run_env,
    )
    if check and res.returncode != 0:
        stdout = mask_sensitive(res.stdout or "", sensitive_values)
        stderr = mask_sensitive(res.stderr or "", sensitive_values)
        raise RuntimeError(
            f"git {' '.join(args)} 失败 (cwd={cwd}):\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        )
    return res


# ---------------------------------------------------------------------------
# GitLab 客户端
# ---------------------------------------------------------------------------

class GitLabClient:
    def __init__(self, base_url: str, token: str, verify: bool = False):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({"PRIVATE-TOKEN": token})
        self.session.verify = verify
        self.timeout = 30

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v4{path}"

    def _get(self, path: str, **kwargs) -> requests.Response:
        return self.session.get(self._url(path), timeout=self.timeout, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        return self.session.post(self._url(path), timeout=self.timeout, **kwargs)

    def _put(self, path: str, **kwargs) -> requests.Response:
        return self.session.put(self._url(path), timeout=self.timeout, **kwargs)

    # ── groups ──

    def get_group(self, full_path: str) -> Optional[dict]:
        enc = urllib.parse.quote(full_path, safe="")
        r = self._get(f"/groups/{enc}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        raise RuntimeError(f"get_group({full_path}) -> {r.status_code} {r.text}")

    def create_subgroup(self, parent_id: int, name: str, path: str) -> dict:
        payload = {
            "name": name, "path": path, "parent_id": parent_id,
            "visibility": "private",
        }
        r = self._post("/groups", json=payload)
        if r.status_code in (200, 201):
            return r.json()
        raise RuntimeError(
            f"create_subgroup(parent={parent_id}, name={name}, path={path}) "
            f"-> {r.status_code} {r.text}"
        )

    def ensure_subgroup(self, parent_full_path: str, parent_id: int,
                       name: str) -> dict:
        """幂等创建子群组。已存在则复用，slug 碰撞则自动追加后缀。"""
        base_path = slugify_path(name)
        safe_name = sanitize_name(name)
        path = base_path
        suffix = 1
        while True:
            full = f"{parent_full_path}/{path}"
            existing = self.get_group(full)
            if not existing:
                break
            existing_name = (existing.get("name") or "").strip()
            if existing_name == safe_name or existing_name == name.strip():
                logger.info("  subgroup 已存在: %s (id=%s)", full, existing["id"])
                return existing
            suffix += 1
            path = f"{base_path}-{suffix}"
            logger.warning("  subgroup slug 碰撞（已存在 name=%r），改用 path=%s",
                           existing_name, path)
        logger.info("  创建 subgroup: %s", full)
        return self.create_subgroup(parent_id, safe_name, path)

    # ── projects ──

    def get_project(self, full_path: str) -> Optional[dict]:
        enc = urllib.parse.quote(full_path, safe="")
        r = self._get(f"/projects/{enc}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        raise RuntimeError(f"get_project({full_path}) -> {r.status_code} {r.text}")

    def create_project(self, namespace_id: int, name: str, path: str) -> dict:
        payload = {
            "name": name, "path": path, "namespace_id": namespace_id,
            "visibility": "private", "default_branch": "main",
            "initialize_with_readme": False,
        }
        r = self._post("/projects", json=payload)
        if r.status_code in (200, 201):
            return r.json()
        raise RuntimeError(
            f"create_project(ns={namespace_id}, name={name}, path={path}) "
            f"-> {r.status_code} {r.text}"
        )

    def ensure_project(self, group_full_path: str, group_id: int,
                       name: str) -> dict:
        """幂等创建项目。已存在则复用，slug 碰撞则自动追加后缀。"""
        base_path = slugify_path(name)
        safe_name = sanitize_name(name)
        path = base_path
        suffix = 1
        while True:
            full = f"{group_full_path}/{path}"
            existing = self.get_project(full)
            if not existing:
                break
            existing_name = (existing.get("name") or "").strip()
            if existing_name == safe_name or existing_name == name.strip():
                logger.info("  project 已存在: %s (id=%s)", full, existing["id"])
                return existing
            suffix += 1
            path = f"{base_path}-{suffix}"
            logger.warning(
                "  project slug 碰撞（已存在 name=%r 与本地 name=%r 不一致），改用 path=%s",
                existing_name, name, path,
            )
        logger.info("  创建 project: %s", full)
        return self.create_project(group_id, safe_name, path)

    def set_default_branch(self, project_id: int, branch: str = "main") -> None:
        r = self._put(f"/projects/{project_id}", json={"default_branch": branch})
        if r.status_code not in (200, 201):
            logger.warning("set_default_branch(%s) -> %s %s",
                           project_id, r.status_code, r.text)


# ---------------------------------------------------------------------------
# 本地仓库操作
# ---------------------------------------------------------------------------

@dataclass
class LocalRepo:
    path: Path
    repo_name: str
    workspace_root: Path
    changes: List[str] = field(default_factory=list)

    def has_git(self) -> bool:
        return (self.path / ".git").exists()

    def current_branch(self) -> Optional[str]:
        res = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"],
                      self.path, check=False)
        return res.stdout.strip() if res.returncode == 0 else None

    def has_any_commit(self) -> bool:
        res = run_git(["rev-parse", "--verify", "HEAD"], self.path, check=False)
        return res.returncode == 0

    def branch_exists(self, name: str) -> bool:
        res = run_git(["show-ref", "--verify", "--quiet",
                       f"refs/heads/{name}"], self.path, check=False)
        return res.returncode == 0

    def dirty_status(self) -> str:
        res = run_git(["status", "--porcelain"], self.path, check=False)
        return (res.stdout or "").strip()

    def ensure_git_init(self) -> None:
        if self.has_git():
            return
        logger.info("  git init -b main")
        res = run_git(["init", "-b", "main"], self.path, check=False)
        if res.returncode != 0:
            run_git(["init"], self.path)
            run_git(["symbolic-ref", "HEAD", "refs/heads/main"], self.path)

    def ensure_main_branch(self) -> None:
        cur = self.current_branch()
        if cur == "main":
            return
        if cur == "master":
            logger.info("  分支 master -> main")
            run_git(["branch", "-m", "master", "main"], self.path)
            return
        if not self.has_any_commit():
            run_git(["symbolic-ref", "HEAD", "refs/heads/main"], self.path)
            return
        if self.branch_exists("main"):
            logger.info("  切换到已存在的 main 分支")
            run_git(["checkout", "main"], self.path)
        else:
            logger.info("  从 %s 创建 main 分支", cur)
            run_git(["checkout", "-b", "main"], self.path)

    def ensure_gitignore(self) -> None:
        gi = self.path / ".gitignore"
        template_text = read_gitignore_template()
        template_lines = template_text.strip("\n").splitlines()
        if gi.exists():
            existing = gi.read_text(encoding="utf-8", errors="replace")
            if existing.strip():
                existing_lines = set(l.rstrip() for l in existing.splitlines())
                missing = [l for l in template_lines if l and l.rstrip() not in existing_lines]
                if not missing:
                    return
                logger.info("  追加 .gitignore (%d 条)", len(missing))
                prefix = "\n" if existing.endswith("\n") else "\n\n"
                gi.write_text(existing + prefix + "\n".join(missing) + "\n",
                              encoding="utf-8", newline="\n")
            else:
                shutil.copyfile(GITIGNORE_TEMPLATE, gi) if GITIGNORE_TEMPLATE.is_file() else gi.write_text(template_text)
            self.changes.append(".gitignore")
        else:
            logger.info("  复制 .gitignore")
            if GITIGNORE_TEMPLATE.is_file():
                shutil.copyfile(GITIGNORE_TEMPLATE, gi)
            else:
                gi.write_text(template_text)
            self.changes.append(".gitignore")

    def ensure_readme(self) -> None:
        readme = self.path / README_NAME
        if readme.exists():
            return
        for cand in ("README.MD", "Readme.md", "readme.md"):
            if (self.path / cand).exists():
                return
        logger.info("  生成 README.md")
        readme.write_text(
            _make_simple_readme(self.repo_name, self.workspace_root, self.path),
            encoding="utf-8", newline="\n",
        )
        self.changes.append(README_NAME)

    def stage_and_commit_if_needed(self) -> bool:
        run_git(["add", "-A"], self.path)
        res = run_git(["status", "--porcelain"], self.path)
        if not res.stdout.strip():
            return False
        msg = "chore: initial commit" if not self.has_any_commit() else \
              "chore: add " + ", ".join(sorted(set(self.changes))) if self.changes else \
              "chore: sync local changes"
        logger.info("  commit: %s", msg)
        run_git(["commit", "-m", msg], self.path)
        return True

    def ensure_clean_origin(self, clean_url: str) -> None:
        res = run_git(["remote"], self.path)
        if "origin" in res.stdout.split():
            run_git(["remote", "set-url", "origin", clean_url], self.path)
        else:
            run_git(["remote", "add", "origin", clean_url], self.path)

    def push_main(self, token: str) -> None:
        logger.info("  git push -u origin main")
        basic_token = base64.b64encode(f"oauth2:{token}".encode("utf-8")).decode("ascii")
        auth_header = f"Authorization: Basic {basic_token}"
        run_git(
            ["-c", "credential.helper=", "-c", f"http.extraHeader={auth_header}",
             "push", "-u", "origin", "main"],
            self.path,
            sensitive_values=(token, basic_token, auth_header),
            env={"GIT_TERMINAL_PROMPT": "0"},
        )

    def remote_head_sha(self, token: str) -> Optional[str]:
        """获取远程 main 分支的 HEAD SHA，用于去重判断。失败返回 None。"""
        basic_token = base64.b64encode(f"oauth2:{token}".encode("utf-8")).decode("ascii")
        auth_header = f"Authorization: Basic {basic_token}"
        res = run_git(
            ["-c", "credential.helper=", "-c", f"http.extraHeader={auth_header}",
             "ls-remote", "origin", "refs/heads/main"],
            self.path, check=False,
            sensitive_values=(token, basic_token, auth_header),
            env={"GIT_TERMINAL_PROMPT": "0"},
        )
        if res.returncode != 0:
            return None
        line = res.stdout.strip()
        return line.split()[0] if line else None

    def local_head_sha(self) -> Optional[str]:
        res = run_git(["rev-parse", "HEAD"], self.path, check=False)
        return res.stdout.strip() if res.returncode == 0 else None


# ---------------------------------------------------------------------------
# 目标发现（L1 / L2 / L3 混合）
# ---------------------------------------------------------------------------

@dataclass
class Target:
    """混合深度扫描目标。
    - l2_dir = None → L1 模式（L1 自身是仓库）
    - l3_dir = None, l2_dir != None → L2 模式
    - l3_dir != None → L3 模式
    """
    l1_dir: Path
    l2_dir: Optional[Path]  # None = L1 模式
    l3_dir: Optional[Path]  # None = L2 模式


@dataclass
class Config:
    gitlab_url: str
    gitlab_token: str
    root_group_path: str
    local_root: Path
    dry_run: bool = True
    verify_ssl: bool = False
    limit: Optional[int] = None
    only: List[str] = field(default_factory=list)


def is_discoverable_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and not path.is_symlink()
        and path.name not in SKIP_DIRECTORY_NAMES
        and not path.name.startswith(".")
    )


def matches_filters(l1_dir: Path, l2_dir: Optional[Path], l3_dir: Optional[Path],
                   filters: Sequence[str]) -> bool:
    if not filters:
        return True
    candidates = [l1_dir.name.casefold()]
    if l2_dir is not None:
        candidates.append(l2_dir.name.casefold())
        candidates.append(f"{l1_dir.name}/{l2_dir.name}".casefold())
    if l3_dir is not None:
        candidates.append(l3_dir.name.casefold())
        candidates.append(f"{l1_dir.name}/{l2_dir.name}/{l3_dir.name}".casefold())
    return any(
        needle.casefold() in c for needle in filters for c in candidates
    )


def discover_targets(local_root: Path, filters: Sequence[str],
                     limit: Optional[int]) -> List[Target]:
    """
    L1/L2/L3 混合深度发现。同一遍历中三种模式共存：

    L1: LOCAL_ROOT/<L1>/.git 存在           → project（挂根群组下）
    L2: LOCAL_ROOT/<L1>/<L2>/.git 存在      → L1=subgroup, L2=project
    L3: LOCAL_ROOT/<L1>/<L2>/<L3>/.git 存在 → L1=subgroup, L2=subgroup, L3=project
    """
    targets: List[Target] = []

    # ── L1 仓库：目录自身含 .git ──
    for l1 in sorted(p for p in local_root.iterdir() if is_discoverable_dir(p)):
        if (l1 / ".git").exists():
            if matches_filters(l1, None, None, filters):
                targets.append(Target(l1_dir=l1, l2_dir=None, l3_dir=None))
            continue  # 是仓库则不再深入

        # ── L2 仓库：L1/L2 自身含 .git ──
        for l2 in sorted(p for p in l1.iterdir() if is_discoverable_dir(p)):
            if (l2 / ".git").exists():
                if matches_filters(l1, l2, None, filters):
                    targets.append(Target(l1_dir=l1, l2_dir=l2, l3_dir=None))
            else:
                # ── L3 仓库：L1/L2/L3 含 .git ──
                for l3 in sorted(p for p in l2.iterdir() if is_discoverable_dir(p)):
                    if matches_filters(l1, l2, l3, filters):
                        targets.append(Target(l1_dir=l1, l2_dir=l2, l3_dir=l3))
            if limit is not None and len(targets) >= limit:
                return targets
    return targets


def project_clean_url(base_url: str, full_path: str) -> str:
    return f"{base_url}/{full_path}.git"


def detect_slug_collisions(
    targets: List[Target],
    root_group_path: str,
) -> Dict[str, List[Path]]:
    """检测 slugify 后映射到同一 GitLab 路径的目录。"""
    seen: Dict[str, List[Path]] = {}
    for t in targets:
        l1_slug = slugify_path(t.l1_dir.name)
        if t.l2_dir is None:
            # L1 模式: {root}/{l1_slug}
            full = f"{root_group_path}/{l1_slug}"
            leaf = t.l1_dir
        elif t.l3_dir is None:
            # L2 模式: {root}/{l1_slug}/{l2_slug}
            l2_slug = slugify_path(t.l2_dir.name)
            full = f"{root_group_path}/{l1_slug}/{l2_slug}"
            leaf = t.l2_dir
        else:
            # L3 模式: {root}/{l1_slug}/{l2_slug}/{l3_slug}
            l2_slug = slugify_path(t.l2_dir.name)
            l3_slug = slugify_path(t.l3_dir.name)
            full = f"{root_group_path}/{l1_slug}/{l2_slug}/{l3_slug}"
            leaf = t.l3_dir
        seen.setdefault(full, []).append(leaf)
    return {k: v for k, v in seen.items() if len(v) > 1}


# ---------------------------------------------------------------------------
# 处理单个目标
# ---------------------------------------------------------------------------

def _process_target(client: GitLabClient, cfg: Config,
                    root_group: dict, l1_cache: Dict[str, dict],
                    l2_cache: Dict[str, dict],
                    target: Target) -> str:
    """
    处理单个 Target。返回状态:
      CREATED  - 新建项目并推送
      PUSHED   - 已存在项目，有新提交推送
      SKIPPED  - 已存在项目，无新提交（去重跳过）
      FAILED   - 处理失败
    """
    l1_name = target.l1_dir.name
    l1_slug = slugify_path(l1_name)
    l1_base_full = f"{cfg.root_group_path}/{l1_slug}"

    if target.l2_dir is None:
        # ── L1 模式：直接在根群组下创建 project ──
        repo_dir = target.l1_dir
        repo_name = l1_name
        display_path = l1_name
        logger.info("→ [L1] %s", display_path)
        parent_full = cfg.root_group_path
        parent_id = root_group["id"]
    elif target.l3_dir is None:
        # ── L2 模式：L1=subgroup, L2=project ──
        l2_name = target.l2_dir.name
        repo_dir = target.l2_dir
        repo_name = l2_name
        display_path = f"{l1_name}/{l2_name}"
        logger.info("→ [L2] %s", display_path)
    else:
        # ── L3 模式：L1=subgroup, L2=subgroup, L3=project ──
        l3_name = target.l3_dir.name
        l2_name = target.l2_dir.name
        repo_dir = target.l3_dir
        repo_name = l3_name
        display_path = f"{l1_name}/{l2_name}/{l3_name}"
        logger.info("→ [L3] %s", display_path)

    # dry-run
    if cfg.dry_run:
        if target.l2_dir is None:
            logger.info("  [dry-run] project=%s, local=%s", l1_base_full, repo_dir)
        elif target.l3_dir is None:
            logger.info("  [dry-run] subgroup=%s, project=%s, local=%s",
                        l1_base_full, f"{l1_base_full}/{slugify_path(target.l2_dir.name)}", repo_dir)
        else:
            logger.info("  [dry-run] subgroup=%s, subgroup=%s, project=%s, local=%s",
                        l1_base_full, f"{l1_base_full}/{slugify_path(target.l2_dir.name)}",
                        f"{l1_base_full}/{slugify_path(target.l2_dir.name)}/{slugify_path(target.l3_dir.name)}", repo_dir)
        return "SKIPPED"

    # ── 1. 创建/复用子群组 ──
    if target.l2_dir is None:
        # L1 模式: project 直接挂在根群组下
        project_parent_full = cfg.root_group_path
        project_parent_id = root_group["id"]
    else:
        # 创建/复用 L1 subgroup
        if l1_name in l1_cache:
            sub1 = l1_cache[l1_name]
        else:
            sub1 = client.ensure_subgroup(cfg.root_group_path, root_group["id"], l1_name)
            l1_cache[l1_name] = sub1
        l1_full = sub1.get("full_path") or f"{cfg.root_group_path}/{sub1.get('path', l1_slug)}"

        if target.l3_dir is None:
            # L2 模式: project 在 L1 subgroup 下
            project_parent_full = l1_full
            project_parent_id = sub1["id"]
        else:
            # L3 模式: 创建/复用 L2 subgroup
            l2_cache_key = f"{l1_name}/{target.l2_dir.name}"
            if l2_cache_key in l2_cache:
                sub2 = l2_cache[l2_cache_key]
            else:
                sub2 = client.ensure_subgroup(l1_full, sub1["id"], target.l2_dir.name)
                l2_cache[l2_cache_key] = sub2
            l2_full = sub2.get("full_path") or f"{l1_full}/{sub2.get('path', slugify_path(target.l2_dir.name))}"
            project_parent_full = l2_full
            project_parent_id = sub2["id"]

    # ── 2. 创建/复用项目 ──
    proj = client.ensure_project(project_parent_full, project_parent_id, repo_name)
    proj_full = proj.get("path_with_namespace") or f"{project_parent_full}/{proj.get('path', slugify_path(repo_name))}"

    # ── 3. 本地准备 ──
    repo = LocalRepo(path=repo_dir, repo_name=repo_name, workspace_root=cfg.local_root)
    has_existing_commit = repo.has_git() and repo.has_any_commit()

    # 已有提交的仓库，检查工作区是否脏
    if has_existing_commit:
        dirty = repo.dirty_status()
        if dirty:
            preview = "\n    ".join(dirty.splitlines()[:10])
            more = "" if len(dirty.splitlines()) <= 10 else f"\n    ...（共 {len(dirty.splitlines())} 项）"
            raise RuntimeError(
                "本地仓库存在未提交/未暂存的改动，请先 commit 或 stash 后再上传：\n"
                f"    {preview}{more}"
            )

    repo.ensure_git_init()
    if has_existing_commit:
        logger.info("  已有历史提交，跳过 README.md/.gitignore 自动补齐")
    else:
        repo.ensure_gitignore()
        repo.ensure_readme()
    repo.ensure_main_branch()
    committed = repo.stage_and_commit_if_needed()
    repo.ensure_main_branch()

    # ── 4. remote + 去重检查 ──
    clean_url = project_clean_url(cfg.gitlab_url, proj_full)
    repo.ensure_clean_origin(clean_url)

    # 去重: 远程已存在同样的 commit → 跳过推送
    if has_existing_commit:
        local_sha = repo.local_head_sha()
        remote_sha = repo.remote_head_sha(cfg.gitlab_token)
        if local_sha and remote_sha and local_sha == remote_sha:
            logger.info("  远程已是最新（%s），跳过推送", local_sha[:8])
            client.set_default_branch(proj["id"], "main")
            return "SKIPPED"

    # ── 5. 推送 ──
    repo.push_main(cfg.gitlab_token)
    client.set_default_branch(proj["id"], "main")

    return "PUSHED" if not committed else "CREATED" if not has_existing_commit else "PUSHED"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitLab 混合深度子组创建 + 批量上传")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="只打印将要执行的动作（默认）")
    mode.add_argument("--execute", action="store_true",
                      help="实际调用 API、初始化/提交本地 git 并推送")
    parser.add_argument("--local-root", "--root", dest="local_root",
                        type=Path, default=None,
                        help="自定义根目录，默认 LOCAL_ROOT 环境变量或当前目录")
    parser.add_argument("--verify-ssl", action="store_true",
                        help="启用 HTTPS 证书校验（默认关闭，兼容内网自签证书）")
    parser.add_argument("--limit", type=int, default=None,
                        help="最多处理多少个目标，便于分批执行")
    parser.add_argument("--only", action="append", default=[],
                        help="只处理名称包含该片段的目录；可重复传入")
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> Config:
    dry_run = not args.execute
    url = os.environ.get("GITLAB_URL", "").strip().rstrip("/")
    token = os.environ.get("GITLAB_TOKEN", "").strip()
    root = os.environ.get("GITLAB_ROOT_GROUP", "").strip().strip("/")

    local_env = os.environ.get("LOCAL_ROOT", "").strip()
    local_path = args.local_root or (Path(local_env) if local_env else Path.cwd())

    verify = args.verify_ssl or os.environ.get("GITLAB_VERIFY_SSL", "").strip().lower() in {"true", "1", "yes"}

    missing = []
    if not url:
        missing.append("GITLAB_URL")
    if not root:
        missing.append("GITLAB_ROOT_GROUP")
    if not dry_run and not token:
        missing.append("GITLAB_TOKEN")
    if missing:
        raise SystemExit(f"缺少 {' / '.join(missing)}，请设置环境变量")

    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit 必须是大于 0 的整数")
    if not local_path.is_dir():
        raise SystemExit(f"LOCAL_ROOT 不是目录: {local_path}")

    only = [item.strip() for item in args.only if item.strip()]
    return Config(url, token, root, local_path.resolve(), dry_run, verify, args.limit, only)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    cfg = load_config(args)

    logger.info("LOCAL_ROOT     = %s", cfg.local_root)
    logger.info("GITLAB_URL     = %s", cfg.gitlab_url)
    logger.info("ROOT_GROUP     = %s", cfg.root_group_path)
    logger.info("DRY_RUN        = %s", cfg.dry_run)
    if cfg.limit is not None:
        logger.info("LIMIT          = %s", cfg.limit)
    if cfg.only:
        logger.info("ONLY           = %s", ", ".join(cfg.only))

    client = GitLabClient(cfg.gitlab_url, cfg.gitlab_token, verify=cfg.verify_ssl)

    if cfg.dry_run:
        root_group = {"id": -1}
    else:
        root_group = client.get_group(cfg.root_group_path)
        if not root_group:
            logger.error("根 group 不存在: %s（请先在 GitLab 上手动创建）", cfg.root_group_path)
            return 2
        logger.info("根 group id=%s", root_group["id"])

    targets = discover_targets(cfg.local_root, cfg.only, cfg.limit)

    # 统计各模式数量
    l1_count = sum(1 for t in targets if t.l2_dir is None)
    l2_count = sum(1 for t in targets if t.l2_dir is not None and t.l3_dir is None)
    l3_count = sum(1 for t in targets if t.l3_dir is not None)
    parts = []
    if l1_count: parts.append(f"{l1_count} 个 L1 仓库")
    if l2_count: parts.append(f"{l2_count} 个 L2 仓库")
    if l3_count: parts.append(f"{l3_count} 个 L3 仓库")
    logger.info("发现 %s", "，".join(parts) if parts else "0 个目标")

    # slug 冲突检测
    collisions = detect_slug_collisions(targets, cfg.root_group_path)
    conflict_leaves: set[Path] = set()
    if collisions:
        logger.error("检测到 slug 冲突：以下本地目录 slugify 后映射到同一 GitLab 路径")
        for gitlab_path, dirs in collisions.items():
            logger.error("  GitLab 路径: %s", gitlab_path)
            for d in dirs:
                logger.error("    本地目录: %s", d)
            logger.error("  解决方案: 重命名其中一个本地目录，使 slugify 后的前缀不同")
            conflict_leaves.update(dirs)

    l1_cache: Dict[str, dict] = {}
    l2_cache: Dict[str, dict] = {}
    stats = {"CREATED": 0, "PUSHED": 0, "SKIPPED": 0, "FAILED": 0}
    summary: Dict[str, List[str]] = {"ok": [], "skip": [], "fail": []}

    for target in targets:
        # 确定目标叶子目录和标签
        if target.l2_dir is None:
            leaf, label = target.l1_dir, target.l1_dir.name
        elif target.l3_dir is None:
            leaf, label = target.l2_dir, f"{target.l1_dir.name}/{target.l2_dir.name}"
        else:
            leaf, label = target.l3_dir, f"{target.l1_dir.name}/{target.l2_dir.name}/{target.l3_dir.name}"

        if leaf in conflict_leaves:
            msg = f"{label}: slug 冲突，请重命名后重试"
            logger.error("× 跳过(冲突): %s", msg)
            stats["FAILED"] += 1
            summary["fail"].append(msg)
            continue

        try:
            status = _process_target(client, cfg, root_group, l1_cache, l2_cache, target)
            stats[status] = stats.get(status, 0) + 1
            if status in ("CREATED", "PUSHED"):
                summary["ok"].append(f"{label} ({status})")
            elif status == "SKIPPED":
                summary["skip"].append(f"{label} ({status})")
            else:
                summary["fail"].append(f"{label} ({status})")
        except Exception as exc:
            logger.exception("× 失败: %s -> %s", label, exc)
            stats["FAILED"] += 1
            summary["fail"].append(f"{label}: {exc}")

    logger.info("=" * 60)
    logger.info("结果: %d 新建, %d 已推送, %d 已跳过, %d 失败",
                stats["CREATED"], stats["PUSHED"], stats["SKIPPED"], stats["FAILED"])
    if summary["ok"]:
        logger.info("成功 %d 个:", len(summary["ok"]))
        for s in summary["ok"]:
            logger.info("  ✓ %s", s)
    if summary["skip"]:
        logger.info("跳过 %d 个:", len(summary["skip"]))
        for s in summary["skip"]:
            logger.info("  - %s", s)
    if summary["fail"]:
        logger.info("失败 %d 个:", len(summary["fail"]))
        for s in summary["fail"]:
            logger.info("  ✗ %s", s)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
