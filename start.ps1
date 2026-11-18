<#
  一键启动：Neo4j + API

  用法：
    .\start.ps1              # 缺什么起什么（已在运行的会跳过）
    .\start.ps1 -Restart     # 先停掉再起
    .\start.ps1 -Public      # 监听 0.0.0.0，同一局域网的其他设备也能访问

  说明：
    - Neo4j 用 console 模式（Windows 下 start 需要先把服务注册到系统）；
    - 两个进程各自开一个最小化窗口，关掉窗口即停止；
    - 脚本只负责拉起和探测端口，不做进程托管。
#>
param([switch]$Restart, [switch]$Public)

$ErrorActionPreference = "Continue"

$BindHost = if ($Public) { "0.0.0.0" } else { "127.0.0.1" }

$Python     = "D:\Anaconda3\envs\pytorch\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$Neo4jHome  = "D:\neo4j\neo4j-community-5.26.12-windows\neo4j-community-5.26.12"
$ProjectDir = $PSScriptRoot

function Test-Port([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch { return $false }
}

function Wait-Port([int]$Port, [int]$TimeoutSec, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 800
    }
    Write-Host "  [超时] $Label 未在 ${TimeoutSec}s 内就绪" -ForegroundColor Red
    return $false
}

function Stop-ByPort([int]$Port, [string]$Name) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pid_ = ($conn | Select-Object -First 1).OwningProcess
        try {
            Stop-Process -Id $pid_ -Force -ErrorAction Stop
            Write-Host "  已停止 $Name（PID $pid_）" -ForegroundColor Yellow
            Start-Sleep -Seconds 2
        } catch {
            Write-Host "  停止 $Name 失败：$($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "=== 中医药问答系统 启动检查 ===" -ForegroundColor Cyan
Write-Host ""

if ($Restart) {
    Write-Host "[0/2] 停止已有进程"
    Stop-ByPort 8000 "API"
    Stop-ByPort 7687 "Neo4j"
    Write-Host ""
}

# ---------------- Vue 前端 ----------------
# 旧版 web/ 已移除，前端只有 Vue3 构建产物。dist 缺失时自动构建，
# 保证 start.bat 在全新环境（git clone 后）仍然一键可用。
$FrontendDir = Join-Path $ProjectDir "frontend"
$FrontendDist = Join-Path $FrontendDir "dist\index.html"
if (-not (Test-Path $FrontendDist)) {
    Write-Host "[前端] 未找到构建产物，正在构建 Vue3 前端…"
    Push-Location $FrontendDir
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Host "  安装依赖（首次约需 1-2 分钟）"
            npm.cmd install
        }
        npm.cmd run build
    } finally {
        Pop-Location
    }
    if (-not (Test-Path $FrontendDist)) {
        Write-Host "  构建失败，请检查 Node.js / npm 是否可用" -ForegroundColor Red
        exit 1
    }
    Write-Host "  就绪" -ForegroundColor Green
} else {
    Write-Host "[前端] 使用已有构建产物" -ForegroundColor DarkGray
}

# ---------------- Neo4j ----------------
Write-Host "[1/2] Neo4j  (bolt 7687 / http 7474)"
if (Test-Port 7474) {
    Write-Host "  已在运行，跳过" -ForegroundColor DarkGray
} else {
    if (-not (Test-Path "$Neo4jHome\bin\neo4j.bat")) {
        Write-Host "  找不到 Neo4j：$Neo4jHome" -ForegroundColor Red
        Write-Host "  请修改脚本里的 `$Neo4jHome 或设置 NEO4J_URI 指向已有实例" -ForegroundColor Red
    } else {
        Write-Host "  启动中…（首次启动约需 15 秒）"
        Start-Process -FilePath "$Neo4jHome\bin\neo4j.bat" `
            -ArgumentList "console" -WorkingDirectory $Neo4jHome -WindowStyle Minimized
        if (-not (Wait-Port 7474 90 "Neo4j")) { exit 1 }
        Write-Host "  就绪" -ForegroundColor Green
    }
}

# ---------------- API ----------------
Write-Host ""
Write-Host "[2/2] API    (http 8000)"
if (Test-Port 8000) {
    Write-Host "  已在运行，跳过" -ForegroundColor DarkGray
} else {
    Write-Host "  启动中…（要加载文本/图像索引与模型，约 20 秒）"
    Start-Process -FilePath $Python `
        -ArgumentList "-m", "uvicorn", "tcmqa.main:app", "--host", $BindHost, "--port", "8000" `
        -WorkingDirectory $ProjectDir -WindowStyle Minimized
    if (-not (Wait-Port 8000 120 "API")) { exit 1 }
    Write-Host "  就绪" -ForegroundColor Green
}

# ---------------- 汇总 ----------------
Write-Host ""
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 20
    Write-Host "健康检查: $($health.status)" -ForegroundColor Green
    Write-Host "  Neo4j      : $($health.checks.neo4j.ok)"
    Write-Host "  LLM        : $($health.checks.llm.model)"
    Write-Host "  文本索引   : $($health.checks.index.documents) 篇"
    try {
        $vision = Invoke-RestMethod "http://127.0.0.1:8000/api/vision/stats" -TimeoutSec 20
        Write-Host "  图像索引   : $($vision.images) 张 / $($vision.herbs) 味"
    } catch {
        Write-Host "  图像索引   : 未构建（scripts/build_vision_index.py）" -ForegroundColor Yellow
    }
} catch {
    Write-Host "健康检查失败，可能还在初始化，请稍等几秒再刷新" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  网页      http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  接口文档  http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "  Neo4j     http://localhost:7474" -ForegroundColor Cyan

if ($Public) {
    # 局域网地址：手机 / 别人的电脑在同一 WiFi 下可以直接打开
    $lanIp = $null
    try {
        $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
            Select-Object -First 1).IPAddress
    } catch { }
    if (-not $lanIp) {
        $lanIp = (ipconfig | Select-String "IPv4" | Select-Object -First 1) -replace ".*: ", ""
        $lanIp = $lanIp.Trim()
    }
    Write-Host ""
    Write-Host "  已监听 0.0.0.0，局域网地址：" -ForegroundColor Yellow
    Write-Host "  http://${lanIp}:8000" -ForegroundColor Cyan
    Write-Host "  首次使用若连不上，多半是防火墙拦了（管理员 PowerShell 执行一次）：" -ForegroundColor DarkGray
    Write-Host "  netsh advfirewall firewall add rule name=`"TCMQA 8000`" dir=in action=allow protocol=TCP localport=8000" -ForegroundColor DarkGray
    Write-Host "  注意：这一层没有鉴权，只适合在可信网络里演示，别把 8000 端口映射到公网。" -ForegroundColor Yellow
}

Write-Host ""Write-Host ""
Write-Host "  整体自检  python scripts/smoke_all.py" -ForegroundColor DarkGray
Write-Host ""
