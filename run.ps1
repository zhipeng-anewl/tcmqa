<#
  本地启动脚本（Windows / PowerShell）

  用法：
    .\run.ps1              启动 API 服务（http://127.0.0.1:8000）
    .\run.ps1 index        重建向量索引
    .\run.ps1 test         跑单元测试
    .\run.ps1 eval         跑金标集评测
    .\run.ps1 api-test     跑接口回归测试（需先启动服务）
#>
param([string]$Task = "serve")

$ErrorActionPreference = "Stop"
# 如果不用 conda 环境，改成你的 python.exe 路径
$Python = "D:\Anaconda3\envs\pytorch\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$env:PYTHONIOENCODING = "utf-8"

switch ($Task) {
    "serve"    { & $Python -m uvicorn tcmqa.main:app --host 127.0.0.1 --port 8000 --reload }
    "index"    { & $Python scripts/build_index.py }
    "index-all"{ & $Python scripts/build_index.py --ingredients }
    "images"   { & $Python scripts/build_images.py }
    "vision"   { & $Python scripts/build_vision_index.py }
    "vision-text" { & $Python scripts/build_vision_text.py }
    "vision-eval" { & $Python scripts/eval_vision.py; & $Python scripts/eval_vision_text.py --sweep }
    "test"     { & $Python -m pytest tests -q }
    "eval"     { & $Python scripts/run_eval.py }
    "api-test" { & $Python scripts/test_api.py }
    "smoke"    { & $Python scripts/smoke_qa.py }
    default    { Write-Host "未知任务：$Task（可用：serve / index / index-all / images / test / eval / api-test / smoke）" }
}
