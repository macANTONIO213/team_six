# ARGUS - provision AWS hosting (idempotent). Windows PowerShell 5.1+ with AWS CLI v2.
# Creates (or reuses) everything tagged Project=ARGUS:
#   S3 bucket (private, TLS-only) for releases + data, IAM instance role/profile
#   (SSM + read bucket + Bedrock Claude AU profiles), security group (:8501),
#   Elastic IP, and one m7i.large Amazon Linux 2023 instance (IMDSv2, encrypted gp3).
# Usage:  powershell -ExecutionPolicy Bypass -File deploy\aws\provision.ps1
param(
    [string]$Region = "ap-southeast-2",
    [string]$InstanceType = "m7i.large",
    [string]$AllowedCidr = "0.0.0.0/0"   # judges must reach the app (NET-04); narrow to the venue IP if known
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$statePath = Join-Path $here ".state.json"
$tmp = Join-Path $env:TEMP "argus-provision"; New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function Invoke-Aws {
    # PS 5.1: native stderr + ErrorActionPreference=Stop throws, so relax it around the call
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $out = & aws @args --region $Region --output json 2>&1
    $code = $LASTEXITCODE; $ErrorActionPreference = $prev
    if ($code -ne 0) { throw "aws $($args -join ' ') failed:`n$($out | Out-String)" }
    $text = ($out | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | Out-String).Trim()
    if ($text) { return ($text | ConvertFrom-Json) }
}
function Test-Aws {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & aws @args --region $Region --output json 2>&1 | Out-Null
    $code = $LASTEXITCODE; $ErrorActionPreference = $prev
    return ($code -eq 0)
}
function Write-Utf8NoBom([string]$Path, [string]$Text) { [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false))) }

$account = (Invoke-Aws sts get-caller-identity).Account
$bucket = "argus-$account-$Region"
$roleName = "argus-ec2-role"; $profileName = "argus-ec2-profile"; $sgName = "argus-web-sg"
Write-Host "Account $account  Region $Region  Bucket $bucket"

# --- S3 bucket -------------------------------------------------------------
if (-not (Test-Aws s3api head-bucket --bucket $bucket)) {
    Invoke-Aws s3api create-bucket --bucket $bucket --create-bucket-configuration "LocationConstraint=$Region" | Out-Null
    Write-Host "Created bucket $bucket"
}
Invoke-Aws s3api put-public-access-block --bucket $bucket --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" | Out-Null
Write-Utf8NoBom "$tmp\enc.json" '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
Invoke-Aws s3api put-bucket-encryption --bucket $bucket --server-side-encryption-configuration "file://$tmp\enc.json" | Out-Null
Write-Utf8NoBom "$tmp\bucket-policy.json" (@'
{"Version":"2012-10-17","Statement":[{"Sid":"DenyInsecureTransport","Effect":"Deny","Principal":"*","Action":"s3:*",
"Resource":["arn:aws:s3:::__B__","arn:aws:s3:::__B__/*"],"Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}
'@ -replace '__B__', $bucket)
Invoke-Aws s3api put-bucket-policy --bucket $bucket --policy "file://$tmp\bucket-policy.json" | Out-Null
Invoke-Aws s3api put-bucket-tagging --bucket $bucket --tagging "TagSet=[{Key=Project,Value=ARGUS},{Key=Event,Value=REPH-AI-Summit-2026-Iloilo}]" | Out-Null

# --- IAM role + instance profile --------------------------------------------
if (-not (Test-Aws iam get-role --role-name $roleName)) {
    Invoke-Aws iam create-role --role-name $roleName --assume-role-policy-document "file://$here\ec2-trust-policy.json" --description "ARGUS EC2 runtime: SSM, read ARGUS bucket, invoke Claude (AU profiles)" --tags "Key=Project,Value=ARGUS" | Out-Null
    Write-Host "Created role $roleName"
}
Invoke-Aws iam attach-role-policy --role-name $roleName --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore | Out-Null
$policy = (Get-Content -Raw "$here\runtime-policy.template.json") -replace '__BUCKET__', $bucket -replace '__REGION__', $Region -replace '__ACCOUNT__', $account
Write-Utf8NoBom "$tmp\runtime-policy.json" $policy
Invoke-Aws iam put-role-policy --role-name $roleName --policy-name argus-runtime --policy-document "file://$tmp\runtime-policy.json" | Out-Null
if (-not (Test-Aws iam get-instance-profile --instance-profile-name $profileName)) {
    Invoke-Aws iam create-instance-profile --instance-profile-name $profileName --tags "Key=Project,Value=ARGUS" | Out-Null
    Invoke-Aws iam add-role-to-instance-profile --instance-profile-name $profileName --role-name $roleName | Out-Null
    Write-Host "Created instance profile $profileName (waiting for IAM propagation)"; Start-Sleep -Seconds 12
}

# --- Network: default VPC, security group, Elastic IP ------------------------
$vpcId = (Invoke-Aws ec2 describe-vpcs --filters "Name=is-default,Values=true").Vpcs[0].VpcId
$subnetId = (Invoke-Aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpcId" "Name=default-for-az,Values=true" "Name=availability-zone,Values=${Region}a").Subnets[0].SubnetId
$sg = (Invoke-Aws ec2 describe-security-groups --filters "Name=group-name,Values=$sgName" "Name=vpc-id,Values=$vpcId").SecurityGroups
if (-not $sg) {
    $sgId = (Invoke-Aws ec2 create-security-group --group-name $sgName --description "ARGUS Streamlit 8501 (no SSH; SSM only)" --vpc-id $vpcId --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$sgName},{Key=Project,Value=ARGUS}]").GroupId
    Invoke-Aws ec2 authorize-security-group-ingress --group-id $sgId --ip-permissions "IpProtocol=tcp,FromPort=8501,ToPort=8501,IpRanges=[{CidrIp=$AllowedCidr,Description=ARGUS-demo}]" | Out-Null
    Write-Host "Created security group $sgId"
} else { $sgId = $sg[0].GroupId }

$eip = (Invoke-Aws ec2 describe-addresses --filters "Name=tag:Project,Values=ARGUS").Addresses
if (-not $eip) {
    $alloc = Invoke-Aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=argus-eip},{Key=Project,Value=ARGUS}]"
    $allocId = $alloc.AllocationId; $publicIp = $alloc.PublicIp; Write-Host "Allocated EIP $publicIp"
} else { $allocId = $eip[0].AllocationId; $publicIp = $eip[0].PublicIp }

# --- Instance ----------------------------------------------------------------
$existing = (Invoke-Aws ec2 describe-instances --filters "Name=tag:Name,Values=argus-app" "Name=instance-state-name,Values=pending,running,stopping,stopped").Reservations
if ($existing) {
    $instanceId = $existing[0].Instances[0].InstanceId; Write-Host "Reusing instance $instanceId"
} else {
    $ami = (Invoke-Aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64).Parameter.Value
    Write-Utf8NoBom "$tmp\bdm.json" '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}}]'
    $ud = (Get-Content -Raw "$here\user-data.sh") -replace "`r`n", "`n"
    Write-Utf8NoBom "$tmp\user-data.sh" $ud
    $run = Invoke-Aws ec2 run-instances --image-id $ami --instance-type $InstanceType --subnet-id $subnetId `
        --security-group-ids $sgId --iam-instance-profile "Name=$profileName" `
        --metadata-options "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1" `
        --block-device-mappings "file://$tmp\bdm.json" --user-data "file://$tmp\user-data.sh" `
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=argus-app},{Key=Project,Value=ARGUS},{Key=Event,Value=REPH-AI-Summit-2026-Iloilo}]" "ResourceType=volume,Tags=[{Key=Name,Value=argus-app},{Key=Project,Value=ARGUS}]"
    $instanceId = $run.Instances[0].InstanceId; Write-Host "Launched $instanceId ($InstanceType, $ami)"
}
& aws ec2 wait instance-running --instance-ids $instanceId --region $Region
Invoke-Aws ec2 associate-address --instance-id $instanceId --allocation-id $allocId | Out-Null

$state = [ordered]@{ account = $account; region = $Region; bucket = $bucket; instanceId = $instanceId; securityGroupId = $sgId; allocationId = $allocId; publicIp = $publicIp; url = "http://${publicIp}:8501" }
Write-Utf8NoBom $statePath ($state | ConvertTo-Json)
Write-Host "`nARGUS hosting ready: http://${publicIp}:8501  (bootstrap takes ~2-3 min after first launch)"
$state | ConvertTo-Json
