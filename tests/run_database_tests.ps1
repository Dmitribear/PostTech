$ErrorActionPreference = 'Stop'
$databaseTestContainer = 'posttech-db-tests-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$databaseTestImage = 'postgres:16-alpine'
$databaseFiles = (Resolve-Path (Join-Path $PSScriptRoot '../database')).Path
$createdContainerId = $null

function Invoke-DatabaseSqlFile([string]$Database, [string]$File) {
    & docker exec $createdContainerId psql -X -q -U postgres -d $Database -v ON_ERROR_STOP=1 -f $File
    if ($LASTEXITCODE -ne 0) { throw "SQL check failed: $Database / $File" }
}

function Get-WorkflowCounts([string]$Database) {
    $counts = & docker exec $createdContainerId psql -X -t -A -U postgres -d $Database -v ON_ERROR_STOP=1 -c 'select (select count(*) from hr_request_events), (select count(*) from notifications);'
    if ($LASTEXITCODE -ne 0) { throw 'Could not read workflow counts' }
    return ($counts -join '').Trim()
}

try {
    # No host ports, no external network, no persistent volume and no real secrets.
    $createdContainerId = & docker run --rm --detach --name $databaseTestContainer --network none --mount type=tmpfs,destination=/var/lib/postgresql/data -e POSTGRES_HOST_AUTH_METHOD=trust $databaseTestImage
    if ($LASTEXITCODE -ne 0) { throw 'Could not start disposable PostgreSQL' }
    $createdContainerId = ($createdContainerId -join '').Trim()

    $databaseReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & docker exec $createdContainerId pg_isready -U postgres *> $null
        if ($LASTEXITCODE -eq 0) { $databaseReady = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $databaseReady) { throw 'Disposable PostgreSQL did not become ready' }
    & docker cp $databaseFiles "${createdContainerId}:/tmp/database"
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy SQL fixtures' }

    foreach ($testDatabase in @('upgrade_case', 'fresh_case')) {
        & docker exec $createdContainerId createdb -U postgres $testDatabase
        if ($LASTEXITCODE -ne 0) { throw 'Could not create test database' }
        Invoke-DatabaseSqlFile $testDatabase '/tmp/database/tests/bootstrap.sql'
        Invoke-DatabaseSqlFile $testDatabase '/tmp/database/migrations/0001_digital_hr.sql'
        if ($testDatabase -eq 'upgrade_case') {
            Invoke-DatabaseSqlFile $testDatabase '/tmp/database/seed.sql'
        }
        Invoke-DatabaseSqlFile $testDatabase '/tmp/database/migrations/0002_atomic_workflows.sql'
        if ($testDatabase -eq 'fresh_case') {
            Invoke-DatabaseSqlFile $testDatabase '/tmp/database/seed.sql'
        }
        $countsBeforeReplay = Get-WorkflowCounts $testDatabase
        Invoke-DatabaseSqlFile $testDatabase '/tmp/database/migrations/0002_atomic_workflows.sql'
        if ((Get-WorkflowCounts $testDatabase) -ne $countsBeforeReplay) {
            throw 'Replaying migration duplicated history or notifications'
        }
        Invoke-DatabaseSqlFile $testDatabase '/tmp/database/seed.sql'
        if ((Get-WorkflowCounts $testDatabase) -ne $countsBeforeReplay) {
            throw 'Replaying seed duplicated history or notifications'
        }
        Invoke-DatabaseSqlFile $testDatabase '/tmp/database/tests/workflows.sql'
        Write-Output "$testDatabase passed (including migration and seed replay)"
    }
}
finally {
    # Only remove the container ID created by this invocation.
    if ($createdContainerId -match '^[0-9a-f]{64}$') {
        & docker rm --force --volumes $createdContainerId | Out-Null
    }
}
