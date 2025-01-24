#!/bin/bash

# Create ~/.aws/config
cat <<EOF > /root/.aws/config
[default]
region = ${AWS_REGION}
output = json
EOF

# Create ~/.aws/credentials
cat <<EOF > /root/.aws/credentials
[default]
aws_access_key_id = ${AWS_ACCESS_KEY_ID}
aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY}
EOF

# Set permissions
chmod 600 /root/.aws/config
chmod 600 /root/.aws/credentials