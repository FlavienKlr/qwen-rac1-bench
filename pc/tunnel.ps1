# The tunnel on Windows: the PC dials the VM and exposes the log proxy (8081)
# as 127.0.0.1:8080 inside the VM. Reconnects if it drops during a long run.
#   powershell -File pc\tunnel.ps1 -Jump user@jumphost -Vm 10.0.0.10
param(
    [Parameter(Mandatory = $true)][string]$Jump,
    [Parameter(Mandatory = $true)][string]$Vm
)
while ($true) {
    ssh -N `
        -o ForwardAgent=no -o ForwardX11=no `
        -o ExitOnForwardFailure=yes `
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
        -J $Jump `
        -R 127.0.0.1:8080:127.0.0.1:8081 `
        $Vm
    Write-Host "$(Get-Date -Format s) tunnel closed, reconnecting in 5 s"
    Start-Sleep -Seconds 5
}
