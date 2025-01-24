#!/bin/bash

# Create necessary directories
if [ ! -d /data/local ]; then
  mkdir -p /data/local
fi

if [ ! -d /data/s3 ]; then
  mkdir -p /data/s3
fi

# Ensure AWS configuration is set up
/scripts/aws_config.sh

# Start the SSH service
/usr/sbin/sshd -D