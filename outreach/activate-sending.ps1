$ErrorActionPreference = 'Stop'
$credentialFile = Join-Path $PSScriptRoot 'data\gmail-credential.xml'
if (-not (Test-Path -LiteralPath $credentialFile)) { throw 'Run connect-gmail.ps1 first.' }
$mailCredential = Import-Clixml -LiteralPath $credentialFile
$env:SMTP_USER = $mailCredential.UserName
$env:SMTP_PASSWORD = $mailCredential.GetNetworkCredential().Password
try {
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'verify_gmail.py')
    if ($LASTEXITCODE -ne 0) { throw 'Gmail connection verification failed. Sending was not enabled.' }
    $configPath = Join-Path $PSScriptRoot 'config.json'
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    if (-not $config.postal_address) { throw 'Configure the business mailing address first.' }
    $config.send_enabled = $true
    $config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configPath -Encoding UTF8
    Write-Output 'Gmail verified. Sending is enabled for the configured campaign target and send interval.'
} finally {
    Remove-Item Env:SMTP_PASSWORD -ErrorAction SilentlyContinue
}
