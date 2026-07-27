---
name: gitlab-download
description: >
  Use when recursively downloading all projects from a GitLab group. Even if
  user says 下载gitlab or 同步代码, use for bulk GitLab clone/pull/sync. Do NOT
  use when cloning one known repo, reading code, or git help queries.
user-invocable: true
---

# GitLab 批量下载

从 GitLab 群组递归下载所有项目到本地，保留中文显示名作为目录名，
维护 GitLab 子群组层级结构。已存在的仓库执行 fetch + ff-only pull，
已是最新的项目自动跳过（SKIPPED）。所有操作前 dry-run 预览，确认后执行。

技能自带完整 Python 下载脚本（`scripts/download.py`），不依赖外部 `_tools/`。

## Prerequisites

- Python 3.8+，requests + urllib3：
  ```bash
  pip install -r "$SKILL_DIR/scripts/requirements.txt"
  ```
- 推荐安装 `glab` CLI（`scoop install glab`），也可手动设置环境变量

## Steps

### 0. 认证检测

```bash
[ -f "$SKILL_DIR/../shared/scripts/gitlab_auth.sh" ] || { echo "缺少共享认证脚本，请确认 shared/ 目录已安装" >&2; return 1; }
source "$SKILL_DIR/../shared/scripts/gitlab_auth.sh"
resolve_gitlab_auth
```

脚本按优先级检查：glab config → 环境变量 → 引导设置。

- glab 已配置 → 自动从 `~/.config/glab-cli/config.yml` 提取 URL + token
- glab 未安装 → 建议 `scoop install glab` 后 `glab auth login --hostname <服务器IP>`
- 手动模式 → 设置环境变量：
  ```bash
  export GITLAB_URL="https://<服务器IP>"
  export GITLAB_TOKEN="<personal access token>"
  export GITLAB_ROOT_GROUP="<根群组路径>"
  ```

### 1. 确认工作目录

`LOCAL_ROOT` 默认为当前目录：
```bash
export LOCAL_ROOT="<本地目标目录>"   # 可选
```

### 2. Dry-run 预览

```bash
python "$SKILL_DIR/scripts/download.py" [--filter <关键词>] [--include-archived]
```

展示：服务器地址、根群组路径、本地目录、项目总数、每个项目 [CLONE]/[PULL] 状态。

>20 个项目时建议用 `--filter` 缩小范围分批执行。

### 3. 用户确认后执行

展示 dry-run 结果，询问用户确认后执行：

```bash
python "$SKILL_DIR/scripts/download.py" --execute [--filter <关键词>] [--include-archived] [--report report.json]
```

脚本末尾会打印统计行：`结果: X 新克隆, X 已更新, X 已是最新跳过, X 失败`，直接提取这些数字。
也可用 `--report report.json` 输出结构化 JSON：
  ```bash
  python -c "import json; d=json.load(open('report.json')); print(d['stats'])"
  ```

### 4. 生成提交历史摘要

从 `--report report.json` 读取结果（或解析脚本输出中的 `[CLONE]`/`[PULL]` 行），
对每个项目取最近提交。`find` 自动适配任意目录深度：

```bash
find "$LOCAL_ROOT" -name .git -mindepth 2 -maxdepth 8 -type d | while read gitdir; do
  proj_dir=$(dirname "$gitdir")
  rel=$(echo "$proj_dir" | sed "s|^$LOCAL_ROOT/||")
  echo "| $rel | $(git -C "$proj_dir" log --oneline -1 --format='%h %an %s' 2>/dev/null || echo '-') |"
done
```

汇总为 Markdown 表格：

| 项目 | 状态 | 最近提交 |
|------|------|----------|
| `path/with/namespace` | CLONED / PULLED / SKIPPED | `abc1234 张三 修复bug` |

## Verification

- 下载目录确认：`ls <LOCAL_ROOT>/<subgroup>/<project>/.git`
- `--report report.json` 验证：`python -c "import json; d=json.load(open('report.json')); assert d['stats']['FAILED']==0, f\"{d['stats']['FAILED']} failures\"; print('OK')"`
- Token 安全：`git -C <project_dir> remote get-url origin` 应无 token
- 已归档项目默认跳过，加 `--include-archived` 才处理

## Notes

- 中文名映射通过 GitLab API 查询群组显示名实现
- `pull --ff-only` 失败 → 警告并跳过，不强制覆盖
- 旧 slug 命名目录会检测并提示重命名
- `Already up to date.` 的项目标记 SKIPPED，避免无意义 pull
