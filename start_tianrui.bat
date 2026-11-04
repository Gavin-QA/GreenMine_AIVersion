@echo off
chcp 65001 >nul
REM Clear ELECTRON_RUN_AS_NODE to prevent Electron from running as Node CLI
set "ELECTRON_RUN_AS_NODE="

cd /d D:\LargeScreen\tianrui\se-launcher-tianrui

echo [Launching] Starting Tianrui client with remote debugging port 9223...
start "" "se-launcher-tianrui.exe" --remote-debugging-port=9223

echo [Ready] 客户端已成功拉起！CDP 调试端口: 9223
