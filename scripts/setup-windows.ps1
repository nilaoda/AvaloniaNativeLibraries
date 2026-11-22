$ErrorActionPreference = 'Stop'
$versions = Get-Content -Raw (Join-Path $PSScriptRoot '../config/versions.json') | ConvertFrom-Json
$llvmConfig = if ($env:RID -eq 'win-arm64') { $versions.llvm_arm64 } else { $versions.llvm }
$installer = Join-Path $env:RUNNER_TEMP 'llvm-installer.exe'
$llvmRoot = Join-Path $env:RUNNER_TEMP ('llvm-' + $llvmConfig.version)
Invoke-WebRequest -Uri $llvmConfig.windows_installer -OutFile $installer -MaximumRetryCount 5 -RetryIntervalSec 3
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $llvmConfig.sha256) {
    throw 'LLVM installer checksum does not match config/versions.json.'
}
$process = Start-Process -FilePath $installer -ArgumentList @('/S', "/D=$llvmRoot") -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "LLVM installation failed: $($process.ExitCode)" }
if (-not (Test-Path -LiteralPath (Join-Path $llvmRoot 'bin/clang-cl.exe'))) { throw 'clang-cl was not installed.' }
"LLVM_ROOT=$llvmRoot" >> $env:GITHUB_ENV
(Join-Path $llvmRoot 'bin') >> $env:GITHUB_PATH
