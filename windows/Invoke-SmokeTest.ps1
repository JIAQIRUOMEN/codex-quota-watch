param([Parameter(Mandatory = $true)][string]$ReceiptDirectory)
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'Show-CodexQuotaAlert.ps1'
$powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
[IO.Directory]::CreateDirectory($ReceiptDirectory) | Out-Null
$events = Join-Path $ReceiptDirectory 'smoke-events'
[IO.Directory]::CreateDirectory($events) | Out-Null
1..3 | ForEach-Object {
    $id = 'smoke-' + [Guid]::NewGuid().ToString('N')
    $event = @{ id=$id; receipt_nonce=[Guid]::NewGuid().ToString('N'); title="Codex Quota Watch smoke test $_/3"; message='This is a visible UI smoke test. Closing automatically does not acknowledge an alert.'; ack_label='Acknowledge'; url='https://x.com/thsottiaux'; timing=@{kind='unknown'; published_text='Source time unavailable'; text='Timing unknown.'; basis=''; confidence=''} }
    $path = Join-Path $events ($id + '.json')
    $event | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $path -Encoding utf8
    Start-Process -FilePath $powershell -ArgumentList @('-NoProfile','-STA','-File',('"{0}"' -f $scriptPath),'-EventPath',('"{0}"' -f $path),'-ReceiptDirectory',('"{0}"' -f $ReceiptDirectory),'-SmokeTestCloseAfterSeconds','2') -WindowStyle Hidden
}
Write-Output "Three test windows launched. Receipts should report displayed then test_closed under $ReceiptDirectory; no acknowledgement is written."
