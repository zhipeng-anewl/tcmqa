<#
  把服务器部署需要的文件整理到 deploy/ 下：图谱 dump + 检索索引 + 图片 + 模型缓存。

  用法（项目根目录）：
    powershell -ExecutionPolicy Bypass -File .\scripts\export_deploy.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\export_deploy.ps1 -SkipModels    # 不传 1.5G 模型缓存
    powershell -ExecutionPolicy Bypass -File .\scripts\export_deploy.ps1 -KeepStopped   # 导完不重启本地 Neo4j

  产出：
    deploy/backup/neo4j.dump        图谱（约 15MB），容器首次启动自动导入
    deploy/data/index/              向量 + BM25 索引（约 11MB）
    deploy/data/images/             中药封面与图库缩略图（约 40MB）
    deploy/data/cache/hf/           bge + Chinese-CLIP 权重（约 1.5GB，可用 -SkipModels 跳过）
    deploy/media/mol/               分子结构图（约 168MB，可用 -SkipMol 跳过）
    deploy/data/*.json              ／疾病中文名映射等运行期数据

  注意：dump 要求数据库处于停止状态，所以脚本会先停 Neo4j、导完再拉起来。
#>
param(
    [string]$Neo4jHome = "D:\neo4j\neo4j-community-5.26.12-windows\neo4j-community-5.26.12",
    [switch]$SkipDump,
    [switch]$SkipModels,
    [switch]$SkipMol,
    [switch]$KeepStopped
)

$ErrorActionPreference = "Stop"

$Root    = Split-Path $PSScriptRoot -Parent
$Deploy  = Join-Path $Root "deploy"
$HerbDir = Join-Path (Split-Path $Root -Parent) "构建知识图谱"

function Test-Port([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $Port)
        $c.Close()
        return $true
    } catch { return $false }
}

function Wait-Port([int]$Port, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Get-ListenPid([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        if ($conn) { return ($conn | Select-Object -First 1).OwningProcess }
    } catch { }
    $line = netstat -ano | Select-String ":$Port\s+\S+\s+LISTENING" | Select-Object -First 1
    if ($line) { return [int](($line -split "\s+")[-1]) }
    return 0
}

function Stop-Neo4j {
    if (-not (Test-Port 7687)) { return }
    $procId = Get-ListenPid 7687
    if ($procId) {
        Write-Host "  停止 Neo4j（PID $procId）…"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }
    if (Test-Port 7687) { throw "Neo4j 仍在运行，无法导出 dump。请手动关闭后重试。" }
}

function Start-Neo4j {
    if (-not (Test-Path "$Neo4jHome\bin\neo4j.bat")) {
        Write-Host "  找不到 $Neo4jHome\bin\neo4j.bat，跳过重启" -ForegroundColor Yellow
        return
    }
    Write-Host "  重新启动 Neo4j…"
    Start-Process -FilePath "$Neo4jHome\bin\neo4j.bat" -ArgumentList "console" `
        -WorkingDirectory $Neo4jHome -WindowStyle Minimized
    if (Wait-Port 7687 120) {
        Write-Host "  Neo4j 已恢复（bolt 7687）" -ForegroundColor Green
    } else {
        Write-Host "  Neo4j 120 秒内没起来，请手动执行 start.bat" -ForegroundColor Yellow
    }
}

function Sync-Dir([string]$Src, [string]$Dst, [string[]]$ExcludeDirs = @()) {
    if (-not (Test-Path $Src)) {
        Write-Host "  跳过（源不存在）：$Src" -ForegroundColor Yellow
        return
    }
    New-Item -ItemType Directory -Force -Path $Dst | Out-Null
    $rcArgs = @($Src, $Dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1")
    if ($ExcludeDirs.Count -gt 0) { $rcArgs += "/XD"; $rcArgs += $ExcludeDirs }
    $null = robocopy @rcArgs
    if ($LASTEXITCODE -ge 8) { throw "复制失败（robocopy $LASTEXITCODE）：$Src" }
    $global:LASTEXITCODE = 0
}

function Get-SizeMB([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $sum = (Get-ChildItem -Recurse -File $Path -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    if (-not $sum) { return 0 }
    return [math]::Round($sum / 1MB, 1)
}

# ---------------------------------------------------------------------- #
Write-Host ""
Write-Host "=== 准备部署产物 ===" -ForegroundColor Cyan

# 1) 图谱 dump
if ($SkipDump) {
    Write-Host "[1/5] 跳过图谱 dump" -ForegroundColor DarkGray
} else {
    Write-Host "[1/5] 导出图谱 dump"
    if (-not (Test-Path "$Neo4jHome\bin\neo4j-admin.bat")) {
        Write-Host "  找不到 neo4j-admin，跳过" -ForegroundColor Yellow
    } else {
        $backup = Join-Path $Deploy "backup"
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        Stop-Neo4j
        Write-Host "  导出中（约 10 秒）…"
        & "$Neo4jHome\bin\neo4j-admin.bat" database dump neo4j "--to-path=$backup" 2>&1 |
            ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) { throw "neo4j-admin dump 失败，检查 JAVA_HOME 是否指向 JDK 17" }
        if (-not $KeepStopped) { Start-Neo4j }
    }
}

# 2) 检索索引
Write-Host "[2/5] 复制检索索引"
Sync-Dir (Join-Path $Root "data\index") (Join-Path $Deploy "data\index")

# 3) 图片
Write-Host "[3/5] 复制图片（封面 / 缩略图）"
Sync-Dir (Join-Path $Root "data\images") (Join-Path $Deploy "data\images")

# 4) 运行期数据文件
Write-Host "[4/5] 复制运行期数据文件"
$runtimeFiles = @("disease_zh.json", "ingredient_zh.json", "golden_set.jsonl")
foreach ($f in $runtimeFiles) {
    $src = Join-Path $Root "data\$f"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $Deploy "data\$f") -Force
    }
}

# 5) 模型缓存 / 分子结构图
if ($SkipModels) {
    Write-Host "[5/5] 跳过模型缓存（服务器首次启动会自己下载，国内建议保留）" -ForegroundColor DarkGray
} else {
    Write-Host "[5/5] 复制模型缓存（1.5GB，稍慢）"
    Sync-Dir (Join-Path $Root "data\cache\hf") (Join-Path $Deploy "data\cache\hf") @(".locks")
}

if (-not $SkipMol) {
    $molSrc = Join-Path $HerbDir "TCMSP\molecular_structures"
    if (Test-Path $molSrc) {
        Write-Host "     复制分子结构图（168MB）"
        Sync-Dir $molSrc (Join-Path $Deploy "media\mol")
    } else {
        Write-Host "     分子结构图目录不存在，跳过：$molSrc" -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------- #
Write-Host ""
Write-Host "=== 产物清单 ===" -ForegroundColor Cyan
$items = @(
    @{ Name = "图谱 dump";   Path = Join-Path $Deploy "backup" },
    @{ Name = "检索索引";    Path = Join-Path $Deploy "data\index" },
    @{ Name = "图片";        Path = Join-Path $Deploy "data\images" },
    @{ Name = "模型缓存";    Path = Join-Path $Deploy "data\cache\hf" },
    @{ Name = "分子结构图";  Path = Join-Path $Deploy "media\mol" }
)
foreach ($it in $items) {
    $mb = Get-SizeMB $it.Path
    $flag = if ($mb -eq 0) { "（空，部署时对应功能会降级）" } else { "$mb MB" }
    Write-Host ("  {0,-12} {1}" -f $it.Name, $flag)
}
Write-Host ""

$total = Get-SizeMB $Deploy
Write-Host ("  合计约 {0} MB（不含代码与镜像）" -f $total)

Write-Host ""
Write-Host "=== 下一步 ===" -ForegroundColor Cyan
Write-Host "  1) deploy\.env.example 复制成 deploy\.env，填 DEEPSEEK_API_KEY / NEO4J_PASSWORD / SITE_ADDRESS"
Write-Host "  2) 代码上传（git clone 或 rsync），数据这样传："
Write-Host "     rsync -avz --progress deploy/data deploy/backup deploy/media root@服务器IP:/opt/tcmqa/deploy/" -ForegroundColor DarkGray
Write-Host "  3) 服务器上：cd /opt/tcmqa/deploy && docker compose -f docker-compose.prod.yml up -d --build"
Write-Host "  4) 浏览器打开 http://服务器IP 验收，完整步骤见 docs/deploy.md"
Write-Host ""
