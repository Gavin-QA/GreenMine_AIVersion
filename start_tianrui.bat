@echo off
chcp 65001 >nul
:: ==============================================================================
:: 四川天瑞大屏客户端手工测试启动脚本 (开启 CDP 9223 调试端口以接入性能大盘)
:: ==============================================================================

cd /d D:\LargeScreen\tianrui\se-launcher-tianrui

echo [Launching] Starting Tianrui client with remote debugging port 9223...
start "" "se-launcher-tianrui.exe" --remote-debugging-port=9223

echo [Ready] 客户端已成功拉起！请打开平台监控大盘查看实时心电图: http://127.0.0.1:8000
