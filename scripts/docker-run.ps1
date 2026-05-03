param(
  [switch]$NoCache,
  [switch]$ForceRecreate,
  [string[]]$Services
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$deployDir = Join-Path $projectRoot "docker-desktop"
$envExample = Join-Path $deployDir ".env.example"
$envFile = Join-Path $deployDir ".env"
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

function Assert-DockerEngineHealthy {
  param(
    [string]$DockerExe
  )

  $outFile = [System.IO.Path]::GetTempFileName()
  $errFile = [System.IO.Path]::GetTempFileName()
  try {
    $proc = Start-Process -FilePath $DockerExe -ArgumentList @("version", "--format", "{{.Server.Version}}") -NoNewWindow -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    if (-not $proc.WaitForExit(15000)) {
      try { $proc.Kill() } catch {}
      throw "Docker 引擎检查超时（15 秒）。"
    }
    if ($proc.ExitCode -ne 0) {
      $stderr = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
      if (-not $stderr) {
        $stderr = "无详细错误输出。"
      }
      throw "Docker 引擎检查失败: $stderr"
    }
  } catch {
    throw @"
Docker 引擎当前不可用（通常是 Docker Desktop Linux Engine 未就绪或存储层异常）。
请先在 Docker Desktop 执行：
1) Troubleshoot -> Clean / Purge data（优先）
2) 若仍失败，Troubleshoot -> Reset to factory defaults
然后重试：
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -NoCache -ForceRecreate -Services web nginx
"@
  } finally {
    Remove-Item $outFile,$errFile -Force -ErrorAction SilentlyContinue
  }
}

if (-not (Test-Path $envFile)) {
  Copy-Item $envExample $envFile
  Write-Host "[INFO] 已生成部署环境文件: $envFile"
}

Set-Location $deployDir
$env:COMPOSE_BAKE = "false"
Assert-DockerEngineHealthy -DockerExe $dockerPath

if ($NoCache) {
  $buildArgs = @("compose", "--env-file", ".env", "-f", "docker-compose.yml", "build", "--no-cache")
  if ($Services -and $Services.Count -gt 0) {
    $buildArgs += $Services
  }

  & $dockerPath @buildArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose 构建失败，退出码: $LASTEXITCODE"
  }
}

$upArgs = @("compose", "--env-file", ".env", "-f", "docker-compose.yml", "up", "-d", "--build")
if ($ForceRecreate) {
  $upArgs += "--force-recreate"
}
if ($Services -and $Services.Count -gt 0) {
  $upArgs += $Services
}

& $dockerPath @upArgs

if ($LASTEXITCODE -ne 0) {
  throw "Docker Compose 启动失败，退出码: $LASTEXITCODE"
}

Write-Host "[DONE] Nginx: http://localhost"
