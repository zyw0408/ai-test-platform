$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$deployDir = Join-Path $projectRoot "docker-desktop"
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
$dockerPath = $null

if ($dockerCmd) {
  $dockerPath = $dockerCmd.Source
}

if (-not $dockerPath) {
  $dockerFallback = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
  if (Test-Path $dockerFallback) {
    $dockerPath = $dockerFallback
  } else {
    throw "Docker 未安装或未加入 PATH。"
  }
}

$dockerBinDir = Split-Path -Parent $dockerPath
if ($env:PATH -notlike "*$dockerBinDir*") {
  $env:PATH = "$dockerBinDir;$env:PATH"
}

Set-Location $deployDir
& $dockerPath compose --env-file .env -f docker-compose.yml down

if ($LASTEXITCODE -ne 0) {
  throw "Docker Compose 停止失败，退出码: $LASTEXITCODE"
}

Write-Host "[DONE] Deployment stopped."
