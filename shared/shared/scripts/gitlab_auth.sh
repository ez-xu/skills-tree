#!/usr/bin/env bash
# gitlab-auth.sh — GitLab 认证解析（glab CLI 优先，环境变量回退）
#
# 用法: source gitlab-auth.sh && resolve_gitlab_auth
# 输出: GITLAB_URL GITLAB_TOKEN GITLAB_ROOT_GROUP 环境变量
# 返回: 0=成功, 1=需要用户干预
set -euo pipefail

# ── glab config 路径（兼容 Windows Git Bash / MSYS2）─────────────────
_find_glab_config() {
    local cfg
    for cfg in \
        "${HOME}/.config/glab-cli/config.yml" \
        "${USERPROFILE:-}/.config/glab-cli/config.yml"; do
        if [ -f "$cfg" ]; then
            echo "$cfg"
            return 0
        fi
    done
    return 1
}

# ── 从 glab config 提取认证 ─────────────────────────────────────────
resolve_from_glab() {
    local glab_bin cfg
    glab_bin=$(command -v glab 2>/dev/null) || return 1
    cfg=$(_find_glab_config) || return 1

    # 提取 hosts: 段下所有非 gitlab.com 的 host 名
    # YAML 结构: "    <hostname>:" (4 空格缩进)
    local hosts
    hosts=$(awk '
        /^hosts:/ { in_hosts=1; next }
        in_hosts && /^    [^ ]/ { gsub(/:.*/, ""); gsub(/^ +/, ""); print }
        in_hosts && /^[a-z]/   { exit }
    ' "$cfg" | grep -v '^gitlab\.com$' || true)

    if [ -z "$hosts" ]; then
        return 1
    fi

    # 选第一个有 token 的 host
    local selected_host token
    for h in $hosts; do
        token=$("$glab_bin" config get token --host "$h" 2>/dev/null || true)
        if [ -n "$token" ] && [ "$token" != "null" ]; then
            selected_host="$h"
            break
        fi
    done
    [ -n "${selected_host:-}" ] || return 1

    # 确定协议（默认 https）
    local proto
    proto=$(awk -v host="$selected_host" '
        /^hosts:/ { in_hosts=1; next }
        in_hosts && $0 ~ "^    " host ":" { cur=host; next }
        in_hosts && cur && /api_protocol/ { gsub(/.*: /, ""); print; exit }
        in_hosts && /^[a-z]/ { exit }
    ' "$cfg" 2>/dev/null || true)
    proto="${proto:-https}"

    GITLAB_URL="${proto}://${selected_host}"
    GITLAB_TOKEN="$token"
    return 0
}

# ── 从环境变量读取 ──────────────────────────────────────────────────
resolve_from_env() {
    if [ -n "${GITLAB_URL:-}" ] && [ -n "${GITLAB_TOKEN:-}" ]; then
        return 0
    fi
    return 1
}

# ── 检查缺少什么并输出引导信息 ──────────────────────────────────────
check_missing() {
    local missing=""
    [ -z "${GITLAB_URL:-}" ] && missing="GITLAB_URL $missing"
    [ -z "${GITLAB_TOKEN:-}" ] && missing="GITLAB_TOKEN $missing"
    [ -z "${GITLAB_ROOT_GROUP:-}" ] && missing="GITLAB_ROOT_GROUP $missing"

    if [ -n "$missing" ]; then
        echo "[gitlab-auth] 缺少配置: $missing" >&2
        return 1
    fi
    return 0
}

# ── 引导信息 ────────────────────────────────────────────────────────
print_glab_guide() {
    cat >&2 << 'EOF'
[gitlab-auth] 未检测到 GitLab 认证。请按以下步骤设置:

  1. 安装 glab CLI:
     scoop install glab
     或: winget install GitLab.GitLab

  2. 登录你的 GitLab 服务器:
     glab auth login --hostname <你的服务器IP或域名>

  3. 设置环境变量:
     export GITLAB_ROOT_GROUP="<你的根群组路径，如 embedded/bcmu/standard>"

  或者直接设置环境变量跳过 glab:
     export GITLAB_URL="https://<服务器IP>"
     export GITLAB_TOKEN="<你的personal access token>"
     export GITLAB_ROOT_GROUP="<根群组路径>"

EOF
}

# ── 主导出函数 ──────────────────────────────────────────────────────
# 优先级: glab config → 环境变量 → 引导
# 成功时设置 GITLAB_URL / GITLAB_TOKEN / GITLAB_ROOT_GROUP 并返回 0
# 失败时打印引导信息并返回 1
resolve_gitlab_auth() {
    # 1. 尝试从 glab 获取（覆盖可能为空的 env）
    local glab_url glab_token
    if resolve_from_glab 2>/dev/null; then
        glab_url="$GITLAB_URL"
        glab_token="$GITLAB_TOKEN"
    fi

    # 2. 环境变量优先覆盖（用户显式设置 > glab 自动发现）
    GITLAB_URL="${GITLAB_URL:-$glab_url}"
    GITLAB_TOKEN="${GITLAB_TOKEN:-$glab_token}"

    # 3. 检查完整性
    if check_missing; then
        echo "[gitlab-auth] ✓ 认证就绪: ${GITLAB_URL}" >&2
        return 0
    fi

    # 4. 缺少配置，检查是否完全没有 glab 和 env
    if ! command -v glab >/dev/null 2>&1 && [ -z "${GITLAB_URL:-}" ] && [ -z "${GITLAB_TOKEN:-}" ]; then
        print_glab_guide
    elif [ -z "${GITLAB_URL:-}" ] || [ -z "${GITLAB_TOKEN:-}" ]; then
        echo "[gitlab-auth] glab 已配置但 URL/token 不完整，请检查:" >&2
        echo "  glab auth status" >&2
        echo "  glab config get token --host <hostname>" >&2
    fi

    # 只提示 GITLAB_ROOT_GROUP，不硬失败（有时可以从其他方式推断）
    if [ -z "${GITLAB_ROOT_GROUP:-}" ]; then
        echo "[gitlab-auth] 提示: GITLAB_ROOT_GROUP 未设置（可通过环境变量配置）" >&2
    fi

    return 1
}

# CLI 模式：直接调用时打印当前认证状态
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    if resolve_gitlab_auth; then
        echo "GITLAB_URL=${GITLAB_URL}"
        echo "GITLAB_TOKEN=${GITLAB_TOKEN}"
        echo "GITLAB_ROOT_GROUP=${GITLAB_ROOT_GROUP:-<未设置>}"
    else
        exit 1
    fi
fi
