$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$gcc = 'D:\SDK\2019.1\gnu\aarch32\nt\gcc-arm-linux-gnueabi\bin\arm-linux-gnueabihf-gcc.exe'
if (-not (Test-Path -LiteralPath $gcc)) { throw "ARM Linux compiler missing: $gcc" }
& $gcc -std=c11 -O2 -Wall -Wextra -Werror -fPIC -shared (Join-Path $root 'ps/mmio.c') -o (Join-Path $root 'ps/libgesture_mmio.so')
if ($LASTEXITCODE -ne 0) { throw 'ARM helper compile failed' }
