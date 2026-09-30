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

title 第二步：切片并重建索引

echo ============================================================
echo  什么时候需要跑这个脚本？
echo    - 往 data\raw 里新增或删除了文档
echo    - 修改了 configs\config.yaml 里的切片参数
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
