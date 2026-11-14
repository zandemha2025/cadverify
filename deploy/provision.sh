#!/usr/bin/env bash
# Provisions the AWS infrastructure: key pair, security group, EC2 instance,
# and a stable Elastic IP. Writes everything it creates to deploy.state so
# teardown.sh can clean up later. Idempotent-ish: refuses to run if state exists.
set -euo pipefail
cd "$(dirname "$0")"

# ── Tunables ────────────────────────────────────────────────
REGION="${REGION:-us-east-1}"
# t3.small (2 GB, ~$15/mo) is the cheapest that plausibly runs the whole stack
# with the 4 GB swap the box sets up. If the build OOMs, set INSTANCE_TYPE=t3.medium.
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
ROOT_GB="${ROOT_GB:-30}"
NAME="cadverify"
KEY_NAME="${NAME}-deploy"
SG_NAME="${NAME}-sg"
STATE_FILE="deploy.state"

aws() { command aws --region "$REGION" "$@"; }

if [[ -f "$STATE_FILE" ]]; then
  echo "!! $STATE_FILE already exists — infra looks provisioned. Run teardown.sh first if you want a fresh box." >&2
  exit 1
fi

echo ">> Verifying AWS credentials…"
aws sts get-caller-identity --query Account --output text >/dev/null

echo ">> Finding default VPC + subnet…"
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
if [[ "$VPC" == "None" || -z "$VPC" ]]; then
  echo "!! No default VPC in $REGION. Create one in the console (VPC > Actions > Create default VPC) and re-run." >&2
  exit 1
fi
SUBNET=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" "Name=default-for-az,Values=true" \
  --query 'Subnets[0].SubnetId' --output text)

echo ">> Creating SSH key pair ($KEY_NAME)…"
aws ec2 create-key-pair --key-name "$KEY_NAME" --query 'KeyMaterial' --output text > "${KEY_NAME}.pem"
chmod 600 "${KEY_NAME}.pem"

echo ">> Creating security group ($SG_NAME)…"
SG=$(aws ec2 create-security-group --group-name "$SG_NAME" \
  --description "CadVerify demo box" --vpc-id "$VPC" --query 'GroupId' --output text)

MYIP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
echo "   Allowing SSH (22) only from your IP: ${MYIP}/32"
aws ec2 authorize-security-group-ingress --group-id "$SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MYIP}/32,Description=ssh-admin}]" >/dev/null
echo "   Opening app ports 3000 (frontend) + 8000 (backend API) to the world"
aws ec2 authorize-security-group-ingress --group-id "$SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=3000,ToPort=3000,IpRanges=[{CidrIp=0.0.0.0/0,Description=frontend}]" \
                   "IpProtocol=tcp,FromPort=8000,ToPort=8000,IpRanges=[{CidrIp=0.0.0.0/0,Description=backend}]" >/dev/null

echo ">> Looking up latest Ubuntu 24.04 AMI…"
AMI=$(aws ssm get-parameters \
  --names /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query 'Parameters[0].Value' --output text)

echo ">> Launching $INSTANCE_TYPE instance…"
IID=$(aws ec2 run-instances \
  --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_NAME" --security-group-ids "$SG" --subnet-id "$SUBNET" \
  --associate-public-ip-address \
  --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=${ROOT_GB},VolumeType=gp3}" \
  --user-data file://cloud-init.yaml \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME}}]" \
  --query 'Instances[0].InstanceId' --output text)
echo "   Instance: $IID — waiting for it to reach 'running'…"
aws ec2 wait instance-running --instance-ids "$IID"

echo ">> Allocating + associating a stable Elastic IP…"
ALLOC=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)
aws ec2 associate-address --instance-id "$IID" --allocation-id "$ALLOC" >/dev/null
IP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)

cat > "$STATE_FILE" <<EOF
REGION=$REGION
INSTANCE_ID=$IID
SECURITY_GROUP_ID=$SG
EIP_ALLOC_ID=$ALLOC
PUBLIC_IP=$IP
KEY_NAME=$KEY_NAME
KEY_FILE=${KEY_NAME}.pem
EOF

echo ""
echo "==================================================================="
echo " Infrastructure ready."
echo "   Public IP : $IP"
echo "   Instance  : $IID  ($INSTANCE_TYPE, $REGION)"
echo "   Saved to  : $STATE_FILE"
echo "==================================================================="
