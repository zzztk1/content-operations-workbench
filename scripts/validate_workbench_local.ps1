$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
  $env:PYTHONPATH = "src"
  $env:LLM_MOCK = "true"
  $env:IMAGE_MOCK = "true"
  $env:VISION_REVIEW_MOCK = "true"
  $env:CHECKPOINTER_MOCK = "true"
  $env:CHECKPOINT_BACKEND = "memory"

  py scripts\validate_workbench_smoke.py

  Push-Location frontend
  $vite = $null
  try {
    npm.cmd run build
    $vite = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5179") -PassThru -WindowStyle Hidden
    $ok = $false
    for ($i = 0; $i -lt 20; $i++) {
      Start-Sleep -Milliseconds 500
      try {
        $status = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5179/" -TimeoutSec 2).StatusCode
        if ($status -eq 200) {
          $ok = $true
          break
        }
      }
      catch {}
    }
    if (-not $ok) {
      throw "Frontend dev server did not respond on http://127.0.0.1:5179/"
    }
    Write-Host "FRONTEND_DEV_SERVER_OK"
  }
  finally {
    if ($vite -and -not $vite.HasExited) {
      Stop-Process -Id $vite.Id -Force
    }
    Pop-Location
  }

  Write-Host "WORKBENCH_LOCAL_VALIDATE_OK"
}
finally {
  Pop-Location
}
