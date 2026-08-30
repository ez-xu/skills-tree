# 🌳 技能树

> 统一管理 **102 个 Agent Skills** 的 Git 子模块树,通过 Junction 链接暴露给所有支持 Agent Skills 标准的运行时(Claude Code、DSH、Codex CLI、Gemini CLI 等)。
> 每个技能源是独立的 git 子模块,技能本体由上游仓库维护,本仓库只管理**登记表**与**链接**。

## 这是什么

- **格式**: [Agent Skills 开放标准](https://agentskills.io/specification)(`SKILL.md` + YAML frontmatter),一个文件夹即可安装到支持该标准的任意 Agent。
- **技能存储位置**: 技能本体存放在 `_sources/<来源名>/`(git 子模块),根目录的 `two-way-steelman`、`codesize` 等目录是 **Windows Junction 链接**,指向 `_sources/` 里的真实技能目录。
- **它解决什么**: 用一棵树管理 24 个技能源、102 个技能,每个源可独立更新、独立追踪版本,根目录链接自动同步。

## 安装位置说明

**根目录下的每个技能目录(如 `two-way-steelman/`、`codesize/`)都是一个 Junction 链接,指向 `_sources/` 下的真实目录。** Agent 扫描 `~/.agents/skills/` 时看到的是根目录链接,加载的是链接后的真实 `SKILL.md`。

| 技能源 | 来源仓库 | 安装位置(子模块路径) | 技能数 |
|--------|---------|---------------------|:---:|
| embed-ai-tool | [LeoKemp223/embed-ai-tool](https://github.com/LeoKemp223/embed-ai-tool) | `_sources/embed-ai-tool/skills/` | 23 |
| kicad-happy | [aklofas/kicad-happy](https://github.com/aklofas/kicad-happy) | `_sources/kicad-happy/skills/` | 11 |
| OfficeCLI | [iOfficeAI/OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) | `_sources/OfficeCLI/skills/` | 10 |
| superpowers | [obra/superpowers](https://github.com/obra/superpowers) | `_sources/superpowers/skills/` | 13 |
| openvela-claude | [ez-xu/openvela-skills](https://github.com/ez-xu/openvela-skills) | `_sources/openvela-claude/skills/` | 13 |
| iart-ai 视频系列 | [iart-ai/tiktok-video-skills](https://github.com/iart-ai/tiktok-video-skills) 等 4 仓 | `_sources/*-video-skills/skills/` | 14 |
| jinghan-xu-skills | [ez-xu/jinghan-xu-skills](https://github.com/ez-xu/jinghan-xu-skills) | `_sources/jinghan-xu-skills/skills/` | 4 |
| orca | [stablyai/orca](https://github.com/stablyai/orca) | `_sources/orca/skills/` | 3 |
| qt-agent-skills | [TheQtCompanyRnD/agent-skills](https://github.com/TheQtCompanyRnD/agent-skills) | `_sources/qt-agent-skills/skills/` | 2 |
| claude-skills | [LiTianYun/claude-skills](https://github.com/LiTianYun/claude-skills) | `_sources/claude-skills/` | 2 |
| hallmark | [nutlope/hallmark](https://github.com/nutlope/hallmark) | `_sources/hallmark/skills/hallmark/` | 1 |
| easyeda-api | [easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill) | `_sources/easyeda-api-skill/` | 1 |
| skill-forge | [nekocode/skill-forge](https://github.com/nekocode/skill-forge) | `_sources/skill-forge/skills/skill-forge/` | 1 |
| agent-skill-creator | [FrancyJGLisboa/agent-skill-creator](https://github.com/FrancyJGLisboa/agent-skill-creator) | `_sources/agent-skill-creator/` | 1 |
| baidupan | [ez-xu/baidupan](https://github.com/ez-xu/baidupan) | `_sources/baidupan/` | 1 |
| drama-forge | [ez-xu/drama-forge](https://github.com/ez-xu/drama-forge) | `_sources/minimax-video-pipeline-skill/` | 1 |
| **two-way-steelman** | [chen1pengvincent/two-way-steelman](https://github.com/chen1pengvincent/two-way-steelman) | `_sources/two-way-steelman/`(SKILL.md 在仓库根) | 1 |
| 其他(mattpocock、addyosmani 等) | — | `_sources/<name>/` | — |

## 🆕 新电脑初始化

```bash
# 1. 克隆根仓库(含所有子模块,--remote-submodules 直接跟踪远端最新)
git clone --recurse-submodules --remote-submodules https://github.com/ez-xu/skills-tree.git ~/.agents/skills

# 2. 创建技能链接(Windows 用 PowerShell Junction,由 _sync.py 生成)
cd ~/.agents/skills
python _sync.py

# 完成!所有 Agent(Claude Code / DSH / Codex 等)会自动加载根目录链接后的技能
```

> ⚠️ 若某台机器 `bash` 不可用,直接用 `python _sync.py`(Windows 原生)。

## 🔄 日常更新

> 所有子模块已在 `.gitmodules` 中声明 `branch`,以下命令会把全部技能源更新到各自远端最新分支:

```bash
# 更新所有子模块到最新版本(跟随声明的分支)
cd ~/.agents/skills
git pull
git submodule update --init --remote --recursive

# 子模块指针已漂移,提交固定新版本
git add .gitmodules _sources/
git commit -m "chore(skills): 更新子模块到最新版本"

python _sync.py
```

## 📦 架构

```
.agents/skills/                  # git clone 到此目录
├── _sync.py                     # 一键创建 Junction + 校验(102 技能)
├── _tree.json                   # 技能分类树定义(来源登记 + 分类)
├── _tree.md                     # 自动生成的可视化文档
├── _sources/                    # 24 个 git 子模块(技能本体)
│   ├── embed-ai-tool/           # LeoKemp223/embed-ai-tool (23 技能)
│   ├── kicad-happy/             # aklofas/kicad-happy (11 技能)
│   ├── OfficeCLI/               # iOfficeAI/OfficeCLI (10 技能)
│   ├── superpowers/             # obra/superpowers (13 技能)
│   ├── openvela-claude/         # ez-xu/openvela-skills (13 技能)
│   ├── two-way-steelman/        # chen1pengvincent/two-way-steelman (1 技能)
│   └── ...                      # 其余 18 个子模块
│
├── two-way-steelman ──┐
├── codesize           ├── 102 个 Junction → _sources/*/skills/* 或 _sources/*/
├── kicad              │   (由 _sync.py 创建,不纳入 git)
└── ...               ──┘
```

## 🛠️ 维护操作

| 操作 | 命令 |
|------|------|
| 添加外部技能源 | `git submodule add <url> _sources/<name>` + 登记到 `_tree.json` |
| 更新单个子模块 | `cd _sources/<name> && git pull` |
| 重建所有链接 | `python _sync.py` |
| 查看完整树 | `cat _tree.md` |

---

## 变更日志

<!-- 新条目添加在最上方 -->

### 2026-08-30

- **feat**: 注册 two-way-steelman 双向钢人论证技能(chen1pengvincent/two-way-steelman,`tree`、`gitignore`、`gitmodules`),新增「🧠 思维方法」分类
- **fix**: 移除 adversaria 源(damionrashford/Adversaria,4 个技能依赖 Claude 专属插件机制,DSH 无法运行)(`tree`)
- **feat**: 接入 openvela 技能集(ez-xu/openvela-skills fork,13 技能)(`tree`、`gitignore`、`gitmodules`)
- **fix**: openvela-claude 技能列表修正为实际 13 个,补全 submodule 登记

### 2026-08-25

- **chore**: 移除 adversaria 插件(`tree`、`gitignore`、`gitmodules`、Claude 插件注册、`adv` 命令、agent-memory)
- **feat**: 注册 RedTeam 反驳技能——danielmiessler/Personal_AI_Infrastructure(18.7k star)(`tree`、`gitignore`、`gitmodules`)
- **chore**: 忽略 arkcli connect 自动安装的技能目录(`gitignore`)

### 2026-08-13

- **refactor**: `git-commit-assistant` 更名为 `git-commit-helper`——移除 claude-skills 源中的别名映射,链接名对齐上游技能目录名(`tree`、`gitignore`)

### 2026-08-11

- **feat**: 注册 drama-forge 视频生成技能(`tree`)
- **chore**: 忽略 baidupan/drama-forge 链接目录(`gitignore`)
- **chore**: 子模块声明 branch 并更新至远端最新(`gitmodules`)
- **feat**: 注册 adversaria/baidupan/drama-forge 子模块(`gitmodules`)
