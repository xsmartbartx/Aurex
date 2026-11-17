<#
.SYNOPSIS
    Restores an AUREX database dump. Stops the application services first and re-applies security policies.
.EXAMPLE
    ./scripts/Restore-AurexDatabase.ps1 -Path ./backups/aurex-20261115-020000Z.dump -Confirm
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)] [string] $Path,
    [string] $ComposeProject = 'aurex',
    [string] $DatabaseUser = $(if ($env:AUREX_DB_USER) { $env:AUREX_DB_USER } else { 'aurex' }),
    [string] $DatabaseName = $(if ($env:AUREX_DB_NAME) { $env:AUREX_DB_NAME } else { 'aurex' })
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-AurexDump {
    param([string] $File)
    if (-not (Test-Path $File -PathType Leaf)) { return $false }
    $header = [System.IO.File]::ReadAllBytes((Resolve-Path $File))[0..4]
    return ([System.Text.Encoding]::ASCII.GetString($header) -eq 'PGDMP')
}

if ($MyInvocation.InvocationName -ne '.') {
    if (-not (Test-AurexDump -File $Path)) { throw "Not a PostgreSQL custom-format dump: $Path" }
    if ($PSCmdlet.ShouldProcess($DatabaseName, "Replace the database with $Path")) {
        docker compose -p $ComposeProject stop api worker web
        Get-Content -Path $Path -AsByteStream -Raw |
            docker compose -p $ComposeProject exec -T db pg_restore -U $DatabaseUser -d $DatabaseName --clean --if-exists --no-owner
        if ($LASTEXITCODE -gt 1) { throw "pg_restore failed with exit code $LASTEXITCODE" }
        docker compose -p $ComposeProject --profile app run --rm migrate
        docker compose -p $ComposeProject --profile app up -d api worker web
        Write-Output "Restored $Path and re-applied migrations and security policies."
    }
}
