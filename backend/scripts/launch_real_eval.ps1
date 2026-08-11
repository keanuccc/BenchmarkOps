$benchOut = 'D:\code\benchmarkv1\backend\run_real_eval.out.log'
$benchErr = 'D:\code\benchmarkv1\backend\run_real_eval.err.log'
$pythonExe = 'D:\code\benchmarkv1\backend\.venv\Scripts\python.exe'
$env:BENCHMARKOPS_API = 'http://127.0.0.1:8001/api/v1'
if (Test-Path $benchOut) { Remove-Item -LiteralPath $benchOut -Force }
if (Test-Path $benchErr) { Remove-Item -LiteralPath $benchErr -Force }
$modelFilter = '"DeepSeek V3 (Qiniu),Doubao Seed 2.0 Pro (Qiniu),GPT-4o mini (OpenRouter)"'
$proc = Start-Process -FilePath $pythonExe -ArgumentList @('scripts/run_real_eval.py', '--models', $modelFilter) `
    -WorkingDirectory 'D:\code\benchmarkv1\backend' `
    -RedirectStandardOutput $benchOut -RedirectStandardError $benchErr `
    -WindowStyle Hidden -PassThru
Write-Output ("PID=" + $proc.Id)
Start-Sleep -Seconds 15
Write-Output '===== out log tail ====='
Get-Content $benchOut -Tail 20 -ErrorAction SilentlyContinue
Write-Output '===== err log tail ====='
Get-Content $benchErr -Tail 20 -ErrorAction SilentlyContinue
