# ARGUS - ship a release to the EC2 instance created by provision.ps1.
#   1. package the repo (no data, cache, venv or secrets)   2. upload release + REPH data to the private S3 bucket
#   3. SSM Run Command: pull, install, (precompute), switch, restart, smoke-test   4. wait and print the output
# Usage:  powershell -ExecutionPolicy Bypass -File deploy\aws\deploy.ps1 [-Precompute auto|always|never] [-SkipData] [-Prewarm]
param(
    [ValidateSet("auto", "always", "never")][string]$Precompute = "auto",
    [switch]$SkipData,
    [switch]$Prewarm,
    [string]$DataDir = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "..\center_data")
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$state = Get-Content (Join-Path $PSScriptRoot ".state.json") | ConvertFrom-Json
$region = $state.region; $bucket = $state.bucket; $iid = $state.instanceId
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$dist = Join-Path $repo "dist"; New-Item -ItemType Directory -Force -Path $dist | Out-Null
$tarball = Join-Path $dist "argus-$ts.tar.gz"

function Invoke-AwsCli { $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"; $o = & aws.exe @args --region $region 2>&1; $c = $LASTEXITCODE; $ErrorActionPreference = $prev
    if ($c -ne 0) { throw "aws $($args -join ' ') failed: $($o | Out-String)" }; return $o }

Write-Host "== package $tarball"
Push-Location $repo
tar -czf $tarball --exclude=.venv --exclude=cache --exclude=data --exclude=dist --exclude=.git --exclude=__pycache__ `
    --exclude=.pytest_cache --exclude="*.db" --exclude="*.db-wal" --exclude="*.db-shm" --exclude=.env --exclude="deploy/aws/.state.json" .
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "tar failed" }

if (-not $SkipData) {
    $d = (Resolve-Path $DataDir).Path
    Write-Host "== upload REPH data from $d (parquet + 2 raw finance files)"
    Invoke-AwsCli s3 sync "$d\D_risk" "s3://$bucket/data/D_risk/" --exclude "*" --include "*.parquet" --only-show-errors | Out-Null
    Invoke-AwsCli s3 cp "$d\raw\suppliers_raw.csv" "s3://$bucket/data/raw/suppliers_raw.csv" --only-show-errors | Out-Null
    Invoke-AwsCli s3 cp "$d\raw\invoices_raw.csv" "s3://$bucket/data/raw/invoices_raw.csv" --only-show-errors | Out-Null
}
Write-Host "== upload release"
Invoke-AwsCli s3 cp $tarball "s3://$bucket/releases/argus-$ts.tar.gz" --only-show-errors | Out-Null

$new = "/opt/argus/app.new-$ts"
$cmds = @(
    "set -euo pipefail",
    "aws s3 cp s3://$bucket/releases/argus-$ts.tar.gz /opt/argus/releases/ --only-show-errors",
    "mkdir -p $new && tar -xzf /opt/argus/releases/argus-$ts.tar.gz -C $new",
    "sed -i 's/\r$//' $new/deploy/aws/remote_deploy.sh",
    "bash $new/deploy/aws/remote_deploy.sh $bucket $new $Precompute"
)
if ($Prewarm) {
    $cmds += "cd /opt/argus/app && sudo -u argus env `$(grep -v '^#' /opt/argus/argus.env | xargs) /opt/argus/venv/bin/python -m scripts.prewarm"
}
$params = @{ commands = $cmds; executionTimeout = @("3000") } | ConvertTo-Json -Compress
$pfile = Join-Path $env:TEMP "argus-ssm-$ts.json"
[IO.File]::WriteAllText($pfile, $params, (New-Object Text.UTF8Encoding($false)))
Write-Host "== SSM Run Command on $iid (precompute=$Precompute)"
$cid = (Invoke-AwsCli ssm send-command --instance-ids $iid --document-name AWS-RunShellScript --comment "ARGUS release $ts" `
        --parameters "file://$pfile" --timeout-seconds 600 --query "Command.CommandId" --output text | Out-String).Trim()
Write-Host "   command $cid"
do {
    Start-Sleep -Seconds 10
    $inv = (Invoke-AwsCli ssm get-command-invocation --command-id $cid --instance-id $iid --output json | Out-String) | ConvertFrom-Json
    Write-Host "   $($inv.Status) ..."
} while ($inv.Status -in @("Pending", "InProgress", "Delayed"))
Write-Host "`n----- stdout -----`n$($inv.StandardOutputContent)"
if ($inv.StandardErrorContent) { Write-Host "----- stderr (tail) -----`n$(($inv.StandardErrorContent -split "`n" | Select-Object -Last 25) -join "`n")" }
Write-Host "`n== $($inv.Status): $($state.url)"
if ($inv.Status -ne "Success") { exit 1 }
