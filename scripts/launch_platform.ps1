#requires -Version 5.1
<#
.SYNOPSIS
    V7.0.1 - Launch the V7 Streamlit platform locally (default) or on the
    LAN (with -Lan).

.DESCRIPTION
    Convenience wrapper around `python -m streamlit run
    apps/portfolio_platform.py`. Defaults to binding only to 127.0.0.1.

    The -Lan switch binds streamlit to 0.0.0.0 so a phone / tablet on the
    same Wi-Fi can reach the dashboard. -Lan is OPT-IN only and prints
    the security caveats from V7_0_1_LAUNCH_WORKFLOW.md before launching.

    This script does NOT fetch data, write CSVs, install packages,
    contact a broker, or touch IBKR. It is a thin convenience wrapper
    around the documented streamlit run command. LIVE_TRADING_ENABLED
    remains False at the project level (this script has no way to
    change it).

.PARAMETER Lan
    Bind streamlit to 0.0.0.0 (every network interface) instead of the
    default 127.0.0.1. Use only on a Wi-Fi network you trust and
    control. Prints the security caveats and requires an explicit
    keypress before launching.

.EXAMPLE
    .\scripts\launch_platform.ps1
    # Localhost-only. No security caveats apply.

.EXAMPLE
    .\scripts\launch_platform.ps1 -Lan
    # Trusted-Wi-Fi LAN mode. Prints caveats; requires keypress.
#>

param(
    [switch]$Lan
)

$ErrorActionPreference = 'Stop'

# Resolve the project root from this script's location so the relative
# path to apps/portfolio_platform.py is robust regardless of the working
# directory the operator launched from.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$AppPath = Join-Path $RepoRoot 'apps/portfolio_platform.py'

if (-not (Test-Path $AppPath)) {
    Write-Host "ERROR: Platform app not found at $AppPath" -ForegroundColor Red
    Write-Host "Run this script from the repository, not from a copy." -ForegroundColor Red
    exit 1
}

# Verify the python command exists. Friendly error if not.
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCmd) {
    Write-Host "ERROR: 'python' is not on PATH." -ForegroundColor Red
    Write-Host "Install Python 3.11+ and ensure it is on PATH, then try again." -ForegroundColor Red
    exit 1
}

if ($Lan) {
    Write-Host ""
    Write-Host "=== LAN MODE - SECURITY CAVEATS (read before continuing) ===" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Streamlit will bind to 0.0.0.0 so devices on the same Wi-Fi can reach the dashboard." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  * Use ONLY on a Wi-Fi network you trust and control." -ForegroundColor Yellow
    Write-Host "  * Do NOT use on public / cafe / hotel / airport / shared Wi-Fi." -ForegroundColor Yellow
    Write-Host "  * Anyone on the same LAN may be able to view this dashboard." -ForegroundColor Yellow
    Write-Host "  * Do NOT configure router port forwarding." -ForegroundColor Yellow
    Write-Host "  * Do NOT expose this to the public internet." -ForegroundColor Yellow
    Write-Host "  * No authentication is added in V7.0.1." -ForegroundColor Yellow
    Write-Host "  * The platform is read-only but data privacy still matters." -ForegroundColor Yellow
    Write-Host "  * Shut down with Ctrl+C when finished." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Find your PC LAN IP with: ipconfig" -ForegroundColor Cyan
    Write-Host "Phone URL will be: http://<PC-LAN-IP>:8501" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Full caveats: reports/research/V7_0_1_LAUNCH_WORKFLOW.md" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Press any key to continue (or Ctrl+C to abort)..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    $Address = '0.0.0.0'
    Write-Host ""
    Write-Host "Starting platform on LAN (0.0.0.0:8501) ..." -ForegroundColor Green
} else {
    $Address = '127.0.0.1'
    Write-Host "Starting platform on localhost (127.0.0.1:8501) ..." -ForegroundColor Green
    Write-Host "For LAN access (trusted Wi-Fi only), re-run with -Lan." -ForegroundColor Gray
}

Write-Host "Press Ctrl+C to shut down when finished." -ForegroundColor Gray
Write-Host ""

# Hand off to streamlit. The platform itself enforces every project
# guardrail (LIVE_TRADING_ENABLED stays False, no broker imports, no
# order execution). This script never touches those settings.
& python -m streamlit run $AppPath --server.address $Address
