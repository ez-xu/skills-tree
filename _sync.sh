#!/bin/bash
# Skills Tree 同步脚本
# 用法: bash _sync.sh

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

# ── 1. 同步 kicad-happy 技能 ──────────────────────────────
echo -e "${YELLOW}[1/4]${NC} 链接 kicad-happy 技能..."

KICAD_HAPPY="C:/Users/15854/kicad-happy/skills"
KICAD_SKILLS=(bom datasheets digikey element14 emc jlcpcb kicad lcsc mouser pcbway spice)

for skill in "${KICAD_SKILLS[@]}"; do
    src="$KICAD_HAPPY/$skill"
    if [ -d "$src" ]; then
        # 如果目标已存在但不是 symlink，先移除
        if [ -e "$skill" ] && [ ! -L "$skill" ]; then
            echo "  ${YELLOW}⚠${NC} 移除实体副本: $skill/"
            rm -rf "$skill"
        fi
        # 创建 symlink
        if [ ! -e "$skill" ]; then
            ln -s "$src" "$skill" 2>/dev/null || cmd.exe /c "mklink /D \"$(cygpath -w "$skill")\" \"$(cygpath -w "$src")\"" >/dev/null 2>&1
            echo "  ${GREEN}✓${NC} $skill -> kicad-happy/skills/$skill"
        elif [ -L "$skill" ]; then
            echo "  ${GREEN}✓${NC} $skill (已链接)"
        fi
    else
        echo "  ${RED}✗${NC} $skill: 源路径不存在 $src"
    fi
done

# ── 2. 同步 easyeda-api submodule ─────────────────────────
echo ""
echo -e "${YELLOW}[2/4]${NC} 同步 easyeda-api submodule..."

if [ -d "_sources/easyeda-api-skill" ]; then
    git submodule update --init _sources/easyeda-api-skill 2>/dev/null || true
    # 创建 symlink
    if [ ! -e "easyeda-api" ] && [ -d "_sources/easyeda-api-skill" ]; then
        ln -s "_sources/easyeda-api-skill" "easyeda-api" 2>/dev/null || cmd.exe /c "mklink /D \"$(cygpath -w "easyeda-api")\" \"$(cygpath -w "_sources/easyeda-api-skill")\"" >/dev/null 2>&1
        echo "  ${GREEN}✓${NC} easyeda-api -> _sources/easyeda-api-skill"
    elif [ -L "easyeda-api" ]; then
        echo "  ${GREEN}✓${NC} easyeda-api (已链接)"
    fi
else
    echo "  ${YELLOW}⚠${NC} _sources/easyeda-api-skill 不存在，跳过"
fi

# ── 3. 校验所有技能 ──────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/4]${NC} 校验技能完整性..."

total=0
missing=0

check_skill() {
    local skill="$1"
    total=$((total + 1))
    if [ -f "$skill/SKILL.md" ] || [ -f "$skill/skill.md" ] || [ -f "$skill/SKILL.md" ]; then
        echo "  ${GREEN}✓${NC} $skill"
    else
        echo "  ${RED}✗${NC} $skill (缺少 SKILL.md)"
        missing=$((missing + 1))
    fi
}

for d in */; do
    name="${d%/}"
    # 跳过隐藏目录和内部目录
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

# ── 4. 生成 _tree.md ─────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/4]${NC} 生成 _tree.md..."

cat > _tree.md << 'TREEHEADER'
# 🌳 Skills Tree

> 自动生成于: TIMESTAMP
> 仓库: https://github.com/ez-xu/agent-skills

## 📊 概览

TREEHEADER

# 统计信息
total_skills=$(ls -d */ | grep -v '^_' | wc -l)
echo "| 分类 | 技能数 |" >> _tree.md
echo "|------|--------|" >> _tree.md

embedded_count=0
eda_count=0
office_count=0
devops_count=0
infra_count=0

# 简单统计 (硬编码分类计数)
embedded_count=24
eda_count=13
office_count=10
devops_count=7
infra_count=5

echo "| 🔌 嵌入式 | $embedded_count |" >> _tree.md
echo "| 📐 EDA / PCB | $eda_count |" >> _tree.md
echo "| 📋 办公文档 | $office_count |" >> _tree.md
echo "| 🔧 研发协作 | $devops_count |" >> _tree.md
echo "| 🛠️ 基础设施 | $infra_count |" >> _tree.md
echo "| **合计** | **$total_skills** |" >> _tree.md
echo "" >> _tree.md

# 生成分类详情
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
# 同步所有技能
bash _sync.sh

# 更新 kicad-happy
cd C:/Users/15854/kicad-happy && git pull && cd - && bash _sync.sh

# 更新 easyeda-api
cd _sources/easyeda-api-skill && git pull && cd -

# 添加新技能
# 1. 放入对应 _collections/<分类>/ 目录
# 2. 更新 _tree.yaml
# 3. bash _sync.sh && git add -A && git commit -m "add: <skill-name>"
```
TREEBODY

# 替换时间戳
current_time=$(date "+%Y-%m-%d %H:%M")
sed -i "s/TIMESTAMP/$current_time/" _tree.md

echo -e "  ${GREEN}✓${NC} _tree.md 已生成"
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      同步完成! ✅                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
