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

function Invoke-MishLabPython {
    param([string[]]$Arguments)
    $entry = Join-Path $repoRoot 'mish_lab.py'
    if ($python.Name -eq 'py.exe' -or $python.Name -eq 'py') {
        & $python.Source -3 $entry @Arguments | Out-Host
    } else {
        & $python.Source $entry @Arguments | Out-Host
    }
    $code = $LASTEXITCODE
    return $code
}

if ($ArgsRest.Count -gt 0 -and $ArgsRest[0] -eq 'go') {
    & git -C $repoRoot pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $code = Invoke-MishLabPython @('doctor')
    if ($code -ne 0) { exit $code }

    $code = Invoke-MishLabPython @('next')
    if ($code -ne 0) { exit $code }

    $labRoot = if ($env:MISH_LAB_ROOT) { $env:MISH_LAB_ROOT } else { 'C:\mish-lab' }
    $currentPath = Join-Path $labRoot 'current.json'
    $current = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json

    if ($current.execution -eq 'ready_probe') {
        $code = Invoke-MishLabPython @('run')
        if ($code -ne 0) { exit $code }
        $code = Invoke-MishLabPython @('submit')
        exit $code
    }

    $null = Invoke-MishLabPython @('status')
    Write-Host 'MISH_LAB_GO=WORKSPACE_READY'
    Write-Host "EXECUTION=$($current.execution)"
    Write-Host "WORKSPACE=$($current.workspace)"
    exit 0
}

exit (Invoke-MishLabPython $ArgsRest)
