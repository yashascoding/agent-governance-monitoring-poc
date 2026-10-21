# AWS SNS Setup and Verification

This guide creates an SNS topic and email subscription for the alerting backend.
It uses only free-tier-eligible SNS resources. Do **not** run these against a
production account without review.

## 1. Prerequisites

- AWS CLI configured with a least-privilege identity (or use the console).
- An email address you can confirm for the subscription.

## 2. Create the topic and subscribe an email endpoint

```bash
export AWS_REGION=us-east-1
export ALERT_EMAIL="your-alert-inbox@example.com"

# Create a standard topic
TOPIC_ARN=$(aws sns create-topic \
  --name agent-governance-alerts \
  --query TopicArn --output text)
echo "Topic ARN: $TOPIC_ARN"

# Subscribe an email endpoint (pending confirmation)
aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol email \
  --notification-endpoint "$ALERT_EMAIL"
```

## 3. Confirm the subscription

AWS sends a "Subscription Confirmation" email. **The subscription is not active
until you click the confirmation link.** You can verify status with:

```bash
aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" \
  --query "Subscriptions[].{Endpoint:Endpoint,Arn:SubscriptionArn}"
```

A confirmed subscription shows a full ARN; an unconfirmed one shows
`"PendingConfirmation"`.

## 4. Configure the POC

```bash
export SNS_TOPIC_ARN="$TOPIC_ARN"
export AWS_REGION="us-east-1"
# Provide credentials via the standard chain (aws configure / SSO / IAM role).
```

## 5. Run the demo with SNS alerting

```bash
python main.py demo --mode faulty --sns
```

The monitor publishes CRITICAL and HIGH findings to SNS (routing is defined in
`config/policies.yaml`). The console output shows the SNS publish result.

## 6. Honesty about delivery

The SNS backend reports `SUCCESS` when the SNS API **accepted** the publish
request (it returns a `MessageId`). This does **not** prove the email was
delivered. To confirm subscriber delivery:

- Check the inbox, or
- Enable delivery status logging on the subscription (may incur small
  CloudWatch costs) and inspect the delivery metrics/logs.

A failed publish is reported as `FAILED` with the number of retry attempts, and
this never raises into the monitoring engine — detection is independent of
notification.

## 7. Tear down (optional)

```bash
aws sns delete-topic --topic-arn "$TOPIC_ARN"
```
