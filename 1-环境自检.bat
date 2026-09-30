@echo off
chcp 936 >nul
set "BASE=%~dp0"
set "APP=%BASE%01-项目代码\rag-agent-platform"
if not exist "%APP%\main.py" (
  echo [错误] 找不到后端项目目录：
  echo        %APP%
  echo        请确认「01-项目代码」文件夹存在，且没有被改名或移动。
  pause
  exit /b 1
)
cd /d "%APP%"

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
