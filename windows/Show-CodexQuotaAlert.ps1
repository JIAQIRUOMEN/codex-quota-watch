param(
    [Parameter(Mandatory = $true)][string]$EventPath,
    [Parameter(Mandatory = $true)][string]$ReceiptDirectory,
    [switch]$ValidateOnly,
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
foreach ($field in @('published_text', 'text')) {
    if ($eventData.timing.$field -isnot [string] -or $eventData.timing.$field.Length -gt 350) { throw 'Invalid timing field' }
}
foreach ($field in @('basis', 'confidence')) {
    if ($null -ne $eventData.timing.$field -and ($eventData.timing.$field -isnot [string] -or $eventData.timing.$field.Length -gt 350)) { throw 'Invalid optional timing field' }
}
if ($eventData.translations -ne $null) {
    if ($eventData.translations -isnot [pscustomobject]) { throw 'Invalid translations object' }
    $languageNames = @($eventData.translations.PSObject.Properties.Name | Sort-Object)
    if (($languageNames -join ',') -ne 'en,zh-CN') { throw 'Translations must contain exactly en and zh-CN' }
    foreach ($language in @('zh-CN', 'en')) {
        $translated = $eventData.translations.$language
        if ($translated -isnot [pscustomobject]) { throw "Invalid $language translation" }
        foreach ($field in @('title', 'message', 'ack_label')) {
            $limit = if ($field -eq 'title') { 120 } elseif ($field -eq 'message') { 2000 } else { 120 }
            if ($translated.$field -isnot [string] -or [string]::IsNullOrWhiteSpace($translated.$field) -or $translated.$field.Length -gt $limit) { throw "Invalid $language $field" }
        }
        $translatedTiming = $translated.timing
        if ($translatedTiming -isnot [pscustomobject] -or $translatedTiming.kind -notin @('explicit', 'estimated', 'unknown')) { throw "Invalid $language timing" }
        foreach ($field in @('published_text', 'text', 'basis', 'confidence')) {
            if ($translatedTiming.$field -isnot [string] -or $translatedTiming.$field.Length -gt 350) { throw "Invalid $language timing $field" }
        }
        if ([string]::IsNullOrWhiteSpace($translatedTiming.published_text) -or [string]::IsNullOrWhiteSpace($translatedTiming.text)) { throw "Missing $language timing text" }
        if ($translatedTiming.kind -eq 'estimated' -and [string]::IsNullOrWhiteSpace($translatedTiming.basis)) { throw "Estimated $language timing requires a basis" }
        if ($translatedTiming.kind -ne $eventData.timing.kind) { throw "$language timing kind must match event" }
    }
}
if ($ValidateOnly) { Write-Output 'valid'; exit 0 }

$ReceiptDirectory = [IO.Path]::GetFullPath($ReceiptDirectory)
[IO.Directory]::CreateDirectory($ReceiptDirectory) | Out-Null
$receiptPath = Join-Path $ReceiptDirectory ($eventData.id + '.json')
function Write-Receipt([string]$status, [string]$errorText = '') {
    $receipt = [ordered]@{ event_id = $eventData.id; receipt_nonce = $eventData.receipt_nonce; status = $status; at = [DateTime]::UtcNow.ToString('o'); process_id = $PID; error = $errorText; timing = $eventData.timing; language = $script:currentLanguage }
    $temporaryPath = $receiptPath + '.' + $PID + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporaryPath, ($receipt | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryPath -Destination $receiptPath -Force
}

$languagePath = Join-Path (Split-Path -Parent $ReceiptDirectory) 'popup-language.json'
function Get-InitialLanguage {
    try {
        if (Test-Path -LiteralPath $languagePath) {
            $saved = [IO.File]::ReadAllText($languagePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
            if ($saved.language -in @('zh-CN', 'en')) { return [string]$saved.language }
        }
    } catch { }
    if ([Globalization.CultureInfo]::CurrentUICulture.Name.StartsWith('zh', [StringComparison]::OrdinalIgnoreCase)) { return 'zh-CN' }
    return 'en'
}
function Save-Language([string]$language) {
    $parent = Split-Path -Parent $languagePath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporaryPath = $languagePath + '.' + $PID + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporaryPath, (@{ language = $language } | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
    try {
        if ([IO.File]::Exists($languagePath)) { [IO.File]::Replace($temporaryPath, $languagePath, $null) }
        else { [IO.File]::Move($temporaryPath, $languagePath) }
    } finally { if ([IO.File]::Exists($temporaryPath)) { [IO.File]::Delete($temporaryPath) } }
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
    $script:currentLanguage = Get-InitialLanguage
    $script:window.Title = $eventData.title; $script:window.Width = 490; $script:window.SizeToContent = 'Height'; $script:window.MinHeight = 210; $script:window.MaxHeight = 650
    $script:window.WindowStartupLocation = 'CenterScreen'; $script:window.ResizeMode = 'CanMinimize'; $script:window.Topmost = $true; $script:window.ShowInTaskbar = $true
    $script:window.Background = [Windows.Media.Brushes]::White; $script:window.FontFamily = [Windows.Media.FontFamily]::new('Microsoft YaHei UI')
    $panel = [Windows.Controls.StackPanel]::new(); $panel.Margin = [Windows.Thickness]::new(24)
    $script:languageSelector = [Windows.Controls.ComboBox]::new(); $script:languageSelector.Name = 'languageSelector'; $script:languageSelector.SetValue([Windows.Automation.AutomationProperties]::AutomationIdProperty, 'languageSelector'); $script:languageSelector.Items.Add('中文') | Out-Null; $script:languageSelector.Items.Add('English') | Out-Null; $script:languageSelector.SelectedIndex = if ($script:currentLanguage -eq 'zh-CN') { 0 } else { 1 }; $script:languageSelector.HorizontalAlignment = 'Right'; $script:languageSelector.Margin = [Windows.Thickness]::new(0, 0, 0, 14); $panel.Children.Add($script:languageSelector) | Out-Null
    $script:saveError = [Windows.Controls.TextBlock]::new(); $script:saveError.Name = 'languageSaveError'; $script:saveError.SetValue([Windows.Automation.AutomationProperties]::AutomationIdProperty, 'languageSaveError'); $script:saveError.Foreground = [Windows.Media.Brushes]::Firebrick; $script:saveError.TextWrapping = 'Wrap'; $script:saveError.Visibility = 'Collapsed'; $panel.Children.Add($script:saveError) | Out-Null
    $script:heading = [Windows.Controls.TextBlock]::new(); $script:heading.Name = 'alertTitle'; $script:heading.SetValue([Windows.Automation.AutomationProperties]::AutomationIdProperty, 'alertTitle'); $script:heading.FontSize = 20; $script:heading.FontWeight = 'SemiBold'; $script:heading.TextWrapping = 'Wrap'; $panel.Children.Add($script:heading) | Out-Null
    $script:body = [Windows.Controls.TextBlock]::new(); $script:body.Name = 'alertMessage'; $script:body.SetValue([Windows.Automation.AutomationProperties]::AutomationIdProperty, 'alertMessage'); $script:body.FontSize = 15; $script:body.TextWrapping = 'Wrap'; $script:body.Margin = [Windows.Thickness]::new(0, 16, 0, 16); $panel.Children.Add($script:body) | Out-Null
    $script:timeBox = [Windows.Controls.TextBlock]::new(); $script:timeBox.Name = 'alertTiming'; $script:timeBox.SetValue([Windows.Automation.AutomationProperties]::AutomationIdProperty, 'alertTiming'); $script:timeBox.FontSize = 14; $script:timeBox.TextWrapping = 'Wrap'; $script:timeBox.Margin = [Windows.Thickness]::new(0, 0, 0, 12)
    $panel.Children.Add($script:timeBox) | Out-Null
    $script:basis = [Windows.Controls.TextBlock]::new(); $script:basis.Name = 'alertBasis'; $script:basis.SetValue([Windows.Automation.AutomationProperties]::AutomationIdProperty, 'alertBasis'); $script:basis.FontSize = 12; $script:basis.Foreground = [Windows.Media.Brushes]::DimGray; $script:basis.TextWrapping = 'Wrap'; $script:basis.Margin = [Windows.Thickness]::new(0, 0, 0, 16); $panel.Children.Add($script:basis) | Out-Null
    $source = [Windows.Controls.TextBox]::new(); $source.Text = $eventData.url; $source.IsReadOnly = $true; $source.BorderThickness = [Windows.Thickness]::new(0); $source.FontSize = 11; $source.Margin = [Windows.Thickness]::new(0, 0, 0, 16); $panel.Children.Add($source) | Out-Null
    $script:button = [Windows.Controls.Button]::new(); $script:button.Name = 'acknowledgeButton'; $script:button.SetValue([Windows.Automation.AutomationProperties]::AutomationIdProperty, 'acknowledgeButton'); $script:button.FontSize = 15; $script:button.Padding = [Windows.Thickness]::new(22, 8, 22, 8); $script:button.HorizontalAlignment = 'Right'
    $script:updateLanguage = {
        $lang = $script:currentLanguage
        if ($eventData.translations -and $eventData.translations.$lang) { $words = $eventData.translations.$lang }
        else { $words = @{ title = $eventData.title; message = $eventData.message; ack_label = $eventData.ack_label; timing = $eventData.timing } }
        $script:window.Title = $words.title; $script:heading.Text = $words.title; $script:body.Text = $words.message
        $script:timeBox.Text = $words.timing.published_text + "`n" + $words.timing.text
        $script:timeBox.Foreground = if ($words.timing.kind -eq 'estimated') { [Windows.Media.Brushes]::DarkOrange } else { [Windows.Media.Brushes]::Black }
        $script:basis.Text = [string]$words.timing.basis
        if ($words.timing.confidence) { $script:basis.Text += ' (' + [string]$words.timing.confidence + ')' }
        $script:basis.Visibility = if ($words.timing.basis -or $words.timing.confidence) { 'Visible' } else { 'Collapsed' }
        $script:button.Content = $words.ack_label
    }
    $script:currentLanguage = if ($script:currentLanguage -eq 'zh-CN') { 'zh-CN' } else { 'en' }
    & $script:updateLanguage
    $script:languageSelector.Add_SelectionChanged({
        if ($script:languageSelector.SelectedIndex -lt 0) { return }
        $script:currentLanguage = if ($script:languageSelector.SelectedIndex -eq 0) { 'zh-CN' } else { 'en' }
        & $script:updateLanguage
        $script:saveError.Visibility = 'Collapsed'
        try { Save-Language $script:currentLanguage }
        catch { $script:saveError.Text = '无法保存语言选择 / Could not save language preference.'; $script:saveError.Visibility = 'Visible' }
    })
    $script:button.Add_Click({ Write-Receipt 'acknowledged'; $script:alertAcknowledged = $true; $script:window.Close() })
    $layout = [Windows.Controls.Grid]::new()
    $layout.RowDefinitions.Add([Windows.Controls.RowDefinition]::new())
    $footerRow = [Windows.Controls.RowDefinition]::new(); $footerRow.Height = [Windows.GridLength]::new(64); $layout.RowDefinitions.Add($footerRow)
    $scroll = [Windows.Controls.ScrollViewer]::new(); $scroll.VerticalScrollBarVisibility = 'Auto'; $scroll.HorizontalScrollBarVisibility = 'Disabled'; $scroll.Content = $panel
    [Windows.Controls.Grid]::SetRow($scroll, 0); $layout.Children.Add($scroll) | Out-Null
    $footer = [Windows.Controls.Border]::new(); $footer.Padding = [Windows.Thickness]::new(24, 8, 24, 16); $footer.Background = [Windows.Media.Brushes]::White
    $footer.Child = $script:button; [Windows.Controls.Grid]::SetRow($footer, 1); $layout.Children.Add($footer) | Out-Null
    $script:window.Content = $layout
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
