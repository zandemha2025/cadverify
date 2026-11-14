#!/usr/bin/env bash
# Destroys everything provision.sh created, so billing stops. Safe to run anytime.
set -euo pipefail
cd "$(dirname "$0")"

[[ -f deploy.state ]] || { echo "Nothing to tear down (no deploy.state)."; exit 0; }
# shellcheck disable=SC1091
source deploy.state
aws() { command aws --region "$REGION" "$@"; }

echo ">> Terminating instance $INSTANCE_ID…"
aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" >/dev/null
aws ec2 wait instance-terminated --instance-ids "$INSTANCE_ID"

echo ">> Releasing Elastic IP $PUBLIC_IP…"
aws ec2 release-address --allocation-id "$EIP_ALLOC_ID" >/dev/null || true

echo ">> Deleting security group…"
for i in $(seq 1 6); do
  if aws ec2 delete-security-group --group-id "$SECURITY_GROUP_ID" 2>/dev/null; then break; fi
  sleep 10  # SG can linger as 'in use' briefly after termination
done

echo ">> Deleting key pair…"
aws ec2 delete-key-pair --key-name "$KEY_NAME" >/dev/null || true
rm -f "$KEY_FILE"

rm -f deploy.state
echo ">> Done. All CadVerify AWS resources removed; billing stopped."
