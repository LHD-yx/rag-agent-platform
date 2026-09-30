@echo off
chcp 936 >nul
set "BASE=%~dp0"
set "APP=%BASE%01-项目代码\rag-desktop"
if not exist "%APP%\package.json" (
  echo [错误] 找不到桌面端目录：
  echo        %APP%
  echo        请确认「01-项目代码」文件夹存在，且没有被改名或移动。
  pause
  exit /b 1
)
cd /d "%APP%"

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
call "node_modules\.bin\electron.cmd" . "--demo-question=%QUESTION%" "--demo-screenshot=%SHOT%"

echo.
echo 截图已保存到：%SHOT%
echo ------------------------------------------------------------
echo 完成。按任意键关闭本窗口。
pause >nul
