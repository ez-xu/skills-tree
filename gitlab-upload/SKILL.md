---
name: gitlab-upload
description: >
  Use when batch-creating GitLab groups and projects from local L1/L2/L3 dirs,
  then pushing repos. Even if user says 上传代码, use for multi-project batch ops.
  Do NOT use when pushing single repo, running git push directly, or read-only
  GitLab queries.
user-invocable: true
---

# GitLab 批量上传

扫描本地工作区目录，自动发现 L1/L2/L3 三种深度的 Git 仓库，
在 GitLab 上幂等创建子群组和项目，初始化 git 仓库并推送。
中文目录名自动提取 ASCII 部分作为 GitLab path slug，完整名称保留为显示名。
已存在且无新提交的项目自动跳过（SKIPPED）。所有操作前 dry-run 预览，确认后执行。

技能自带完整 Python 上传脚本（`scripts/upload.py`），不依赖外部 `_tools/`。

## Prerequisites

- Python 3.8+，requests + urllib3：
  ```bash
  pip install -r "$SKILL_DIR/scripts/requirements.txt"
  ```
- 推荐安装 `glab` CLI（`scoop install glab`），也可手动设置环境变量
- 依赖 `shared/scripts/gitlab_auth.sh`（与 gitlab-download 共用，随技能一起安装）

## Steps

### 0. 认证检测

```bash
source "$SKILL_DIR/../shared/scripts/gitlab_auth.sh"
resolve_gitlab_auth
```

脚本按优先级检查：glab config → 环境变量 → 引导设置。

- glab 已配置 → 自动从 `~/.config/glab-cli/config.yml` 提取 URL + token
- 手动模式 → 设置环境变量：
  ```bash
  export GITLAB_URL="https://<服务器IP>"
  export GITLAB_TOKEN="<personal access token>"
  export GITLAB_ROOT_GROUP="<根群组路径>"
  ```

### 1. 确认工作目录

```bash
export LOCAL_ROOT="<本地根目录>"   # 可选，默认当前目录
```

### 2. Dry-run 预览

```bash
python "$SKILL_DIR/scripts/upload.py" --dry-run [--limit N] [--only <关键词>]
```

自动发现三种深度的仓库（同一遍历中共存）：

- **L1**：`LOCAL_ROOT/<L1>/.git` → project（挂在根群组下）
- **L2**：`LOCAL_ROOT/<L1>/<L2>/.git` → L1=subgroup, L2=project
- **L3**：`LOCAL_ROOT/<L1>/<L2>/<L3>/.git` → L1=subgroup, L2=subgroup, L3=project

展示：每种深度的目标数量、中文名映射示例、slug 冲突检测结果。

**确认标准**：slug 冲突为 0、L1/L2/L3 映射与预期一致、GitLab 群组路径正确，
三项均通过方可继续 Step 3。有冲突则按 Notes 重命名目录后重新 dry-run。

>10 个目标时建议用 `--limit` 或 `--only` 分批执行。

### 3. 用户确认后执行

dry-run 结果通过确认标准后，向用户展示摘要并获取确认，然后执行：

```bash
python "$SKILL_DIR/scripts/upload.py" --execute [--limit N] [--only <关键词>]
```

每个仓库的处理流程（遇 slug 冲突或 `git status --porcelain` 非空时脚本中止，参见 Notes）：
1. 幂等创建/复用子群组（已存在则直接复用）
2. 幂等创建/复用项目
3. `git init -b main`（如非 git 仓库）
4. 补齐 `.gitignore` + 生成 `README.md`（已有提交则跳过）
5. 确保 `main` 分支（含 `master → main` 迁移）
6. `git add -A` + `git commit`
7. **去重检查**：比较本地 HEAD vs 远程 HEAD，相同则跳过推送（SKIPPED）
8. `git push -u origin main`

已有 git 历史的仓库跳过 README/.gitignore 自动生成。工作区有未提交改动时中止。

### 4. 生成上传摘要

对每个处理的仓库：
```bash
git -C <repo_dir> log --oneline -5 --format="%h %an %s"
```

汇总为 Markdown 表格：

| 深度 | L1 | L2 | L3 | GitLab 路径 | 状态 | 最近提交 |
|------|----|----|----|-------------|------|----------|
| L2 | `S32K144` | `BCMU` | — | `...S32K144/BCMU` | PUSHED | `abc1234 新提交` |
| L3 | `S32K144` | `BCMU` | `测试板` | `...S32K144_BCMU` | CREATED | `def5678 init` |
| L1 | `Top` | — | — | `...Top` | SKIPPED | — |

## Verification

- API 确认：`curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" "$GITLAB_URL/api/v4/projects?search=<slug>"`
- 远程抽查：`git -C <repo_dir> ls-remote origin`
- Token 安全：`git -C <repo_dir> remote get-url origin` 应无 token

## Notes

- **中文名策略**：`[^A-Za-z0-9_.\-]` → `-`，ASCII 自然保留为 path slug
- **slug 冲突**：检测并拒绝处理，提示重命名目标目录
- **工作区脏**：已有提交的仓库 `git status --porcelain` 非空时中止
- **去重上传**：`git ls-remote origin` 比较 HEAD SHA，相同则 SKIPPED
- **Token 安全**：通过 `http.extraHeader` 传入，不写入 git config
