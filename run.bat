@echo off
set PORT=8000
set URL=http://127.0.0.1:%PORT%/

echo 🚀 正在启动 Deep Research Agent (Windows 版)...

:: 1. 检查环境变量文件
if not exist .env (
    echo ⚠️ 未发现 .env 文件，正在从 .env.example 复制...
    copy .env.example .env
    echo 请记得在 .env 中填写你的 API Key！
)

:: 2. 检查并创建虚拟环境
if not exist .venv (
    echo 📦 正在创建虚拟环境...
    python -m venv .venv
)

:: 3. 激活虚拟环境并安装依赖
echo 🛠️ 正在检查并安装依赖...
call .venv\Scripts\activate
pip install -r requirements.txt

:: 4. 自动打开浏览器
echo 🌐 准备打开前端页面: %URL%
start %URL%

:: 5. 启动服务
echo 🔥 服务正在启动...
uvicorn app.main:app --port %PORT% --reload

pause