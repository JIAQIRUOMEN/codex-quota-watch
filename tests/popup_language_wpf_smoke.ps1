param([string]$TestDirectory = '')
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($TestDirectory)) {
    $TestDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'work\popup-language-wpf-smoke'
}
$testRoot = [IO.Path]::GetFullPath($TestDirectory)
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$runRoot = Join-Path $testRoot ('run-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($runRoot) | Out-Null
$stateDirectory = Join-Path $runRoot 'state'
$receiptDirectory = Join-Path $stateDirectory 'receipts'
[IO.Directory]::CreateDirectory($receiptDirectory) | Out-Null
$resultPath = Join-Path $runRoot 'component-result.json'
$runnerPath = Join-Path $runRoot 'renderer-under-test.ps1'
$rendererPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'windows\Show-CodexQuotaAlert.ps1'

function Assert-Smoke([bool]$condition, [string]$message) {
    if (-not $condition) { throw $message }
}

function New-SmokeEvent([string]$eventId, [string]$nonce) {
    $timingZh = [ordered]@{
        kind = 'unknown'; published_text = '原帖时间：2026-10-27 12:00 UTC+08:00 (北京时间)'
        text = '合成测试时间；不表示真实提醒。'; basis = '合成测试依据'; confidence = '未确认'
    }
    $timingEn = [ordered]@{
        kind = 'unknown'; published_text = 'Original post time: 2026-10-27 12:00 UTC+08:00 (Beijing time)'
        text = 'Synthetic test timing; not a real alert.'; basis = 'Synthetic test basis'; confidence = 'Unconfirmed'
    }
    return [ordered]@{
        id = $eventId; receipt_nonce = $nonce; title = '合成测试标题'; message = '合成测试正文'
        ack_label = '已知晓'; url = 'https://x.com/thsottiaux/status/123456789'
        timing = $timingZh
        translations = [ordered]@{
            'zh-CN' = [ordered]@{ title = '合成测试标题'; message = '中文正文'; ack_label = '已知晓'; timing = $timingZh }
            en = [ordered]@{ title = 'Synthetic test title'; message = 'English body'; ack_label = 'Acknowledge'; timing = $timingEn }
        }
    }
}

function Invoke-RendererCheck([string]$eventId, [string]$nonce, [string]$passName, [string]$expectedReceiptStatus) {
    $eventPath = Join-Path $runRoot ($eventId + '.json')
    $event = New-SmokeEvent $eventId $nonce
    [IO.File]::WriteAllText($eventPath, ($event | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))

    $source = [IO.File]::ReadAllText($rendererPath, [Text.Encoding]::UTF8)
    $marker = '    $script:window.ShowDialog() | Out-Null'
    if ([regex]::Matches($source, [regex]::Escape($marker)).Count -ne 1) {
        throw 'Could not find the unique pre-ShowDialog injection point in the production renderer.'
    }
    $hook = @'
    $script:popupLanguageSmokeFailure = $null
    $script:window.Add_ContentRendered({
        try {
            if ($eventData.id -eq 'popup-language-smoke-one') {
                $script:languageSelector.SelectedIndex = 0
                Assert-Smoke ($script:window.Title -ceq $eventData.translations.'zh-CN'.title) 'Chinese title did not update.'
                Assert-Smoke ($script:heading.Text -ceq $eventData.translations.'zh-CN'.title) 'Chinese heading did not update.'
                Assert-Smoke ($script:body.Text -ceq $eventData.translations.'zh-CN'.message) 'Chinese body did not update.'
                Assert-Smoke ($script:timeBox.Text -ceq ($eventData.translations.'zh-CN'.timing.published_text + "`n" + $eventData.translations.'zh-CN'.timing.text)) 'Chinese timing did not update.'
                Assert-Smoke ($script:basis.Text -ceq ($eventData.translations.'zh-CN'.timing.basis + ' (' + $eventData.translations.'zh-CN'.timing.confidence + ')')) 'Chinese basis did not update.'
                Assert-Smoke ($script:button.Content -ceq $eventData.translations.'zh-CN'.ack_label) 'Chinese ack button did not update.'

                $script:languageSelector.SelectedIndex = 1
                Assert-Smoke ($script:window.Title -ceq $eventData.translations.en.title) 'English title did not update.'
                Assert-Smoke ($script:heading.Text -ceq $eventData.translations.en.title) 'English heading did not update.'
                Assert-Smoke ($script:body.Text -ceq $eventData.translations.en.message) 'English body did not update.'
                Assert-Smoke ($script:timeBox.Text -ceq ($eventData.translations.en.timing.published_text + "`n" + $eventData.translations.en.timing.text)) 'English timing did not update.'
                Assert-Smoke ($script:basis.Text -ceq ($eventData.translations.en.timing.basis + ' (' + $eventData.translations.en.timing.confidence + ')')) 'English basis did not update.'
                Assert-Smoke ($script:button.Content -ceq $eventData.translations.en.ack_label) 'English ack button did not update.'

                $savedLanguage = [IO.File]::ReadAllText($languagePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
                Assert-Smoke ($savedLanguage.language -ceq 'en') 'English preference was not persisted.'
                $receiptNow = [IO.File]::ReadAllText($receiptPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
                Assert-Smoke ($receiptNow.event_id -ceq $eventData.id -and $receiptNow.receipt_nonce -ceq $eventData.receipt_nonce -and $receiptNow.status -ceq 'displayed') 'Language switching changed or failed to preserve the displayed receipt.'
            } elseif ($eventData.id -eq 'popup-language-smoke-two') {
                Assert-Smoke ($script:currentLanguage -ceq 'en' -and $script:languageSelector.SelectedIndex -eq 1) 'Second event did not load the saved English preference.'
                Assert-Smoke ($script:window.Title -ceq $eventData.translations.en.title -and $script:body.Text -ceq $eventData.translations.en.message) 'Second event did not render the saved English language.'
                Assert-Smoke ($script:timeBox.Text -ceq ($eventData.translations.en.timing.published_text + "`n" + $eventData.translations.en.timing.text)) 'Second event timing did not use the saved language.'
            } elseif ($eventData.id -eq 'popup-language-smoke-three') {
                Assert-Smoke ($script:currentLanguage -ceq 'en' -and $script:button.Content -ceq $eventData.translations.en.ack_label) 'Acknowledgment event did not render in English.'
                $receiptNow = [IO.File]::ReadAllText($receiptPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
                Assert-Smoke ($receiptNow.event_id -ceq $eventData.id -and $receiptNow.receipt_nonce -ceq $eventData.receipt_nonce -and $receiptNow.status -ceq 'displayed') 'Acknowledgment event was not displayed with its original identity before click.'
                $script:button.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Primitives.ButtonBase]::ClickEvent))
                Assert-Smoke (-not $script:window.IsVisible) 'Real acknowledgment click handler did not close the test window.'
            } elseif ($eventData.id -eq 'popup-language-smoke-four') {
                $receiptNow = [IO.File]::ReadAllText($receiptPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
                Assert-Smoke ($receiptNow.event_id -ceq $eventData.id -and $receiptNow.receipt_nonce -ceq $eventData.receipt_nonce -and $receiptNow.status -ceq 'displayed') 'Dismissal event was not displayed with its original identity before close.'
                $script:window.Close()
            }
        } catch {
            $script:popupLanguageSmokeFailure = $_.Exception.Message
        } finally {
            if ($eventData.id -in @('popup-language-smoke-one', 'popup-language-smoke-two') -or $script:popupLanguageSmokeFailure) {
                $script:testClosed = $true
                if ($script:window.IsVisible) { $script:window.Close() }
            }
        }
    })
    $script:popupLanguageSmokeTimer = [Windows.Threading.DispatcherTimer]::new()
    $script:popupLanguageSmokeTimer.Interval = [TimeSpan]::FromSeconds(20)
    $script:popupLanguageSmokeTimer.Add_Tick({
        $script:popupLanguageSmokeTimer.Stop()
        $script:popupLanguageSmokeFailure = 'Timed out waiting for the WPF component to render.'
        $script:testClosed = $true
        $script:window.Close()
    })
    $script:popupLanguageSmokeTimer.Start()
    $script:window.Add_Closed({ $script:popupLanguageSmokeTimer.Stop() })
'@
    $source = $source.Replace($marker, $hook + [Environment]::NewLine + $marker)
    $source += @'

$smokeSummary = [ordered]@{ pass = $env:CODEX_QUOTA_WATCH_WPF_SMOKE_PASS; success = [string]::IsNullOrEmpty($script:popupLanguageSmokeFailure); failure = $script:popupLanguageSmokeFailure }
[IO.File]::WriteAllText($env:CODEX_QUOTA_WATCH_WPF_SMOKE_RESULT, ($smokeSummary | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
'@
    [IO.File]::WriteAllText($runnerPath, $source, [Text.UTF8Encoding]::new($true))
    $env:CODEX_QUOTA_WATCH_WPF_SMOKE_PASS = $passName
    $env:CODEX_QUOTA_WATCH_WPF_SMOKE_RESULT = $resultPath
    $null = & $runnerPath -EventPath $eventPath -ReceiptDirectory $receiptDirectory
    $componentResult = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Smoke $componentResult.success $componentResult.failure
    $receiptPath = Join-Path $receiptDirectory ($eventId + '.json')
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Smoke ($receipt.event_id -ceq $eventId -and $receipt.receipt_nonce -ceq $nonce -and $receipt.status -ceq $expectedReceiptStatus) "Final receipt expected $expectedReceiptStatus with the original event identity."
    return [ordered]@{ pass = $passName; status = $receipt.status; event_id = $eventId }
}

$oldPass = $env:CODEX_QUOTA_WATCH_WPF_SMOKE_PASS
$oldResult = $env:CODEX_QUOTA_WATCH_WPF_SMOKE_RESULT
try {
    Add-Type -AssemblyName PresentationFramework
    [IO.File]::WriteAllText((Join-Path $stateDirectory 'popup-language.json'), '{"language":"en"}', [Text.UTF8Encoding]::new($false))
    $first = Invoke-RendererCheck 'popup-language-smoke-one' '11111111111111111111111111111111' 'toggle-and-persist' 'test_closed'
    $second = Invoke-RendererCheck 'popup-language-smoke-two' '22222222222222222222222222222222' 'reload-saved-language' 'test_closed'
    $third = Invoke-RendererCheck 'popup-language-smoke-three' '33333333333333333333333333333333' 'click-acknowledge' 'acknowledged'
    $fourth = Invoke-RendererCheck 'popup-language-smoke-four' '44444444444444444444444444444444' 'dismiss-without-acknowledgment' 'dismissed_unacknowledged'
    [ordered]@{ success = $true; checks = @($first, $second, $third, $fourth); test_directory = $runRoot } | ConvertTo-Json -Depth 5 -Compress | Write-Output
    exit 0
} catch {
    [ordered]@{ success = $false; error = $_.Exception.Message; test_directory = $runRoot } | ConvertTo-Json -Depth 5 -Compress | Write-Output
    exit 1
} finally {
    $env:CODEX_QUOTA_WATCH_WPF_SMOKE_PASS = $oldPass
    $env:CODEX_QUOTA_WATCH_WPF_SMOKE_RESULT = $oldResult
}
