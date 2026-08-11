# 🌳 技能树

> 统一管理 57 个 Claude Code 技能的 Git 子模块树。

## 🆕 新电脑初始化

```bash
# 1. 克隆根仓库（含所有子模块，--remote-submodules 直接跟踪远端最新）
git clone --recurse-submodules --remote-submodules https://github.com/ez-xu/skills-tree.git ~/.agents/skills

# 2. 创建技能链接（Windows 用 PowerShell Junction）
cd ~/.agents/skills
bash _sync.sh

# 完成！Claude Code 会自动加载所有技能
```

## 🔄 日常更新

> 所有子模块已在 `.gitmodules` 中声明 `branch`，以下命令会把全部技能组件更新到各自远端最新分支：

```bash
# 更新所有子模块到最新版本（跟随声明的分支）
cd ~/.agents/skills
git pull
git submodule update --init --remote --recursive

# 子模块指针已漂移，提交固定新版本
git add _sources/ easyeda-api
git commit -m "chore(skills): 更新子模块到最新版本"

bash _sync.sh
```

## 📦 架构

```
.agents/skills/                  # git clone 到此目录
├── _sync.sh                     # 一键创建 Junction + 校验
├── _tree.yaml                   # 技能分类树定义
├── _tree.md                     # 自动生成的可视化文档
├── _sources/                    # 9 个 git 子模块
│   ├── embed-ai-tool/           # LeoKemp223/embed-ai-tool (24 技能)
│   ├── kicad-happy/             # aklofas/kicad-happy (11 技能)
│   ├── OfficeCLI/               # iOfficeAI/OfficeCLI (10 技能)
│   ├── orca/                    # stablyai/orca (3 技能)
│   ├── jinghan-xu-skills/       # ez-xu/jinghan-xu-skills (3 技能)
│   ├── qt-agent-skills/         # TheQtCompanyRnD/agent-skills (2 技能)
│   ├── hallmark/                # nutlope/hallmark (1 技能)
│   ├── skill-forge/             # nekocode/skill-forge (1 技能)
│   └── easyeda-api-skill/       # easyeda/easyeda-api-skill (1 技能)
│
├── build-keil  ──┐
├── can-debug     ├── 54 个 Junction → _sources/*/skills/*
├── kicad         │   (由 _sync.sh 创建，不纳入 git)
└── ...          ──┘
```

## 🛠️ 维护操作

| 操作 | 命令 |
|------|------|
| 添加外部技能源 | `git submodule add <url> _sources/<name>` |
| 更新单个子模块 | `cd _sources/<name> && git pull` |
| 重建所有链接 | `bash _sync.sh` |
| 查看完整树 | `cat _tree.md` |

---

## 变更日志

<!-- 新条目添加在最上方 -->

### 2026-08-11

- **feat**: 注册 drama-forge 视频生成技能（`tree`）
- **chore**: 忽略 baidupan/drama-forge 链接目录（`gitignore`）
- **chore**: 子模块声明 branch 并更新至远端最新（`gitmodules`）
