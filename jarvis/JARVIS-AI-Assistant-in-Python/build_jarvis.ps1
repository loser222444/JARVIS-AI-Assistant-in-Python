$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

Write-Host "Installing build and assistant dependencies..." -ForegroundColor Cyan
python -m pip install pyinstaller SpeechRecognition pyttsx3 PyAudioWPatch google-genai pyautogui

Write-Host "Building JARVIS.exe..." -ForegroundColor Cyan
python -m PyInstaller --clean --noconfirm JARVIS.spec

$desktopPath = Join-Path $env:USERPROFILE "Desktop\JARVIS.exe"
$desktopBuildPath = $desktopPath
try {
	Copy-Item ".\dist\JARVIS.exe" $desktopBuildPath -Force -ErrorAction Stop
}
catch [System.IO.IOException] {
	$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
	$desktopBuildPath = Join-Path $env:USERPROFILE "Desktop\JARVIS-$stamp.exe"
	Copy-Item ".\dist\JARVIS.exe" $desktopBuildPath -Force
	Write-Warning "Desktop JARVIS.exe is in use. Created $desktopBuildPath instead."
}

Write-Host "Build complete." -ForegroundColor Green
Write-Host "Executable: $desktopBuildPath"
Write-Host "Gemini support requires GEMINI_API_KEY to be set in your environment."
