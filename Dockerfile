# Use the official Ubuntu base image
FROM ubuntu:latest

# Update the package list and install necessary packages
RUN apt-get update && \
    apt-get install -y \
    openssh-server curl unzip s3fs groff nano less python3 python3-pip

# Install AWS CLI and boto3
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install

RUN pip3 install boto3 pyyaml --break-system-packages

# Create the SSH directory and set up the SSH server
RUN mkdir /var/run/sshd && \
    echo 'PubkeyAuthentication yes' >> /etc/ssh/sshd_config && \
    echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config

# Create required directories
RUN mkdir -p /scripts /data/local /data/s3 /root/.aws

# Expose the SSH port
EXPOSE 22

# Copy SSH configuration
RUN mkdir -p /root/.ssh
COPY ssh_config /root/.ssh/config

# Copy the imirunner script and sample settings file
COPY imirunner.py /root/imirunner.py
COPY settings.yml /root/settings.yml
COPY tmux_install.sh /root/tmux_install.sh
COPY fixslurm.sh /root/fix_slurm.sh
RUN ["chmod", "+x", "/root/imirunner.py"]
RUN ["chmod", "+x", "/root/fixslurm.sh"]
RUN ["chmod", "+x", "/root/tmux_install.sh"]

# Copy the AWS configuration script
COPY aws_config.sh /scripts/aws_config.shs
RUN chmod +x /scripts/aws_config.sh

# Set up AWS credentials and config
RUN mkdir -p /root/.aws
RUN /scripts/aws_config.sh

COPY run.sh /scripts/run.sh 
RUN ["chmod", "+x", "/scripts/run.sh"]
ENTRYPOINT ["/scripts/run.sh"]