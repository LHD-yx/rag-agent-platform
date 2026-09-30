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
