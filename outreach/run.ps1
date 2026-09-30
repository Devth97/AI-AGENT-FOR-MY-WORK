param([ValidateSet('research','send','run','export')][string]$Mode = 'research')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$credentialFile = Join-Path $PSScriptRoot 'data\gmail-credential.xml'
if (Test-Path -LiteralPath $credentialFile) {
    $mailCredential = Import-Clixml -LiteralPath $credentialFile
    $env:SMTP_HOST = 'smtp.gmail.com'
    $env:SMTP_PORT = '587'
    $env:IMAP_HOST = 'imap.gmail.com'
    $env:SMTP_USER = $mailCredential.UserName
    $env:IMAP_USER = $mailCredential.UserName
    $env:SMTP_PASSWORD = $mailCredential.GetNetworkCredential().Password
    $env:IMAP_PASSWORD = $env:SMTP_PASSWORD
}
try {
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'pipeline.py') $Mode
    if ($LASTEXITCODE -ne 0) { throw "Pipeline exited with code $LASTEXITCODE" }
} finally {
    Remove-Item Env:SMTP_PASSWORD,Env:IMAP_PASSWORD -ErrorAction SilentlyContinue
}
