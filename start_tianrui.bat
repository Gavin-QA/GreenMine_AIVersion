@echo off
chcp 65001 >nul
REM 清除 ELECTRON_RUN_AS_NODE，防止 Electron 作为 Node CLI 运行
set "ELECTRON_RUN_AS_NODE="

cd /d D:\LargeScreen\tianrui\se-launcher-tianrui

echo [Launching] 正在启动 Tianrui 客户端，开启远程调试端口 9223...
start "" "se-launcher-tianrui.exe" --remote-debugging-port=9223

echo [Ready] 客户端已成功启动，CDP 调试端口: 9223
pause