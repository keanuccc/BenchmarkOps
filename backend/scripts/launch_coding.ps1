$codOut = 'D:\code\benchmarkv1\backend\run_coding.out.log'
$codErr = 'D:\code\benchmarkv1\backend\run_coding.err.log'
$pythonExe = 'D:\code\benchmarkv1\backend\.venv\Scripts\python.exe'
$env:BENCHMARKOPS_API = 'http://127.0.0.1:8011/api/v1'
if (Test-Path $codOut) { Remove-Item -LiteralPath $codOut -Force }
if (Test-Path $codErr) { Remove-Item -LiteralPath $codErr -Force }
$modelFilter = '"DeepSeek V3 (Qiniu),GPT-4o mini (OpenRouter)"'
$proc = Start-Process -FilePath $pythonExe -ArgumentList @('scripts/run_real_eval.py', '--only-coding', '--models', $modelFilter) `
    -WorkingDirectory 'D:\code\benchmarkv1\backend' `
    -RedirectStandardOutput $codOut -RedirectStandardError $codErr `
    -WindowStyle Hidden -PassThru
Write-Output ("CODING_PID=" + $proc.Id)
