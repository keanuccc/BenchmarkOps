Start-Process -FilePath "D:\code\benchmarkv1\backend\.venv\Scripts\python.exe" `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
  -WorkingDirectory "D:\code\benchmarkv1\backend" `
  -RedirectStandardOutput "D:\code\benchmarkv1\run_backend_dev.out.log" `
  -RedirectStandardError "D:\code\benchmarkv1\run_backend_dev.err.log" `
  -WindowStyle Hidden
