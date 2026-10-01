$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'data') | Out-Null
$mailCredential = Get-Credential -UserName 'khalandarthameem97@gmail.com' -Message 'Enter a newly generated 16-character Google app password without spaces, NOT your ordinary account password. It is encrypted for this Windows account.'
if ($null -eq $mailCredential) { throw 'No credential supplied' }
$mailCredential | Export-Clixml -LiteralPath (Join-Path $PSScriptRoot 'data\gmail-credential.xml')
Write-Output 'Gmail credential saved with Windows user encryption. Sending remains controlled by config.json.'
