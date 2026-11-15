BeforeAll {
    . "$PSScriptRoot/../../scripts/Backup-AurexDatabase.ps1"
    . "$PSScriptRoot/../../scripts/Restore-AurexDatabase.ps1" -Path 'unused'
}

Describe 'Backup naming' {
    It 'uses a sortable UTC timestamp' {
        Get-AurexBackupName -At ([datetime]'2026-11-15T02:03:04Z').ToUniversalTime() | Should -Be 'aurex-20261115-020304Z.dump'
    }
}

Describe 'Retention' {
    It 'removes only expired AUREX dumps' {
        $dir = Join-Path $TestDrive 'backups'
        New-Item -ItemType Directory -Path $dir | Out-Null
        $old = New-Item -Path (Join-Path $dir 'aurex-20200101-000000Z.dump') -Value 'x'
        $new = New-Item -Path (Join-Path $dir 'aurex-20991231-000000Z.dump') -Value 'x'
        $other = New-Item -Path (Join-Path $dir 'notes.txt') -Value 'x'
        (Get-Item $old).LastWriteTimeUtc = (Get-Date).ToUniversalTime().AddDays(-30)
        Remove-AurexOldBackups -Path $dir -Days 14
        Test-Path $old | Should -BeFalse
        Test-Path $new | Should -BeTrue
        Test-Path $other | Should -BeTrue
    }
}

Describe 'Restore guard' {
    It 'rejects files that are not PostgreSQL dumps' {
        $file = New-Item -Path (Join-Path $TestDrive 'fake.dump') -Value 'not a dump'
        Test-AurexDump -File $file | Should -BeFalse
    }
    It 'accepts the custom-format signature' {
        $file = Join-Path $TestDrive 'real.dump'
        [System.IO.File]::WriteAllBytes($file, [byte[]](0x50, 0x47, 0x44, 0x4D, 0x50, 0x01))
        Test-AurexDump -File $file | Should -BeTrue
    }
}
