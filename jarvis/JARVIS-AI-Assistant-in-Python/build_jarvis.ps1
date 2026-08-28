$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

# Build with the PROJECT virtual environment so bundled dependencies match
# what was actually tested. Bare `python` on PATH may be the system
# interpreter, which lacks several packages JARVIS depends on.
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "Virtual environment interpreter not found: $py"
}

Write-Host "Installing build and assistant dependencies..." -ForegroundColor Cyan
& $py -m pip install pyinstaller SpeechRecognition pyttsx3 PyAudioWPatch google-genai pyautogui python-dotenv customtkinter

Write-Host "Building JARVIS.exe (cinematic sci-fi HUD included)..." -ForegroundColor Cyan
& $py -m PyInstaller --clean --noconfirm JARVIS.spec

$desktopBuildPath = Join-Path $env:USERPROFILE "Desktop\JARVIS.exe"
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
Write-Host "Gemini support: keep GEMINI_API_KEY either in your environment or in a"
Write-Host '.env file placed NEXT TO JARVIS.exe:'
Write-Host '    GEMINI_API_KEY=your-key-here'
