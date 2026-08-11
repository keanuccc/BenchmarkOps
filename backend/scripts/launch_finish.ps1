$finOut = 'D:\code\benchmarkv1\backend\run_finish.out.log'
$finErr = 'D:\code\benchmarkv1\backend\run_finish.err.log'
$pythonExe = 'D:\code\benchmarkv1\backend\.venv\Scripts\python.exe'
$env:BENCHMARKOPS_API = 'http://127.0.0.1:8011/api/v1'
if (Test-Path $finOut) { Remove-Item -LiteralPath $finOut -Force }
if (Test-Path $finErr) { Remove-Item -LiteralPath $finErr -Force }
$proc = Start-Process -FilePath $pythonExe -ArgumentList @('scripts/finish_real_eval.py', '--project', '671b8aec-7fce-4f1b-bf10-45c451d8f1a8') `
    -WorkingDirectory 'D:\code\benchmarkv1\backend' `
    -RedirectStandardOutput $finOut -RedirectStandardError $finErr `
    -WindowStyle Hidden -PassThru
Write-Output ("FINISH_PID=" + $proc.Id)
