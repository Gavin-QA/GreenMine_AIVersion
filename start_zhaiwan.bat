@echo off
chcp 65001 >nul
title 寨湾客户端环境切换与启动工具

echo ==========================================
echo        请选择要启动的测试环境
echo ==========================================
echo   [1] 生产环境 (外网/主环境)
echo   [2] 测试环境 (内网/测试环境)
echo ==========================================
set /p choice=请输入编号 (1 或 2): 

if "%choice%"=="1" (
    set "TARGET_URL=http://221.234.48.197:8808"
    echo.
    echo [Check] Switching to Production Environment...
) else if "%choice%"=="2" (
    set "TARGET_URL=http://121.43.58.203:8783"
    echo.
    echo [Check] Switching to Test Environment...
) else (
    echo.
    echo [Error] Invalid input, exiting.
    goto end
)

:: 检查当前 config.json 中的环境是否一致（已移除所有管道符，杜绝转义冲突）
for /f "usebackq" %%i in (`powershell -Command "$path = 'C:\Users\grm\AppData\Roaming\se-launcher-zhaiwan\config.json'; if (Test-Path $path) { $c = ConvertFrom-Json -InputObject (Get-Content $path -Raw); if ($c.nplusoneUrl -eq '%TARGET_URL%') { 'MATCH' } else { 'DIFFERENT' } } else { 'NOT_FOUND' }"`) do set "CONFIG_STATUS=%%i"

echo Config Status: %CONFIG_STATUS%

if "%CONFIG_STATUS%"=="MATCH" (
    echo [Skip] Already on the target environment, skipping reconfiguration.
    
    :: 检查客户端进程是否在运行
    tasklist | findstr /i "se-launcher-zhaiwan.exe" >nul
    if errorlevel 1 (
        echo [Launching] Client not running, starting now...
        cd /d D:\LargeScreen\zhaiwan2\project\se-launcher-zhaiwan
        start "" "se-launcher-zhaiwan.exe" --remote-debugging-port=9223
    ) else (
        echo [Notice] Client is already running and environment matches!
    )
    goto end
)

:: 不一致时的处理：清理进程并更新配置
echo [Updating] Environment mismatch, updating configuration...
echo [Cleaning] Closing existing client and rendering processes...
taskkill /f /im se-launcher-zhaiwan.exe >nul 2>&1
timeout /t 1 >nul

:: PowerShell 安全写入无 BOM JSON（使用 -InputObject 和 $null 彻底避开管道符）
powershell -Command "$path = 'C:\Users\grm\AppData\Roaming\se-launcher-zhaiwan\config.json'; $dir = Split-Path $path; if (!(Test-Path $dir)) { $null = New-Item -ItemType Directory -Path $dir }; if (Test-Path $path) { $content = Get-Content -Path $path -Raw; if ($content.Trim() -ne '') { $json = ConvertFrom-Json -InputObject $content } else { $json = [PSCustomObject]@{} } } else { $json = [PSCustomObject]@{} }; $json.nplusoneUrl = '%TARGET_URL%'; $jsonString = ConvertTo-Json -InputObject $json -Depth 10; [System.IO.File]::WriteAllText($path, $jsonString, (New-Object System.Text.UTF8Encoding $false))"

echo [Success] Configuration updated!
echo.

:: 启动客户端
cd /d D:\LargeScreen\zhaiwan2\project\se-launcher-zhaiwan

echo [Launching] Starting client...
start "" "se-launcher-zhaiwan.exe" --remote-debugging-port=9223

:end
timeout /t 3 >nul