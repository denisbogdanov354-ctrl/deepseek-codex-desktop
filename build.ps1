$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt

python -m PyInstaller `
  --noconfirm `
  --clean `
  --noconsole `
  --onedir `
  --name "DeepSeek Codex" `
  --icon ".\assets\deepseek_codex.ico" `
  --version-file ".\version_info.txt" `
  --add-data ".\assets\deepseek_codex.ico;assets" `
  --collect-all tkinterdnd2 `
  ".\app.py"

Write-Host ""
Write-Host "Build complete: .\dist\DeepSeek Codex\DeepSeek Codex.exe"