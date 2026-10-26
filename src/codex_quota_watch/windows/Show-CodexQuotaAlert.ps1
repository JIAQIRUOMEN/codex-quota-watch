param(
    [Parameter(Mandatory = $true)][string]$EventPath,
    [Parameter(Mandatory = $true)][string]$ReceiptDirectory,
    [ValidateRange(0, 60)][int]$SmokeTestCloseAfterSeconds = 0
)
$ErrorActionPreference = 'Stop'

# Parse and validate the complete untrusted event before constructing or showing UI.
$raw = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $EventPath), [Text.Encoding]::UTF8)
$eventData = $raw | ConvertFrom-Json
if ($eventData.id -isnot [string] -or $eventData.id -notmatch '^[A-Za-z0-9_-]{1,100}$') { throw 'Invalid event id' }
foreach ($field in @('title', 'message', 'ack_label', 'url')) {
    if ($eventData.$field -isnot [string] -or [string]::IsNullOrWhiteSpace($eventData.$field)) { throw "Missing or invalid $field" }
}
if ($eventData.receipt_nonce -isnot [string] -or $eventData.receipt_nonce -notmatch '^[a-f0-9]{32}$') { throw 'Invalid event receipt nonce' }
if ($eventData.title.Length -gt 120 -or $eventData.message.Length -gt 2000 -or $eventData.url.Length -gt 2000) { throw 'Alert text too long' }
if ($eventData.url -notmatch '^https?://') { throw 'Invalid source URL' }
if ($eventData.timing -isnot [pscustomobject]) { throw 'Invalid timing data' }
if ($eventData.timing.kind -notin @('explicit', 'estimated', 'unknown')) { throw 'Invalid timing kind' }
foreach ($field in @('published_text', 'text')) {
    if ($eventData.timing.$field -isnot [string] -or [string]::IsNullOrWhiteSpace($eventData.timing.$field)) { throw "Missing timing $field" }
}
if ($eventData.timing.kind -eq 'estimated' -and [string]::IsNullOrWhiteSpace([string]$eventData.timing.basis)) { throw 'Estimated timing requires an evidence basis' }
foreach ($field in @('published_text', 'text', 'basis', 'confidence')) {
    if (([string]$eventData.timing.$field).Length -gt 350) { throw 'Timing field too long' }
}

[IO.Directory]::CreateDirectory($ReceiptDirectory) | Out-Null
$receiptPath = Join-Path $ReceiptDirectory ($eventData.id + '.json')
function Write-Receipt([string]$status, [string]$errorText = '') {
    $receipt = [ordered]@{ event_id = $eventData.id; receipt_nonce = $eventData.receipt_nonce; status = $status; at = [DateTime]::UtcNow.ToString('o'); process_id = $PID; error = $errorText; timing = $eventData.timing }
    $temporaryPath = $receiptPath + '.' + $PID + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporaryPath, ($receipt | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryPath -Destination $receiptPath -Force
}

$mutex = [Threading.Mutex]::new($false, ('Local\CodexQuotaWatch_' + $eventData.id))
$ownsMutex = $false
$script:testTimer = $null
$script:window = $null
$script:alertAcknowledged = $false
$script:testClosed = $false
try {
    try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { Write-Output 'Alert already open'; exit 0 }
    if (Test-Path -LiteralPath $receiptPath) {
        $oldReceipt = [IO.File]::ReadAllText($receiptPath) | ConvertFrom-Json
        if ($oldReceipt.event_id -eq $eventData.id -and $oldReceipt.status -eq 'acknowledged') { Write-Output 'Alert already acknowledged'; exit 0 }
    }
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName WindowsBase
    $script:window = [Windows.Window]::new()
    $script:window.Title = $eventData.title; $script:window.Width = 490; $script:window.SizeToContent = 'Height'; $script:window.MinHeight = 210; $script:window.MaxHeight = 650
    $script:window.WindowStartupLocation = 'CenterScreen'; $script:window.ResizeMode = 'CanMinimize'; $script:window.Topmost = $true; $script:window.ShowInTaskbar = $true
    $script:window.Background = [Windows.Media.Brushes]::White; $script:window.FontFamily = [Windows.Media.FontFamily]::new('Microsoft YaHei UI')
    $panel = [Windows.Controls.StackPanel]::new(); $panel.Margin = [Windows.Thickness]::new(24)
    $heading = [Windows.Controls.TextBlock]::new(); $heading.Text = $eventData.title; $heading.FontSize = 20; $heading.FontWeight = 'SemiBold'; $heading.TextWrapping = 'Wrap'; $panel.Children.Add($heading) | Out-Null
    $body = [Windows.Controls.TextBlock]::new(); $body.Text = $eventData.message; $body.FontSize = 15; $body.TextWrapping = 'Wrap'; $body.Margin = [Windows.Thickness]::new(0, 16, 0, 16); $panel.Children.Add($body) | Out-Null
    $timeBox = [Windows.Controls.TextBlock]::new(); $timeBox.Text = $eventData.timing.published_text + "`n" + $eventData.timing.text; $timeBox.FontSize = 14; $timeBox.TextWrapping = 'Wrap'; $timeBox.Margin = [Windows.Thickness]::new(0, 0, 0, 12)
    if ($eventData.timing.kind -eq 'estimated') { $timeBox.Foreground = [Windows.Media.Brushes]::DarkOrange }
    $panel.Children.Add($timeBox) | Out-Null
    if ($eventData.timing.basis) {
        $basis = [Windows.Controls.TextBlock]::new(); $basis.Text = [string]$eventData.timing.basis
        if ($eventData.timing.confidence) { $basis.Text += ' (' + [string]$eventData.timing.confidence + ')' }
        $basis.FontSize = 12; $basis.Foreground = [Windows.Media.Brushes]::DimGray; $basis.TextWrapping = 'Wrap'; $basis.Margin = [Windows.Thickness]::new(0, 0, 0, 16); $panel.Children.Add($basis) | Out-Null
    }
    $source = [Windows.Controls.TextBox]::new(); $source.Text = $eventData.url; $source.IsReadOnly = $true; $source.BorderThickness = [Windows.Thickness]::new(0); $source.FontSize = 11; $source.Margin = [Windows.Thickness]::new(0, 0, 0, 16); $panel.Children.Add($source) | Out-Null
    $button = [Windows.Controls.Button]::new(); $button.Content = $eventData.ack_label; $button.FontSize = 15; $button.Padding = [Windows.Thickness]::new(22, 8, 22, 8); $button.HorizontalAlignment = 'Right'
    $button.Add_Click({ Write-Receipt 'acknowledged'; $script:alertAcknowledged = $true; $script:window.Close() }); $panel.Children.Add($button) | Out-Null
    $script:window.Content = $panel
    $script:window.Add_ContentRendered({ Write-Receipt 'displayed' })
    $script:window.Add_Closed({
        if ($script:testClosed) { Write-Receipt 'test_closed' }
        elseif (-not $script:alertAcknowledged) { Write-Receipt 'dismissed_unacknowledged' }
    })
    if ($SmokeTestCloseAfterSeconds -gt 0) {
        $script:window.Add_ContentRendered({
            $script:testTimer = [Windows.Threading.DispatcherTimer]::new()
            $script:testTimer.Interval = [TimeSpan]::FromSeconds($SmokeTestCloseAfterSeconds)
            $script:testTimer.Add_Tick({ $script:testTimer.Stop(); $script:testClosed = $true; $script:window.Close() })
            $script:testTimer.Start()
        })
    }
    $script:window.ShowDialog() | Out-Null
} catch {
    try { Write-Receipt 'failed' $_.Exception.Message } catch { }
    throw
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
