#!/bin/bash
# Exit immediately if any command fails
set -e

# Load environment variables
export $(grep -v '^#' .env | xargs)

if [ ! -f instance_ids.txt ]; then
	echo "No instance_ids.txt found. Nothing to delete."
	exit 1
fi

IDS=$(cat instance_ids.txt | tr '\n' ' ')

echo "Terminating instances: $IDS"

aws ec2 terminate-instances --instance-ids $IDS --region "$AWS_REGION"

echo "Waiting for instances to terminate..."

aws ec2 wait instance-terminated --instance-ids $IDS --region "$AWS_REGION"

echo "All instances terminated sucessfully."
rm instance_ids.txt
