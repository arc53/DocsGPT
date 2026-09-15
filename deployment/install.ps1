# DocsGPT installer for Windows.
#
#   irm https://docs.ac/install.ps1 | iex
#
# Installs uv when it is missing or too old, installs the docsgpt Python
# package with it, then runs `docsgpt up`, which sets up DocsGPT on Docker
# Desktop and starts it. Running it again upgrades the package and keeps your
# settings. To pass options to `docsgpt up`:
#
#   & ([scriptblock]::Create((irm https://docs.ac/install.ps1))) --domain docs.example.com --yes
#
# Environment:
#   DOCSGPT_VERSION         package version to install (default: the latest release)
#   DOCSGPT_PACKAGE         install this instead of docsgpt from PyPI (a wheel path or URL)
#   DOCSGPT_NO_MODIFY_PATH  set to 1 to leave PATH alone
#
# Everything runs inside a function, so a download cut short runs nothing, and
# nothing calls `exit`, which would close the window `iex` runs in.

function Install-DocsGPT {
    param([string[]]$UpArguments)

    $ErrorActionPreference = 'Stop'
    $UvVersion = '0.12.15'
    $UvMinVersion = [version]'0.8.0'
    # sha256 of https://astral.sh/uv/$UvVersion/install.ps1, checked before it runs. Bump it with
    # $UvVersion: (Invoke-WebRequest "https://astral.sh/uv/<version>/install.ps1").Content | …
    $UvInstallerSha256 = '63f2d7e2ccc347cc018127b22f56f569080e5730a390dcb702b654daf6822193'

    function Say([string]$Message) { Write-Host "==> $Message" }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'DocsGPT runs on Docker. Install Docker Desktop (https://docs.docker.com/desktop/setup/install/windows-install/), start it, and run this again.'
    }

    # uv installs and upgrades the package, and brings Python 3.12 when the system has none.
    $uv = $null
    $candidates = @(
        (Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        (Join-Path $HOME '.local\bin\uv.exe'),
        (Join-Path $HOME '.cargo\bin\uv.exe')
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($candidate in $candidates) {
        $found = "$(& $candidate --version 2>$null)" -replace '^uv\s+([0-9.]+).*$', '$1'
        if ($found -match '^\d+\.\d+(\.\d+)?$' -and [version]$found -ge $UvMinVersion) {
            $uv = $candidate
            break
        }
    }
    if (-not $uv) {
        $uvDir = Join-Path $HOME '.local\bin'
        Say "Installing uv $UvVersion into $uvDir"
        $env:UV_INSTALL_DIR = $uvDir
        $env:UV_NO_MODIFY_PATH = '1'
        $env:UV_PRINT_QUIET = '1'
        # Downloaded and checked before it runs, and run in a child PowerShell so nothing the
        # uv installer does can end this session.
        $installer = Join-Path ([System.IO.Path]::GetTempPath()) "uv-installer-$UvVersion.ps1"
        try {
            Invoke-WebRequest -Uri "https://astral.sh/uv/$UvVersion/install.ps1" -OutFile $installer -UseBasicParsing
            $actual = (Get-FileHash -Path $installer -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $UvInstallerSha256) {
                throw "The uv installer does not match its pinned sha256: got $actual, expected $UvInstallerSha256. Refusing to run it."
            }
            $shell = (Get-Process -Id $PID).Path
            & $shell -NoProfile -ExecutionPolicy Bypass -File $installer
        } finally {
            Remove-Item $installer -Force -ErrorAction SilentlyContinue
        }
        $uv = Join-Path $uvDir 'uv.exe'
        if (-not (Test-Path $uv)) { throw "uv did not install into $uvDir" }
    }

    if ($env:DOCSGPT_VERSION -and $env:DOCSGPT_PACKAGE) {
        throw 'Set DOCSGPT_VERSION or DOCSGPT_PACKAGE, not both.'
    }
    if ($env:DOCSGPT_PACKAGE) {
        Say 'Installing docsgpt from DOCSGPT_PACKAGE'
        & $uv tool install --reinstall --python 3.12 $env:DOCSGPT_PACKAGE
    } elseif ($env:DOCSGPT_VERSION) {
        Say "Installing docsgpt $env:DOCSGPT_VERSION"
        & $uv tool install --force --python 3.12 "docsgpt==$env:DOCSGPT_VERSION"
    } else {
        Say 'Installing the latest docsgpt'
        & $uv tool install --upgrade --python 3.12 docsgpt
    }
    if ($LASTEXITCODE -ne 0) { throw 'Installing the docsgpt package failed.' }

    $binDir = "$(& $uv tool dir --bin)".Trim()
    $docsgpt = Join-Path $binDir 'docsgpt.exe'
    if (-not (Test-Path $docsgpt)) { throw "The docsgpt command is missing from $binDir." }
    if (($env:Path -split ';') -notcontains $binDir) {
        if ($env:DOCSGPT_NO_MODIFY_PATH -eq '1') {
            Say "Add $binDir to PATH to run docsgpt from a new terminal"
        } else {
            & $uv tool update-shell *> $null
            Say "Added $binDir to PATH for new terminals"
        }
        $env:Path = "$binDir;$env:Path"
    }

    & $docsgpt up @UpArguments
    if ($LASTEXITCODE -ne 0) {
        # throw, not Write-Error: the caller (and any automation) must see this fail.
        throw "docsgpt up exited with code $LASTEXITCODE. Fix the problem above and run it again: docsgpt up"
    }
}

Install-DocsGPT -UpArguments $args
