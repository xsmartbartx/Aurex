<#
.SYNOPSIS
    Writes a compressed PostgreSQL dump of the AUREX database and prunes old dumps.
.EXAMPLE
    ./scripts/Backup-AurexDatabase.ps1 -Destination ./backups -RetentionDays 14
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $Destination = './backups',
    [ValidateRange(1, 3650)] [int] $RetentionDays = 14,
    [string] $ComposeProject = 'aurex',
    [string] $DatabaseUser = $(if ($env:AUREX_DB_USER) { $env:AUREX_DB_USER } else { 'aurex' }),
    [string] $DatabaseName = $(if ($env:AUREX_DB_NAME) { $env:AUREX_DB_NAME } else { 'aurex' })
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-AurexBackupName {
    param([datetime] $At = (Get-Date).ToUniversalTime())
    "aurex-$($At.ToString('yyyyMMdd-HHmmss'))Z.dump"
}

function Remove-AurexOldBackups {
    [CmdletBinding(SupportsShouldProcess)]
    param([string] $Path, [int] $Days)
    $cutoff = (Get-Date).ToUniversalTime().AddDays(-$Days)
    Get-ChildItem -Path $Path -Filter 'aurex-*.dump' -File |
        Where-Object { $_.LastWriteTimeUtc -lt $cutoff } |
        ForEach-Object { if ($PSCmdlet.ShouldProcess($_.FullName, 'Remove expired backup')) { Remove-Item $_.FullName } }
}

if ($MyInvocation.InvocationName -ne '.') {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $file = Join-Path $Destination (Get-AurexBackupName)
    if ($PSCmdlet.ShouldProcess($file, 'Write database dump')) {
        docker compose -p $ComposeProject exec -T db pg_dump -U $DatabaseUser -d $DatabaseName --format=custom --compress=9 |
            Set-Content -Path $file -AsByteStream
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
        if ((Get-Item $file).Length -lt 1024) { throw "The dump is suspiciously small: $file" }
        Write-Output "Backup written: $file"
    }
    Remove-AurexOldBackups -Path $Destination -Days $RetentionDays
}
