param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsRest
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
    throw 'Python 3 is required. Install Python or place it on PATH.'
}

function Invoke-MishPythonEntry {
    param([string]$Entry, [string[]]$Arguments)
    if ($python.Name -eq 'py.exe' -or $python.Name -eq 'py') {
        & $python.Source -3 $Entry @Arguments | Out-Host
    } else {
        & $python.Source $Entry @Arguments | Out-Host
    }
    $code = $LASTEXITCODE
    return $code
}

function Invoke-MishLabPython {
    param([string[]]$Arguments)
    $entry = Join-Path $repoRoot 'mish_lab.py'
    return Invoke-MishPythonEntry -Entry $entry -Arguments $Arguments
}

function Invoke-MishProductPhysicalE3 {
    param([string[]]$Arguments)
    $entry = Join-Path $repoRoot 'product_physical_e3.py'
    return Invoke-MishPythonEntry -Entry $entry -Arguments $Arguments
}

function Resolve-MishLabAdb {
    if ($env:MISH_LAB_ADB -and (Test-Path -LiteralPath $env:MISH_LAB_ADB -PathType Leaf)) {
        return $env:MISH_LAB_ADB
    }

    $managed = 'C:\mish-lab\tools\android-sdk\platform-tools\adb.exe'
    if (Test-Path -LiteralPath $managed -PathType Leaf) {
        return $managed
    }

    $command = Get-Command adb -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw 'ADB is unavailable after doctor passed.'
}

function Install-MishExactProduct {
    param($Current, $Task)

    if ($Task.install_product -ne $true) {
        return $false
    }
    if (-not $Current.product_apk) {
        throw 'install_product=true requires an exact verified product APK in the task.'
    }
    if (-not (Test-Path -LiteralPath $Current.product_apk -PathType Leaf)) {
        throw "Verified product APK is missing: $($Current.product_apk)"
    }

    $adb = Resolve-MishLabAdb
    & $adb install -r $Current.product_apk | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw 'Exact PRODUCT APK install/update failed. No uninstall or signature-bypass fallback is allowed.'
    }

    & $adb shell pm path com.mobileproxymish.app | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw 'PRODUCT package verification failed after install.'
    }

    Write-Host 'MISH_LAB_PRODUCT_INSTALL=PASS'
    Write-Host 'PRODUCT_PACKAGE=com.mobileproxymish.app'
    Write-Host "PRODUCT_APK_SHA256=$($Current.product_apk_sha256)"
    return $true
}

function Start-MishExactProduct {
    $adb = Resolve-MishLabAdb
    & $adb shell am start -W -n 'com.mobileproxymish.app/.MainActivity' | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw 'PRODUCT package is installed but its launcher activity did not start.'
    }
    Write-Host 'MISH_LAB_PRODUCT_LAUNCH=PASS'
}

if ($ArgsRest.Count -gt 0 -and $ArgsRest[0] -eq 'go') {
    & git -C $repoRoot pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $code = Invoke-MishLabPython @('doctor')
    if ($code -ne 0) { exit $code }

    # Formal PRODUCT E3/E4 is owned by iamaman11/mobile-proxy-mish and consumes
    # one immutable PRODUCT RC. This LAB launcher no longer polls Issue #11,
    # builds PRODUCT, or creates a second physical-acceptance control path.
    $code = Invoke-MishLabPython @('next')
    if ($code -ne 0) { exit $code }

    $labRoot = if ($env:MISH_LAB_ROOT) { $env:MISH_LAB_ROOT } else { 'C:\mish-lab' }
    $currentPath = Join-Path $labRoot 'current.json'
    $current = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
    $taskPath = Join-Path $current.workspace 'task.json'
    $task = Get-Content -LiteralPath $taskPath -Raw | ConvertFrom-Json

    $productInstalled = Install-MishExactProduct -Current $current -Task $task

    if ($current.execution -eq 'ready_probe') {
        $code = Invoke-MishLabPython @('run')
        if ($code -ne 0) { exit $code }

        if ($productInstalled) {
            Start-MishExactProduct
        }

        $code = Invoke-MishLabPython @('submit')
        exit $code
    }

    # Historical per-task E3 remains executable only for already-issued legacy
    # diagnostic tasks. It is not formal PRODUCT E3 and cannot promote evidence.
    if ($current.execution -eq 'product_physical_e3') {
        $code = Invoke-MishProductPhysicalE3 @('execute')
        if ($code -ne 0) { exit $code }

        $code = Invoke-MishLabPython @('submit')
        exit $code
    }

    if ($productInstalled) {
        Start-MishExactProduct
    }

    $null = Invoke-MishLabPython @('status')
    Write-Host 'MISH_LAB_GO=WORKSPACE_READY'
    Write-Host "EXECUTION=$($current.execution)"
    Write-Host "WORKSPACE=$($current.workspace)"
    exit 0
}

exit (Invoke-MishLabPython $ArgsRest)
