#!/usr/bin/env python3
"""
工程目录扫描脚本 - 分析目录结构，输出 JSON 供技能使用。
用法: python scan_project.py <目录路径>
"""

import sys
import os
import json
from collections import Counter
from pathlib import Path

# 源码文件扩展名
SOURCE_EXTS = {
    '.c', '.h', '.cpp', '.hpp', '.cxx', '.hxx', '.cc', '.hh',
    '.py', '.pyx', '.pxd',
    '.js', '.jsx', '.ts', '.tsx', '.mjs',
    '.rs',
    '.go',
    '.java', '.kt', '.kts',
    '.cs', '.vb',
    '.swift', '.m', '.mm',
    '.rb',
    '.php',
    '.lua',
    '.s', '.S', '.asm',
    '.v', '.vh', '.sv', '.svh',
}

# 构建产物扩展名
BUILD_EXTS = {
    '.o', '.obj', '.a', '.so', '.dll', '.lib', '.dylib',
    '.elf', '.bin', '.hex', '.s19', '.srec', '.map',
    '.exe', '.out',
    '.pyc', '.pyo', '.class',
    '.d', '.dep',
}

# 已知的构建/IDE目录名（不区分大小写）
BUILD_DIRS = {
    'debug', 'release', 'output', 'build', 'dist', 'out',
    'target', 'bin', 'obj', 'libs', 'lib', 'node_modules',
    '__pycache__', '.pio', 'cmake-build-debug', 'cmake-build-release',
    'brun',
}

# 已知的IDE/工具目录
IDE_DIRS = {
    '.git', '.svn', '.hg',
    '.vscode', '.settings', '.idea', '.eclipse',
    '.vs', '.github', '.gitlab',
}

# 已知的IDE配置文件
IDE_FILES = {
    '.cproject', '.project', '.classpath', '.gitignore',
    '.gitattributes', '.gitmodules', '.editorconfig',
    '.clang-format', '.clang-tidy',
}

def scan_directory(root_path):
    """扫描目录并返回结构信息"""
    root = Path(root_path)
    if not root.exists():
        return {"error": f"路径不存在: {root_path}"}
    if not root.is_dir():
        return {"error": f"不是目录: {root_path}"}

    top_items = []
    all_extensions = Counter()
    total_files = 0
    total_dirs = 0

    try:
        for item in sorted(root.iterdir()):
            if item.is_dir():
                total_dirs += 1
                sub_files = []
                sub_all_exts = Counter()
                sub_total = 0
                try:
                    for f in item.rglob('*'):
                        if f.is_file():
                            sub_total += 1
                            ext = f.suffix.lower()
                            sub_all_exts[ext] += 1
                            all_extensions[ext] += 1
                            total_files += 1
                except PermissionError:
                    pass

                # 判定目录类型
                dir_type = classify_directory(item.name, sub_all_exts, sub_total)
                top_items.append({
                    "name": item.name,
                    "type": "directory",
                    "classification": dir_type,
                    "file_count": sub_total,
                    "top_extensions": sub_all_exts.most_common(5),
                })
            else:
                total_files += 1
                ext = item.suffix.lower()
                all_extensions[ext] += 1
                top_items.append({
                    "name": item.name,
                    "type": "file",
                    "extension": ext,
                })

    except PermissionError as e:
        return {"error": f"权限不足: {e}"}

    # 汇总
    source_dirs = [i for i in top_items if i.get("classification") == "source"]
    build_dirs = [i for i in top_items if i.get("classification") == "build_or_ide"]
    uncertain_dirs = [i for i in top_items if i.get("classification") == "uncertain"]

    return {
        "path": str(root.absolute()),
        "total_files": total_files,
        "total_dirs": total_dirs,
        "all_extensions": dict(all_extensions.most_common(20)),
        "source_dirs": source_dirs,
        "build_or_ide_dirs": build_dirs,
        "uncertain_dirs": uncertain_dirs,
        "top_items": top_items,
    }


def classify_directory(dirname, extensions, file_count):
    """判断目录类型"""
    name_lower = dirname.lower()

    if name_lower in BUILD_DIRS:
        return "build_or_ide"
    if name_lower in IDE_DIRS:
        return "build_or_ide"

    if file_count == 0:
        return "build_or_ide"  # 空目录标记为排除

    # 统计源码文件比例
    source_count = sum(c for ext, c in extensions.items() if ext in SOURCE_EXTS)
    build_count = sum(c for ext, c in extensions.items() if ext in BUILD_EXTS)

    if source_count > 0 and build_count == 0 and source_count / file_count > 0.5:
        return "source"
    if build_count > 0 and source_count == 0:
        return "build_or_ide"

    # 包含常见源码目录名
    source_names = {'src', 'source', 'app', 'include', 'inc', 'components',
                    'modules', 'drivers', 'core', 'lib', 'user', 'ra',
                    'ra_cfg', 'ra_gen', 'script', 'test', 'tests',
                    'common', 'hal', 'bsp', 'middleware', 'os', 'rtos'}
    if name_lower in source_names:
        if source_count > 0 or file_count > 0:
            return "source"
        return "uncertain"

    return "uncertain"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "用法: python scan_project.py <目录路径>"}, ensure_ascii=False))
        sys.exit(1)

    result = scan_directory(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
