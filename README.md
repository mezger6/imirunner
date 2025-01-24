# imirunner

A tool to automate running the [Integrated Methane Inversion](https://github.com/geoschem/integrated_methane_inversion) on Amazon EC2 instances.

## Warning

- This tool provisions EC2 instances, which cost money. Please keep a close eye on your billing and set up alerts to prevent unwanted charges.
- The Docker container comes with an ssh server for ease of access. If you expose the ssh port to the internet, you risk compromising your AWS account and being overcharged. Please keep the container accessible only internally or set up secure access through a VPN or reverse proxy.

## Prerequisites

- Python 3.x
- Docker

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/mezger6/imirunner.git
   cd imirunner
   ```

2. Build the Docker image:

   ```bash
   docker compose build
   ```

3. Set up AWS credentials, EC2 ssh key path, authorized_keys path and local data path either as environment variables, or by substituting directly in `docker-compose.yml`:

   a. Environment variables:

   ```bash
   export AWS_REGION=us-east-1
   export AWS_ACCESS_KEY_ID=your-access-key-id
   export AWS_SECRET_ACCESS_KEY=your-secret-access-key
   export LOCAL_DATA_PATH=/path/to/local/data
   export SSH_KEY_PATH=/path/to/EC2/sshkey.pem
   export SSH_AUTHORIZED_KEYS_PATH:-/path/to/authorized_keys
   ```

   b. `docker-compose.yml`:

   ```yaml
   version: "3.8"

   services:
   imirunner:
     container_name: imirunner
     privileged: true
     ports:
       - 15522:22/tcp
     environment:
       - TZ=${TIMEZONE:-Europe/Athens}
       - AWS_REGION=${AWS_REGION:-us-east-1}
       - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
       - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
     volumes:
       - ${LOCAL_DATA_PATH:-/path/to/local/data}:/data/local
       - ${SSH_KEY_PATH:-/path/to/EC2/sshkey.pem}:/root/imikey.pem
       - ${SSH_AUTHORIZED_KEYS_PATH:-/path/to/authorized_keys}:/root/.ssh/authorized_keys
     image: imirunner:latest
     network_mode: bridge
   ```

4. Start the container with `docker compose up -d`.

## Initial configuration

1. Open a shell to the container, via ssh or docker:

   ```bash
   docker exec -it imirunner /bin/bash
   ```

2. Create a launch template in EC2 and get the launch template ID.

3. (Optional) Create a `KalmanPeriods.csv` file according to the sample.

4. (Optional) Create custom shapefiles and state vector files following the instructions at https://imi.readthedocs.io/en/latest/getting-started/imi-config-file.html#custom-pre-generated-state-vector

5. Modify the sample settings file `settings.yml` to add your launch_template_id and custom shapefile/state vector filenames:

   ```yaml
   aws:
     region: us-east-1
     ami_id: ami-0d1f9163a7a4c609f
     instance_type: c5.9xlarge
     launch_template_id: lt-20d224e2c4a10330d
   paths:
     local_data: /data/local
     s3_data: /data/s3
     ssh_key: /root/imikey.pem
   region:
     shapefile: CustomShapefile
     state_vector: CustomStateVector.nc
   ```

6. Create a `config.yml` for the imi according to the [docs](https://imi.readthedocs.io/en/latest/getting-started/imi-config-file.html).
   Note that the `RunName` MUST match the filename (i.e. `RunName: my_run` has to be in `my_run.yml`)

## Usage

    Usage: imirunner.py <action> [options]

    Options:
        -i, --instance_no   0-based instance index (default: 0)

    Actions:
        create [--options]       Start an EC2 instance. Pass additional options to the aws ec2 run-instances command
        terminate [-i NUM]       Terminate a running EC2 instance. WARNING: the attached volume may be deleted!
        stop [-i NUM]            Stop a running EC2 instance
        restart [-i NUM]         Restart a stopped EC2 instance
        cancel_spot [-i NUM]     Cancel an active spot request
        instance_setup [-i NUM]  Run setup scripts on existing instance
        run <configfile> [-i NUM] [--tmux] [--options]
                                Run inversion using specified config file
        log [-i NUM] [--logfile] Tail log file (default: imi_output.log)
        shell [-i NUM] [command] Open SSH session or execute command
        copy_local [-i NUM] <run_name> [--overwrite]
                                Copy run results to local storage
        copy_from_s3 [-i NUM] <run_name>
                                Copy run output from S3 to instance
        get_instance [-i NUM]    Show details of running instances
        help                    Print this help message

    Examples:
        ./imirunner.py create --options='{"InstanceType": "t3.micro"}'
        ./imirunner.py run config.yml -i 0 --tmux
        ./imirunner.py instance_setup
        ./imirunner.py copy_local my_run -i 1
        ./imirunner.py shell "ls -l"

## Example usage

- Create an EC2 instance:
  ```bash
  ./imirunner.py create --options='{"InstanceType": "c5.9xlarge"}'
  ```
- View instances and their status:
  ```bash
  ./imirunner.py get_instance
  ```
- Run an inversion:
  ```bash
  ./imirunner.py run my_run.yml
  ```
- Tail a log file:
  ```bash
  ./imirunner.py log
  ```
- Copy output to local:
  ```bash
  ./imirunner.py copy_local my_run
  ```
