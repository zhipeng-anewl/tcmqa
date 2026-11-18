<#
  给一个「别人现在就能点开」的公网链接（临时，不需要服务器、不需要域名、不需要备案）。

  原理：Cloudflare Quick Tunnel 在本机起一个出站连接，把 http://127.0.0.1:8000
  映射成一个 https://xxx.trycloudflare.com 的地址。不占用公网 IP，也不用到路由器上做端口映射。

  用法（项目根目录，管理员非必需）：
    powershell -ExecutionPolicy Bypass -File .\scripts\share.ps1

  注意：
    - 链接随进程消失而失效，重启会换一个新地址；
    - 这是把你的本机服务暴露到公网，演示完记得 Ctrl+C 关掉；
    - 面试演示建议提前 10 分钟跑一遍，确认能打开再发链接。
#>
param(
    [int]$Port = 8000,
    [switch]$NoTunnel
)

$ErrorActionPreference = "Continue"

$Root    = Split-Path $PSScriptRoot -Parent
$Tools   = Join-Path $Root ".tools"
$Exe     = Join-Path $Tools "cloudflared.exe"
$LogFile = Join-Path $Tools "cloudflared.log"
$ErrFile = Join-Path $Tools "cloudflared.err"

function Test-Port([int]$P) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $P)
        $c.Close()
        return $true
    } catch { return $false }
}

function Wait-Port([int]$P, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $P) { return $true }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Get-LanIp {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
            Select-Object -First 1).IPAddress
        if ($ip) { return $ip }
    } catch { }
    $line = ipconfig | Select-String "IPv4" | Select-Object -First 1
    if ($line) { return ($line -replace ".*: ", "").Trim() }
    return "本机IP"
}

Write-Host ""
Write-Host "=== 生成公网临时链接 ===" -ForegroundColor Cyan
Write-Host ""

# ---------------- 1) 确保 API 在跑 ----------------
if (Test-Port $Port) {
    Write-Host "[1/3] API 已在 $Port 端口运行" -ForegroundColor Green
} else {
    Write-Host "[1/3] API 未运行，正在启动（约 20 秒）…"
    $py = "D:\Anaconda3\envs\pytorch\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    Start-Process -FilePath $py `
        -ArgumentList "-m", "uvicorn", "tcmqa.main:app", "--host", "127.0.0.1", "--port", "$Port" `
        -WorkingDirectory $Root -WindowStyle Minimized
    if (-not (Wait-Port $Port 180)) {
        Write-Host "  API 没起来，先跑 start.bat 看看报什么错" -ForegroundColor Red
        exit 1
    }
    Write-Host "  API 就绪" -ForegroundColor Green
}

try {
    $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 30
    Write-Host "      健康检查：$($health.status)（Neo4j $($health.checks.neo4j.ok) / 索引 $($health.checks.index.documents) 篇）"
} catch {
    Write-Host "      健康检查失败，先确认本地能打开 http://127.0.0.1:$Port" -ForegroundColor Yellow
}

# ---------------- 2) 准备 cloudflared ----------------
if (-not (Test-Path $Exe)) {
    Write-Host "[2/3] 下载 cloudflared（约 20MB，只需一次）…"
    New-Item -ItemType Directory -Force -Path $Tools | Out-Null
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    try {
        Invoke-WebRequest -Uri $url -OutFile $Exe -TimeoutSec 300
        Write-Host "      下载完成" -ForegroundColor Green
    } catch {
        Write-Host "      下载失败：$($_.Exception.Message)" -ForegroundColor Red
        Write-Host "      可以手动下载后放到：$Exe" -ForegroundColor Yellow
        Write-Host "      地址：$url" -ForegroundColor DarkGray
        Write-Host "      或者改用 ngrok：ngrok http $Port" -ForegroundColor DarkGray
        exit 1
    }
} else {
    Write-Host "[2/3] cloudflared 已就绪"
}

if ($NoTunnel) {
    Write-Host ""
    Write-Host "已跳过隧道（-NoTunnel），局域网地址：http://$(Get-LanIp):$Port" -ForegroundColor Cyan
    exit 0
}

# ---------------- 3) 起隧道并解析地址 ----------------
Write-Host "[3/3] 建立隧道…"
Remove-Item $LogFile, $ErrFile -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath $Exe `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" `
    -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile `
    -WindowStyle Hidden -PassThru

$publicUrl = $null
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $text = ""
    foreach ($f in @($LogFile, $ErrFile)) {
        if (Test-Path $f) { $text += (Get-Content $f -Raw -ErrorAction SilentlyContinue) }
    }
    $m = [regex]::Match($text, "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($m.Success) { $publicUrl = $m.Value; break }
    if ($proc.HasExited) { break }
}

Write-Host ""
if ($publicUrl) {
    Write-Host "  公网地址：$publicUrl" -ForegroundColor Green
    Write-Host "  局域网地址：http://$(Get-LanIp):$Port" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  这个链接可以直接发给面试官 / 写进简历（进程不关就一直有效）。" -ForegroundColor Yellow
    Write-Host "  按 Ctrl+C 结束；结束后链接立即失效。" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  别忘了：对外暴露期间会消耗你的 DeepSeek 额度，" -ForegroundColor Yellow
    Write-Host "  公网长期部署请按 docs/deploy.md 走服务器方案（带限流）。" -ForegroundColor Yellow
} else {
    Write-Host "  没拿到公网地址，常见原因：" -ForegroundColor Red
    Write-Host "    1) 网络访问不了 Cloudflare（国内部分网络会被干扰）→ 换 ngrok 或直接上服务器；"
    Write-Host "    2) 本地 8000 端口没起来 → 先浏览器打开 http://127.0.0.1:$Port 确认；"
    Write-Host "    3) 日志：$ErrFile" -ForegroundColor DarkGray
    if (Test-Path $ErrFile) { Get-Content $ErrFile -Tail 15 }
}

Write-Host ""
Write-Host "按 Ctrl+C 结束脚本（同时关闭隧道）…"
try {
    Wait-Process -Id $proc.Id
} finally {
    # Ctrl+C 结束脚本时把隧道一起收掉，避免链接悄悄一直开着
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
