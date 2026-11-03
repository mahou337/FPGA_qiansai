param([string]$VivadoBin = '')
if (-not $VivadoBin) {
 if ($env:XILINX_VIVADO) { $VivadoBin=Join-Path $env:XILINX_VIVADO 'bin' }
 else { $VivadoBin=Split-Path (Get-Command xvlog.bat -ErrorAction Stop).Source -Parent }
}
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location (Join-Path $root 'sim')
& (Join-Path $VivadoBin 'xvlog.bat') --sv ../pl/mask_display_axi.v tb_mask_display.sv
if($LASTEXITCODE){throw 'xvlog failed'}
& (Join-Path $VivadoBin 'xelab.bat') tb_mask_display -s mask_sim
if($LASTEXITCODE){throw 'xelab failed'}
& (Join-Path $VivadoBin 'xsim.bat') mask_sim -tclbatch run.tcl -log simulation.log
if($LASTEXITCODE){throw 'xsim failed'}
if(-not (Select-String -Path simulation.log -SimpleMatch 'PASS mask display:')){throw 'simulation has no PASS marker'}
