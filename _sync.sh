#!/bin/bash
# Skills Tree 同步脚本
# 用法: bash _sync.sh
#
# 在 Windows 上使用 PowerShell Junction (无需管理员权限)
# 在 Linux/Mac 上使用 ln -s

set -e

SKILLS_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SKILLS_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       Skills Tree Sync               ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ── 平台检测 ─────────────────────────────────────────────
IS_WINDOWS=false
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=true ;;
esac

# ── 创建链接函数 ──────────────────────────────────────────
create_link() {
    local link_name="$1"
    local link_target="$2"
    local display_target="$3"

    # 如果已存在且是链接/挂载点，跳过
    if [ -L "$link_name" ] || [ -f "$link_name" ]; then
        return 0
    fi

    # 如果已存在但是实体目录，先移除
    if [ -d "$link_name" ]; then
        echo "  ${YELLOW}⚠${NC} 移除实体副本: $link_name/"
        rm -rf "$link_name"
    fi

    if $IS_WINDOWS; then
        # Windows: 使用 PowerShell Junction (无需管理员)
        local win_link=$(cygpath -w "$link_name" 2>/dev/null || echo "$link_name")
        local win_target=$(cygpath -w "$link_target" 2>/dev/null || echo "$link_target")
        powershell.exe -NoProfile -Command \
            "New-Item -ItemType Junction -Path '$win_link' -Target '$win_target' -Force" \
            >/dev/null 2>&1
    else
        # Unix: 标准 symlink
        ln -sf "$link_target" "$link_name"
    fi

    echo "  ${GREEN}✓${NC} $link_name -> $display_target"
}

# ── 1. 同步 kicad-happy 技能 ──────────────────────────────
echo -e "${YELLOW}[1/10]${NC} 链接 kicad-happy 技能..."

KICAD_HAPPY_BASE="$SKILLS_DIR/_sources/kicad-happy/skills"
KICAD_SKILLS=(bom datasheets digikey element14 emc jlcpcb kicad lcsc mouser pcbway spice)

for skill in "${KICAD_SKILLS[@]}"; do
    src="$KICAD_HAPPY_BASE/$skill"
    if [ -d "$src" ]; then
        create_link "$skill" "$src" "kicad-happy/skills/$skill"
    else
        echo "  ${RED}✗${NC} $skill: 源路径不存在 $src"
    fi
done

# ── 2. 同步 embed-ai-tool 技能 ────────────────────────────
echo ""
echo -e "${YELLOW}[2/10]${NC} 链接 embed-ai-tool 技能..."

EMBED_BASE="$SKILLS_DIR/_sources/embed-ai-tool/skills"
EMBED_SKILLS=(build-cmake build-iar build-idf build-keil build-makefile build-platformio debug-gdb-openocd debug-jlink debug-platformio flash-idf flash-jlink flash-keil flash-openocd flash-platformio logic-analyzer memory-analysis modbus-debug rtos-debug serial-monitor serial-shell static-analysis visa-debug workflow)

for skill in "${EMBED_SKILLS[@]}"; do
    src="$EMBED_BASE/$skill"
    if [ -d "$src" ]; then
        create_link "$skill" "$src" "embed-ai-tool/skills/$skill"
    else
        echo "  ${RED}✗${NC} $skill: 源路径不存在 $src"
    fi
done

# usb-can-debug 为独立技能，不从 embed-ai-tool 链接

# ── 3. 同步 Qt 技能 ───────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/10]${NC} 链接 Qt 技能..."

QT_BASE="$SKILLS_DIR/_sources/qt-agent-skills/skills"
QT_SKILLS=(qt-cpp-review qt-ui-design)

for skill in "${QT_SKILLS[@]}"; do
    src="$QT_BASE/$skill"
    if [ -d "$src" ]; then
        create_link "$skill" "$src" "qt-agent-skills/skills/$skill"
    else
        echo "  ${RED}✗${NC} $skill: 源路径不存在 $src"
    fi
done

# ── 4. 同步 orca 技能 ─────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/10]${NC} 链接 orca 技能..."

ORCA_BASE="$SKILLS_DIR/_sources/orca/skills"
ORCA_SKILLS=(computer-use orca-cli orchestration)

for skill in "${ORCA_SKILLS[@]}"; do
    src="$ORCA_BASE/$skill"
    if [ -d "$src" ]; then
        create_link "$skill" "$src" "orca/skills/$skill"
    else
        echo "  ${RED}✗${NC} $skill: 源路径不存在 $src"
    fi
done

# ── 5. 同步 OfficeCLI 技能 ────────────────────────────────
echo ""
echo -e "${YELLOW}[5/10]${NC} 链接 OfficeCLI 技能..."

OFFICECLI_BASE="$SKILLS_DIR/_sources/OfficeCLI/skills"
OFFICECLI_SKILLS=(officecli-pptx officecli-docx officecli-xlsx officecli-pitch-deck officecli-financial-model officecli-data-dashboard officecli-word-form officecli-academic-paper morph-ppt morph-ppt-3d)

for skill in "${OFFICECLI_SKILLS[@]}"; do
    src="$OFFICECLI_BASE/$skill"
    if [ -d "$src" ]; then
        create_link "$skill" "$src" "OfficeCLI/skills/$skill"
    else
        echo "  ${RED}✗${NC} $skill: 源路径不存在 $src"
    fi
done

# ── 6. 同步 hallmark 技能 ──────────────────────────────────
echo ""
echo -e "${YELLOW}[6/10]${NC} 链接 hallmark 技能..."

HALLMARK_SRC="$SKILLS_DIR/_sources/hallmark/skills/hallmark"
if [ -d "$HALLMARK_SRC" ]; then
    create_link "hallmark" "$HALLMARK_SRC" "hallmark/skills/hallmark"
else
    echo "  ${RED}✗${NC} hallmark: 源路径不存在 $HALLMARK_SRC"
fi

# ── 7. 同步 easyeda-api submodule ─────────────────────────
echo ""
echo -e "${YELLOW}[7/10]${NC} 同步 easyeda-api submodule..."

EASYEDA_SRC="_sources/easyeda-api-skill"
if [ -d "$EASYEDA_SRC" ]; then
    git submodule update --init "$EASYEDA_SRC" 2>/dev/null || true
    create_link "easyeda-api" "$(pwd)/$EASYEDA_SRC" "_sources/easyeda-api-skill"
else
    echo "  ${YELLOW}⚠${NC} $EASYEDA_SRC 不存在，请先: git submodule update --init"
fi

# ── skill-forge ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[8/10]${NC} 链接 skill-forge 技能..."

SKILLFORGE_SRC="$SKILLS_DIR/_sources/skill-forge/skills/skill-forge"
if [ -d "$SKILLFORGE_SRC" ]; then
    create_link "skill-forge" "$SKILLFORGE_SRC" "skill-forge/skills/skill-forge"
else
    echo "  ${RED}✗${NC} skill-forge: 源路径不存在 $SKILLFORGE_SRC"
fi

# ── 9. 校验所有技能 ──────────────────────────────────────
echo ""
echo -e "${YELLOW}[9/10]${NC} 校验技能完整性..."

total=0
missing=0

check_skill() {
    local skill="$1"
    total=$((total + 1))
    if [ -f "$skill/SKILL.md" ] || [ -f "$skill/skill.md" ]; then
        echo "  ${GREEN}✓${NC} $skill"
    else
        echo "  ${RED}✗${NC} $skill (缺少 SKILL.md)"
        missing=$((missing + 1))
    fi
}

for d in */; do
    name="${d%/}"
    case "$name" in
        _*|.) continue ;;
    esac
    check_skill "$name"
done

echo ""
if [ $missing -eq 0 ]; then
    echo -e "  ${GREEN}全部 $total 个技能校验通过${NC}"
else
    echo -e "  ${RED}$missing/$total 个技能缺失${NC}"
fi

# ── 10. 生成 _tree.md ────────────────────────────────────
echo ""
echo -e "${YELLOW}[10/10]${NC} 生成 _tree.md..."

cat > _tree.md << 'TREEHEADER'
# 🌳 Skills Tree

> 自动生成于: TIMESTAMP
> 仓库: https://github.com/ez-xu/agent-skills

## 📊 概览

TREEHEADER

total_skills=$(ls -d */ 2>/dev/null | grep -v '^_' | wc -l)

echo "| 分类 | 技能数 |" >> _tree.md
echo "|------|--------|" >> _tree.md
echo "| 🔌 嵌入式 | 24 |" >> _tree.md
echo "| 📐 EDA / PCB | 13 |" >> _tree.md
echo "| 📋 办公文档 | 10 |" >> _tree.md
echo "| 🔧 研发协作 | 7 |" >> _tree.md
echo "| 🛠️ 基础设施 | 5 |" >> _tree.md
echo "| **合计** | **$total_skills** |" >> _tree.md
echo "" >> _tree.md

cat >> _tree.md << 'TREEBODY'

---

## 🔌 嵌入式

| 子类 | 技能 |
|------|------|
| 构建 | build-cmake, build-iar, build-idf, build-keil, build-makefile, build-platformio |
| 烧录 | flash-idf, flash-jlink, flash-keil, flash-openocd, flash-platformio |
| 调试 | debug-gdb-openocd, debug-jlink, debug-platformio |
| 通信 | can-debug, modbus-debug, rtos-debug |
| 监控 | serial-monitor, serial-shell, logic-analyzer, visa-debug |
| 分析 | static-analysis, memory-analysis |
| 编排 | workflow |

## 📐 EDA / PCB

| 子类 | 技能 | 来源 |
|------|------|------|
| 设计 | kicad, easyeda-api | kicad-happy / easyeda |
| 物料 | bom, datasheets | kicad-happy |
| 采购 | digikey, mouser, element14, lcsc | kicad-happy |
| 制造 | jlcpcb, pcbway | kicad-happy |
| 仿真 | spice, emc | kicad-happy |

## 📋 办公文档

| 子类 | 技能 |
|------|------|
| 演示 | officecli-pptx, officecli-pitch-deck, morph-ppt, morph-ppt-3d |
| 文档 | officecli-docx, officecli-word-form, officecli-academic-paper |
| 表格 | officecli-xlsx, officecli-financial-model, officecli-data-dashboard |

## 🔧 研发协作

| 子类 | 技能 |
|------|------|
| Git | git-commit-assistant, gitlab-download, gitlab-upload |
| 审查 | project-diff, qt-cpp-review |
| 设计 | qt-ui-design, hallmark |

## 🛠️ 基础设施

| 技能 | 用途 |
|------|------|
| skill-forge | 技能创建/改进/扫描 |
| shared | 共享工具库 |
| computer-use | 桌面应用自动化 |
| orca-cli | Orca 工作区管理 |
| orchestration | 多智能体编排 |

---

## 🔗 外部来源

| 来源 | 仓库 | 技能数 |
|------|------|--------|
| kicad-happy | [aklofas/kicad-happy](https://github.com/aklofas/kicad-happy) | 11 |
| easyeda-api | [easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill) | 1 |

---

## 🚀 快速操作

```bash
# 同步所有技能 (clone 后首次运行)
bash _sync.sh

# 更新 kicad-happy 技能
cd C:/Users/15854/kicad-happy && git pull && cd - && bash _sync.sh

# 更新 easyeda-api 技能
cd _sources/easyeda-api-skill && git pull && cd -

# 添加新技能
# 1. 在顶层创建技能目录
# 2. 更新 _tree.yaml 中的分类
# 3. bash _sync.sh && git add -A && git commit -m "add: <skill-name>"
```
TREEBODY

current_time=$(date "+%Y-%m-%d %H:%M")
sed -i "s/TIMESTAMP/$current_time/" _tree.md 2>/dev/null || true

echo -e "  ${GREEN}✓${NC} _tree.md 已生成"
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      同步完成! ✅                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
