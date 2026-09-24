#!/usr/bin/env python3
"""Skills Tree Sync — 读取 _tree.json，创建链接、校验、生成文档。"""

import json, os, sys, subprocess, platform, shutil
from datetime import datetime
from pathlib import Path

SKILLS_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
TREE_FILE = SKILLS_DIR / "_tree.json"
IS_WINDOWS = platform.system() == "Windows"
if IS_WINDOWS:
    sys.stdout.reconfigure(encoding="utf-8")

GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
RED    = "\033[0;31m"
NC     = "\033[0m"

def log(msg):
    print(msg)

def is_link(p: Path) -> bool:
    """跨平台判断 symlink / Windows junction。

    Python 的 Path.is_symlink() 在 Windows 上不识别 junction
    （_sync 创建链接用的就是 junction），需要按 reparse point 检测。
    """
    if p.is_symlink():
        return True
    if IS_WINDOWS:
        try:
            return bool(p.lstat().st_file_attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except (AttributeError, OSError):
            return False
    return False

def remove_link(path: Path):
    """删除链接/junction 本身，不触碰目标目录。"""
    try:
        os.rmdir(path)   # junction 视为空目录，rmdir 仅移除联接
    except OSError:
        path.unlink()    # 符号链接

def expected_links(tree: dict) -> set:
    """根据 _tree.json 算出根目录应有的链接名集合。

    登记来源的每个技能（含 aliases 改名）+ extra_links（共享资源等非技能目录）。
    """
    expected = set(tree.get("extra_links", []))
    for src in tree["sources"]:
        for skill in src["skills"]:
            expected.add(src.get("aliases", {}).get(skill, skill))
    return expected

def cleanup_stale_links(tree: dict):
    """清理未登记的残留链接（如技能改名后遗留的旧链接）。

    保留名单来自 _tree.json 的 extra_links（共享资源等非技能目录），
    其余根目录下指向外部的链接一律删除。
    """
    expected = expected_links(tree)

    removed = []
    for p in sorted(SKILLS_DIR.iterdir()):
        if p.name.startswith(".") or p.name == "_sources" or not is_link(p):
            continue
        if p.name not in expected:
            remove_link(p)
            removed.append(p.name)

    if removed:
        log(f"  {YELLOW}[!]{NC} 清理未登记链接: {', '.join(removed)}")
    return removed

# 各 Agent 的 skills 目录（相对 HOME）。AGENTS.md 要求每个 Agent 都能看到全部技能：
# 整目录是 Junction 的会自动跟随根目录，真实目录（如 Codex，须与自带 .system/ 共存）
# 则必须逐条建链接，否则新技能永远不会出现——曾经的 34 条缺失就是这么来的。
AGENT_DIRS = [".claude", ".qwen", ".codex", ".commandcode", ".kimi-code", ".codegeex"]

def link_agent_dirs(tree: dict):
    """把根目录的技能链接同步到各 Agent 的 skills 目录。

    只增不删、绝不反向同步：
      - 整目录已是 Junction 的 Agent（自动跟随根目录）直接跳过；
      - 真实目录里的存量内容（如 Codex 的 .system/）与同名实体目录绝不触碰；
      - 只有断链（目标已消失）才重建。
    """
    expected = expected_links(tree)
    extra = set(tree.get("extra_links", []))
    home = Path.home()
    created, repaired, whole, absent, real = [], [], [], [], []

    for agent in AGENT_DIRS:
        d = home / agent / "skills"
        if not d.is_dir():
            absent.append(agent)
            continue
        if is_link(d):
            whole.append(agent)
            continue
        real.append(agent)
        for name in sorted(expected):
            src = SKILLS_DIR / name
            if not src.is_dir():
                continue
            link = d / name
            if is_link(link):
                if link.exists():
                    continue          # 健康链接：保持原样
                remove_link(link)     # 断链：目标已消失，先删再建
                repaired.append(f"{agent}/{name}")
            elif link.exists():
                continue              # 真实目录/文件：不碰

            if IS_WINDOWS:
                subprocess.run([
                    "powershell.exe", "-NoProfile", "-Command",
                    f"New-Item -ItemType Junction -Path '{link}' -Target '{src}' -Force"
                ], capture_output=True)
            else:
                link.symlink_to(src, target_is_directory=True)
            created.append(f"{agent}/{name}")

    for a in whole:
        log(f"  {GREEN}[OK]{NC} {a}: 整目录 Junction，自动跟随")
    for a in real:
        n = sum(1 for x in created if x.startswith(f"{a}/"))
        r = sum(1 for x in repaired if x.startswith(f"{a}/"))
        log(f"  {GREEN}[OK]{NC} {a}: 真实目录，逐条同步（新建 {n}，重建 {r}）")
    for a in absent:
        log(f"  {YELLOW}[-]{NC} {a}: 未安装，跳过")

    # 复核：真实目录型 Agent 的每一条链接都要真能读到 SKILL.md，
    # 否则"新建 0 条"这种输出会掩盖"整类被静默跳过"——Codex 就是这么烂掉的。
    missing = []
    for a in real:
        for name in sorted(expected):
            p = home / a / "skills" / name
            # extra_links 是共享资源目录（如 shared），不是技能，没有 SKILL.md
            ok = p.is_dir() if name in extra else (p / "SKILL.md").exists()
            if not ok:
                missing.append(f"{a}/{name}")
    if missing:
        log(f"  {RED}[X]{NC} {len(missing)} 条 Agent 链接不可达: {', '.join(missing[:10])}"
            + (" ..." if len(missing) > 10 else ""))
    else:
        log(f"  {GREEN}[OK]{NC} {len(real)} 个真实目录型 Agent × {len(expected)} 条链接，全部可达")
    return created, repaired, missing

def create_link(name, target):
    link = SKILLS_DIR / name
    src = (SKILLS_DIR / target).resolve()

    if is_link(link):
        # 链接已存在：若目标与登记不一致（如技能换了来源仓库），重建
        try:
            cur = link.resolve()
            if os.path.normcase(str(cur)) == os.path.normcase(str(src)):
                return
            log(f"  {YELLOW}[~]{NC} {name}: 目标变更 -> {target}")
            remove_link(link)
        except OSError:
            remove_link(link)
    if link.is_dir():
        log(f"  {YELLOW}[!]{NC} 移除实体副本: {name}/")
        shutil.rmtree(str(link), ignore_errors=True)

    if IS_WINDOWS:
        subprocess.run([
            "powershell.exe", "-NoProfile", "-Command",
            f"New-Item -ItemType Junction -Path '{link}' -Target '{src}' -Force"
        ], capture_output=True)
    else:
        link.symlink_to(src, target_is_directory=True)

    log(f"  {GREEN}[OK]{NC} {name} -> {target}")

def main():
    with open(TREE_FILE, "r", encoding="utf-8") as f:
        tree = json.load(f)

    log(f"{CYAN}=== Skills Tree Sync ==={NC}")
    log("")

    n = len(tree["sources"])

    # ── 创建链接 ─────────────────────────────────────
    for i, src in enumerate(tree["sources"], 1):
        name = src["name"]
        base = SKILLS_DIR / src["path"] / src["skills_dir"]
        aliases = src.get("aliases", {})

        log(f"{YELLOW}[{i}/{n}]{NC} 链接 {name}...")

        for skill in src["skills"]:
            d = base / skill
            if not d.is_dir():
                # 单技能仓库：skills_dir 自身就是技能目录
                d = base
            if d.is_dir():
                link_name = aliases.get(skill, skill)
                create_link(link_name, str(d.relative_to(SKILLS_DIR)))
            else:
                log(f"  {RED}[X]{NC} {skill}: 源路径不存在")
        log("")

    # ── 清理残留链接 ─────────────────────────────────
    log(f"{YELLOW}[{n+1}/{n+4}]{NC} 清理未登记链接...")
    removed = cleanup_stale_links(tree)
    if not removed:
        log("  无残留")
    log("")

    # ── 同步各 Agent 的 skills 目录 ──────────────────
    log(f"{YELLOW}[{n+2}/{n+4}]{NC} 同步各 Agent 链接...")
    if "--no-agents" in sys.argv:
        log(f"  {YELLOW}[-]{NC} 已用 --no-agents 跳过")
        agent_missing = []
    else:
        _, _, agent_missing = link_agent_dirs(tree)
    log("")

    # ── 校验 ────────────────────────────────────────
    # 基于 _tree.json 注册清单校验（而非遍历文件系统），
    # 避免把 shared 等共享资源目录误判为技能。
    log(f"{YELLOW}[{n+3}/{n+4}]{NC} 校验技能完整性...")
    total = 0
    missed = 0

    for src in tree["sources"]:
        aliases = src.get("aliases", {})
        for skill in src["skills"]:
            link_name = aliases.get(skill, skill)
            link_dir = SKILLS_DIR / link_name
            total += 1
            if link_dir.is_dir() and (link_dir / "SKILL.md").exists():
                log(f"  {GREEN}[OK]{NC} {link_name}")
            else:
                log(f"  {RED}[X]{NC} {link_name} (链接或 SKILL.md 缺失)")
                missed += 1

    if missed == 0:
        log(f"\n  {GREEN}全部 {total} 个技能校验通过{NC}")
    else:
        log(f"\n  {RED}{missed}/{total} 个技能缺失{NC}")

    # ── 生成 _tree.md ───────────────────────────────
    log(f"\n{YELLOW}[{n+4}/{n+4}]{NC} 生成 _tree.md...")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = []
    md.append(f"# 🌳 技能树\n\n> 自动生成于: {now}\n> 仓库: https://github.com/ez-xu/skills-tree\n\n## 📊 概览\n\n| 分类 | 技能数 |\n|------|--------|")

    for cat, info in tree["categories"].items():
        md.append(f"| {info['label']} | {len(info['skills'])} |")
    md.append(f"| **合计** | **{total}** |\n")

    for cat_key, info in tree["categories"].items():
        md.append(f"---\n\n## {info['label']}\n\n| 技能 | 来源 |\n|------|------|")
        for skill in info["skills"]:
            source = "自维护"
            for s in tree["sources"]:
                if skill in s["skills"] or skill in s.get("aliases", {}).values():
                    source = s["name"]
                    break
            md.append(f"| {skill} | {source} |")
        md.append("")

    md.append("---\n\n## 🔗 外部来源\n\n| 来源 | 仓库 | 技能数 |\n|------|------|--------|")
    for src in tree["sources"]:
        repo = src["remote"].split("/")[-1].replace(".git", "")
        md.append(f"| {src['name']} | [{repo}]({src['remote']}) | {len(src['skills'])} |")

    dormant = tree.get("dormant", [])
    if dormant:
        md.append("\n---\n\n## 💤 保留但未注册\n")
        md.append("> 这些仓库**留在 `_sources/` 里，但刻意不注册技能**：不建链接、不进任何 Agent 的上下文。")
        md.append("> 要启用就把它们移进 `sources` 并加入 `categories`，再跑一次 `python _sync.py`。\n")
        md.append("| 子模块 | 可提供技能数 | 不注册的原因 |")
        md.append("|--------|:---:|------|")
        for d in dormant:
            md.append(f"| `{d['path']}` | {d.get('skills', 0)} | {d['reason']} |")

    md.append("\n---\n\n## 🚀 快速操作\n\n```bash")
    md.append("# 新电脑初始化\ngit clone --recurse-submodules https://github.com/ez-xu/skills-tree.git ~/.agents/skills\ncd ~/.agents/skills && bash _sync.sh")
    md.append("\n# 更新所有技能\ngit pull && git submodule update --remote --recursive && bash _sync.sh")
    md.append("```")

    with open(SKILLS_DIR / "_tree.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    log(f"  {GREEN}[OK]{NC} _tree.md 已生成")
    if agent_missing:
        log(f"\n{RED}⚠ 有 {len(agent_missing)} 条 Agent 链接不可达，见上面的 [X]{NC}")
    log(f"\n{GREEN}=== 同步完成! ==={NC}")

if __name__ == "__main__":
    main()
