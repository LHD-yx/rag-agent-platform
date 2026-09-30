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
