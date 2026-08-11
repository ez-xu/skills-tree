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

def create_link(name, target):
    link = SKILLS_DIR / name
    src = (SKILLS_DIR / target).resolve()

    if link.is_symlink():
        return
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

    # ── 校验 ────────────────────────────────────────
    # 基于 _tree.json 注册清单校验（而非遍历文件系统），
    # 避免把 shared 等共享资源目录误判为技能。
    log(f"{YELLOW}[{n+1}/{n+2}]{NC} 校验技能完整性...")
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
    log(f"\n{YELLOW}[{n+2}/{n+2}]{NC} 生成 _tree.md...")

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

    md.append("\n---\n\n## 🚀 快速操作\n\n```bash")
    md.append("# 新电脑初始化\ngit clone --recurse-submodules https://github.com/ez-xu/skills-tree.git ~/.agents/skills\ncd ~/.agents/skills && bash _sync.sh")
    md.append("\n# 更新所有技能\ngit pull && git submodule update --remote --recursive && bash _sync.sh")
    md.append("```")

    with open(SKILLS_DIR / "_tree.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    log(f"  {GREEN}[OK]{NC} _tree.md 已生成")
    log(f"\n{GREEN}=== 同步完成! ==={NC}")

if __name__ == "__main__":
    main()
