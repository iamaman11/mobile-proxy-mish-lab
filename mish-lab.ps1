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

$entry = Join-Path $repoRoot 'mish_lab.py'
if ($python.Name -eq 'py.exe' -or $python.Name -eq 'py') {
    & $python.Source -3 $entry @ArgsRest
} else {
    & $python.Source $entry @ArgsRest
}
exit $LASTEXITCODE
