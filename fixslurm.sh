#!/bin/bash

# 1. Get the first line of slurmd -C output
slurmd_output=$(slurmd -C | head -n 1)

# 2. Find and comment the NodeName=ip- line
sed -i '/^ NodeName=ip-/s/^/#/' /etc/slurm/slurm.conf

# 3. Insert the new line
sed -i "/^# NodeName=ip-/a $slurmd_output State=UNKNOWN"  /etc/slurm/slurm.conf

# 4. Restart Slurm services
sudo systemctl restart slurmctld slurmd munge
