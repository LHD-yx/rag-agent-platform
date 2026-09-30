# -*- coding: utf-8 -*-
"""重新生成 5 个 .bat 启动脚本（GBK 编码 + CRLF 换行）。

为什么需要这个脚本：
    Windows 的 cmd.exe 是按系统默认编码（中文系统为 GBK）读取 .bat 文件的。
    如果 .bat 被保存成 UTF-8，中文注释会被解析成乱码命令，
    轻则报错、重则连最后的 pause 都被破坏 —— 表现就是"双击后窗口一闪而过"。

    所以本脚本统一用 GBK + CRLF 写回，保证双击就能正常显示与执行。

改了目录结构怎么办：
    项目代码现在放在「01-项目代码」文件夹里，下面 5 个脚本都用
        set "BASE=%~dp0"
        set "APP=%BASE%01-项目代码\rag-agent-platform"
    来定位项目。以后如果你给文件夹改名，只需要改这两行，然后重新运行本脚本。

用法：python 修复bat编码.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 统一的"找项目目录 + 找不到就友好报错"的头部片段
HEAD_BACKEND = """@echo off
chcp 936 >nul
set "BASE=%~dp0"
set "APP=%BASE%01-项目代码\\rag-agent-platform"
if not exist "%APP%\\main.py" (
  echo [错误] 找不到后端项目目录：
  echo        %APP%
  echo        请确认「01-项目代码」文件夹存在，且没有被改名或移动。
  pause
  exit /b 1
)
cd /d "%APP%"
"""

HEAD_DESKTOP = """@echo off
chcp 936 >nul
set "BASE=%~dp0"
set "APP=%BASE%01-项目代码\\rag-desktop"
if not exist "%APP%\\package.json" (
  echo [错误] 找不到桌面端目录：
  echo        %APP%
  echo        请确认「01-项目代码」文件夹存在，且没有被改名或移动。
  pause
  exit /b 1
)
cd /d "%APP%"
"""

SCRIPTS: dict[str, str] = {}

SCRIPTS["1-环境自检.bat"] = HEAD_BACKEND + """
title 第一步：环境自检

echo ============================================================
echo  环境自检：检查 Python、依赖、API Key、文档、索引是否就绪
echo  （出现 [X] 不要慌，那一行下面就是解决办法）
echo ============================================================
echo.

python main.py doctor

echo.
echo ------------------------------------------------------------
echo 自检结束。按任意键关闭本窗口。
pause >nul
"""

SCRIPTS["2-重建索引.bat"] = HEAD_BACKEND + """
title 第二步：切片并重建索引

echo ============================================================
echo  什么时候需要跑这个脚本？
echo    - 往 data\\raw 里新增或删除了文档
echo    - 修改了 configs\\config.yaml 里的切片参数
echo  说明：本步骤会调用 embedding 接口，需要联网，通常 1 到 3 分钟
echo        （纯解析切片只要几秒，慢的是第二步的向量化）
echo ============================================================
echo.

echo [1/2] 正在解析文档并切片 ...
python main.py chunk
echo.

echo [2/2] 正在向量化并建立索引 ...
python main.py index

echo.
echo ------------------------------------------------------------
echo 完成。按任意键关闭本窗口。
pause >nul
"""

SCRIPTS["3-启动后端服务.bat"] = HEAD_BACKEND + """
title RAG 后端服务（使用期间不要关闭本窗口）

echo ============================================================
echo  RAG 后端服务启动中 ...
echo.
echo   接口地址：http://127.0.0.1:8000
echo   接口文档：http://127.0.0.1:8000/docs  （浏览器里可直接调试）
echo.
echo  注意：这个窗口要一直开着，关闭窗口就等于停止服务。
echo        想停止服务，按 Ctrl + C 或直接关闭窗口。
echo ============================================================
echo.

python main.py serve

echo.
echo 服务已停止。按任意键关闭。
pause >nul
"""

SCRIPTS["4-启动桌面应用.bat"] = HEAD_DESKTOP + """
title RAG 桌面应用

echo ============================================================
echo  RAG 桌面应用
echo.
echo  前置条件：请先运行「3-启动后端服务.bat」并保持其窗口打开，
echo            否则窗口右上角会显示「后端未连接」。
echo ============================================================
echo.

if not exist "node_modules" (
  echo 检测到首次运行，正在安装依赖（约 1 到 3 分钟，请耐心等待）...
  call npm install
  echo.
)

echo 正在启动应用窗口 ...
call npm run dev

echo.
echo 应用已关闭。按任意键关闭本窗口。
pause >nul
"""

SCRIPTS["5-生成演示截图.bat"] = HEAD_DESKTOP + """
title 生成演示截图

set "SHOT=%BASE%演示截图-桌面问答.png"

echo ============================================================
echo  自动演示并截图
echo  前置条件：请先运行「3-启动后端服务.bat」并保持其窗口打开。
echo.
echo  流程：启动应用 -^> 自动提问 -^> 等待回答生成 -^> 截图 -^> 自动退出
echo  截图保存位置：%SHOT%
echo ============================================================
echo.

set "QUESTION="
set /p QUESTION=请输入要演示的问题（直接回车使用默认问题）：
if "%QUESTION%"=="" set "QUESTION=电视无法开机怎么办"

echo.
echo 正在构建前端（首次约 5 秒）...
call npm run build >nul 2>nul

echo 正在启动应用并自动提问，约 25 秒后自动截图 ...
call "node_modules\\.bin\\electron.cmd" . "--demo-question=%QUESTION%" "--demo-screenshot=%SHOT%"

echo.
echo 截图已保存到：%SHOT%
echo ------------------------------------------------------------
echo 完成。按任意键关闭本窗口。
pause >nul
"""


def main() -> None:
    for name, content in SCRIPTS.items():
        path = ROOT / name
        # 关键：GBK 编码（中文系统 cmd 默认）+ CRLF 换行（Windows 批处理要求）
        path.write_bytes(content.replace("\n", "\r\n").encode("gbk"))
        print(f"已写入 {name}（GBK + CRLF，{path.stat().st_size} 字节）")
    print("\n完成。现在双击任意 .bat 都应正常显示中文并停在「按任意键关闭」。")


if __name__ == "__main__":
    main()
