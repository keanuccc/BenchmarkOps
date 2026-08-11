$pyExe = 'D:\code\benchmarkv1\backend\.venv\Scripts\python.exe'
$env:DATABASE_URL = 'sqlite+aiosqlite:///./eval.db'
$outLog = 'D:\code\benchmarkv1\backend\eval_backend.out.log'
$errLog = 'D:\code\benchmarkv1\backend\eval_backend.err.log'
if (Test-Path $outLog) { Remove-Item -LiteralPath $outLog -Force }
if (Test-Path $errLog) { Remove-Item -LiteralPath $errLog -Force }
$proc = Start-Process -FilePath $pyExe -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8011') `
    -WorkingDirectory 'D:\code\benchmarkv1\backend' `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
    -WindowStyle Hidden -PassThru
Write-Output ("BACKEND_PID=" + $proc.Id)
Start-Sleep -Seconds 10
try {
    $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8011/api/v1/health' -TimeoutSec 10
    $h | ConvertTo-Json -Depth 3
} catch {
    Write-Output ('health failed: ' + $_.Exception.Message)
    Get-Content $errLog -Tail 20 -ErrorAction SilentlyContinue
}
