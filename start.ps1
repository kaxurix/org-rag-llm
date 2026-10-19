param([int]$Port = 8000, [switch]$WithAI, [string]$OllamaLibrary = 'vulkan', [int]$GpuMarginMB = 512)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$ragPython = Join-Path $PSScriptRoot 'venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ragPython)) {
    $ragPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $ragPython)) {
    throw 'Buat virtual environment dan instal requirements.txt sesuai README.md terlebih dahulu.'
}
$ragProvider = & $ragPython -c 'from config import Settings; print(Settings().provider)'
if ($WithAI -and $ragProvider -eq 'ollama') {
    $ragOllama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ragOllama) {
        Write-Warning 'Ollama belum terpasang. Aplikasi tetap tersedia dengan kutipan sumber.'
    } else {
        $ragOllamaReady = $false
        try {
            $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
            $ragOllamaReady = $true
        } catch { }
        if (-not $ragOllamaReady) {
            if ($OllamaLibrary) { $env:OLLAMA_LLM_LIBRARY = $OllamaLibrary }
            $env:OLLAMA_CONTEXT_LENGTH = '4096'
            $env:OLLAMA_KEEP_ALIVE = '30m'
            if ($GpuMarginMB -ge 256) { $env:LLAMA_ARG_FIT_TARGET = [string]$GpuMarginMB }
            $ragLogDir = Join-Path $PSScriptRoot 'data'
            $null = New-Item -ItemType Directory -Path $ragLogDir -Force
            Start-Process -FilePath $ragOllama.Source -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $ragLogDir 'ollama.stdout.log') -RedirectStandardError (Join-Path $ragLogDir 'ollama.stderr.log')
            Write-Host 'Ollama dijalankan di latar belakang. Log tersedia di data/ollama.stderr.log.'
        } elseif ($OllamaLibrary) {
            Write-Host 'Ollama sudah berjalan; pilihan library hanya berlaku saat proses baru dijalankan.'
        }
    }
}
Write-Host "CampusOrg: http://127.0.0.1:$Port"
& $ragPython -B -m uvicorn main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
