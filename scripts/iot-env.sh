#!/usr/bin/env bash

export AWS_PROFILE="amp"
export AWS_REGION="us-east-1"

export IOT_ENDPOINT="a11ogvst1mo5zr-ats.iot.us-east-1.amazonaws.com"

export IOT_CA="$HOME/amp/app/secrets/iot/AmazonRootCA1.pem"
export IOT_CERT="$(find "$HOME/amp/app/secrets/iot" -name '*-certificate.pem.crt' | head -n1)"
export IOT_KEY="$(find "$HOME/amp/app/secrets/iot" -name '*-private.pem.key' | head -n1)"

export IOT_CLIENT_ID="amp-ubuntu"
export IOT_COMMAND_TOPIC="amp/ubuntu/command"
export IOT_RESPONSE_PREFIX="amp/ubuntu/response"
