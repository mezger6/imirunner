#!/usr/bin/python3

import os
import sys
import json
import time
import shutil
import argparse
import logging
import boto3
import yaml
import subprocess
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables to store instance details
INSTANCE_ID_VAR = "AWS_INSTANCE_ID"
PUBLIC_URL_VAR = "AWS_PUBLIC_URL"

# Load configuration
with open('settings.yml', 'r') as f:
    config = yaml.safe_load(f)

AWS_REGION = config['aws']['region']
AMI_ID = config['aws']['ami_id']
INSTANCE_TYPE = config['aws']['instance_type']
LAUNCH_TEMPLATE_ID = config['aws']['launch_template_id']
SSH_KEY_PATH = config['paths']['ssh_key']
LOCAL_DATA_PATH = config['paths']['local_data']
S3_DATA_PATH = config['paths']['s3_data']

# Region-specific configuration
SHAPEFILE = config['region']['shapefile']
STATE_VECTOR = config['region']['state_vector']

# Initialize boto3 client
ec2 = boto3.client('ec2', region_name=AWS_REGION)



def create_instance(options=None):
    try:
        logging.info("🚀 Launching EC2 instance...")
        run_args = {
            'LaunchTemplate': {'LaunchTemplateId': LAUNCH_TEMPLATE_ID},
            'MinCount': 1,
            'MaxCount': 1,
            'KeyName': 'imikey'
        }
        if options:
            try:
                options_dict = json.loads(options)
                run_args.update(options_dict)
            except json.JSONDecodeError as e:
                logging.error(f"❌ Invalid JSON format: {str(e)}")
                logging.error("💡 Example valid format: {\"InstanceType\": \"t3.micro\", \"KeyName\": \"my-key\"}")
                return False
            except Exception as e:
                logging.error(f"❌ Invalid options: {str(e)}")
                return False
        
        # Start instance
        response = ec2.run_instances(**run_args)
        instance_id = response['Instances'][0]['InstanceId']
        logging.info(f"🆔 Instance ID: {instance_id}")

        # Wait for instance to be fully operational
        logging.info("⏳ Waiting for instance initialization (this may take a few minutes)...")
        waiter = ec2.get_waiter('instance_status_ok')
        waiter.wait(
            InstanceIds=[instance_id],
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}],
            WaiterConfig={'Delay': 30, 'MaxAttempts': 30}  # 15 minute timeout
        )

        # Get connection details
        instance = ec2.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]
        public_dns = instance['PublicDnsName']
        logging.info(f"🌐 Public DNS: {public_dns}")

        # Verify SSH accessibility
        logging.info("🔒 Testing SSH connectivity...")
        ssh_ready = False
        for _ in range(10):  # Additional 5 minute timeout
            try:
                subprocess.run(
                    ["ssh", "-i", SSH_KEY_PATH, "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
                     f"ubuntu@{public_dns}", "true"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                ssh_ready = True
                break
            except subprocess.CalledProcessError:
                time.sleep(30)
        
        if not ssh_ready:
            raise Exception("SSH connection failed after 15 minutes")

        # Run instance setup
        logging.info("🛠️ Starting instance setup...")
        if instance_setup(public_dns):
            logging.info("✅ Instance setup completed successfully")
            os.environ[INSTANCE_ID_VAR] = instance_id
            os.environ[PUBLIC_URL_VAR] = public_dns
            return True
        else:
            raise Exception("Instance setup failed")

    except Exception as e:
        logging.error(f"❌ Instance creation failed: {e}")
        return False

def instance_setup(public_url):
    try:
        # Copy required files
        files_to_copy = [
            ("tmux_install.sh", "/home/ubuntu/"),
            ("fixslurm.sh", "/home/ubuntu/"),
            (f"{SHAPEFILE}.shp", "/home/ubuntu/integrated_methane_inversion"),
            (f"{SHAPEFILE}.shx", "/home/ubuntu/integrated_methane_inversion"),
            (STATE_VECTOR, "/home/ubuntu/integrated_methane_inversion")
        ]
        
        for local_file, remote_path in files_to_copy:
            if os.path.exists(local_file):
                subprocess.run([
                    "scp", "-i", SSH_KEY_PATH, 
                    local_file, f"ubuntu@{public_url}:{remote_path}"
                ])
            else:
                logging.warning(f"Missing file: {local_file}")

        # Execute setup commands
        commands = [
            "sudo apt remove -y tmux",
            "chmod +x tmux_install.sh && ./tmux_install.sh",
            "chmod +x fixslurm.sh && ./fixslurm.sh"
        ]
        
        subprocess.run([
            "ssh", "-i", SSH_KEY_PATH, f"ubuntu@{public_url}",
            " && ".join(commands)
        ])
        
        return True
        
    except Exception as e:
        logging.error(f"Setup failed: {e}")
        return False

def terminate_instance(instance_no=0):
    instance_id = os.getenv(INSTANCE_ID_VAR)
    if instance_no or not instance_id:
        if not get_instance(instance_no):
            logging.error("No instance found")
            return
        instance_id = os.getenv(INSTANCE_ID_VAR)
    
    try:
        ec2.terminate_instances(InstanceIds=[instance_id])
        logging.info(f"Terminated instance: {instance_id}")
        os.environ[INSTANCE_ID_VAR] = ""
        os.environ[PUBLIC_URL_VAR] = ""
    except Exception as e:
        logging.error(f"Termination failed: {e}")

def stop_instance(instance_no=0):
    instance_id = os.getenv(INSTANCE_ID_VAR)
    if instance_no or not instance_id:
        state = get_instance(instance_no)
        if state != 'running':
            logging.error("Instance not running")
            return
        instance_id = os.getenv(INSTANCE_ID_VAR)
    
    try:
        ec2.stop_instances(InstanceIds=[instance_id])
        logging.info(f"Stopped instance: {instance_id}")
        os.environ[INSTANCE_ID_VAR] = ""
        os.environ[PUBLIC_URL_VAR] = ""
    except Exception as e:
        logging.error(f"Stop failed: {e}")

def restart_instance(instance_no=0):
    instance_id = os.getenv(INSTANCE_ID_VAR)
    if instance_no or not instance_id:
        state = get_instance(instance_no)
        if state != 'stopped':
            logging.error("Instance not stopped")
            return
        instance_id = os.getenv(INSTANCE_ID_VAR)
    
    try:
        ec2.start_instances(InstanceIds=[instance_id])
        logging.info(f"Started instance: {instance_id}")
        os.environ[INSTANCE_ID_VAR] = ""
        os.environ[PUBLIC_URL_VAR] = ""
    except Exception as e:
        logging.error(f"Start failed: {e}")

def cancel_spot(instance_no=0):
    try:
        spot_requests = ec2.describe_spot_instance_requests(
            Filters=[{'Name': 'state', 'Values': ['active']}]
        )['SpotInstanceRequests']
        
        if not spot_requests:
            logging.info("No active spot requests")
            return
            
        if instance_no >= len(spot_requests):
            logging.error(f"No spot request #{instance_no}")
            return
            
        request_id = spot_requests[instance_no]['SpotInstanceRequestId']
        ec2.cancel_spot_instance_requests(SpotInstanceRequestIds=[request_id])
        logging.info(f"Cancelled spot request: {request_id}")
        
    except Exception as e:
        logging.error(f"Spot cancellation failed: {e}")

def run_command(configfile="config.yml", instance_no=0, options=None, tmux=False):
    try:
        # Validate instance connection
        if not get_instance(instance_no):
            logging.error("No valid instance available")
            return

        public_url = os.getenv(PUBLIC_URL_VAR)
        if not public_url:
            logging.error("No public URL found for instance")
            return

        # Validate config file contents
        config_stem = os.path.splitext(os.path.basename(configfile))[0]
        run_name = None
        use_slurm = None

        with open(configfile, 'r') as f:
            for line in f:
                # Process RunName line
                if line.startswith('RunName:'):
                    run_name_value = line.split(':', 1)[1].strip().strip('\"\'')
                    if run_name_value != config_stem:
                        logging.error(f"Config filename '{config_stem}' does not match RunName '{run_name_value}'")
                        logging.error("Please ensure the config filename matches the RunName value")
                        sys.exit(1)
                    run_name = run_name_value
                
                # Process UseSlurm line
                elif line.startswith('UseSlurm:'):
                    slurm_value = line.split(':', 1)[1].strip().lower()
                    if slurm_value == 'true':
                        use_slurm = True
                    elif slurm_value == 'false':
                        use_slurm = False
                    else:
                        logging.error(f"Invalid UseSlurm value: {slurm_value}. Must be 'true' or 'false'")
                        sys.exit(1)

        # Validate UseSlurm vs tmux option
        if use_slurm is not None:
            if use_slurm and tmux:
                logging.error("Configuration conflict: UseSlurm=true cannot be used with --tmux")
                logging.error("When using Slurm (UseSlurm=true), omit the --tmux option")
                sys.exit(1)
            elif not use_slurm and not tmux:
                logging.error("Configuration conflict: UseSlurm=false requires --tmux option")
                logging.error("When not using Slurm (UseSlurm=false), you must specify --tmux")
                sys.exit(1)

        # File transfer and command execution
        kalman_file = "KalmanPeriods.csv"
        if os.path.exists(kalman_file):
            subprocess.run([
                "scp", "-i", SSH_KEY_PATH,
                kalman_file,
                f"ubuntu@{public_url}:/home/ubuntu/integrated_methane_inversion/periods.csv"
            ])
        else:
            logging.warning(f"{kalman_file} not found, skipping transfer")

        subprocess.run([
            "scp", "-i", SSH_KEY_PATH,
            configfile,
            f"ubuntu@{public_url}:/home/ubuntu/integrated_methane_inversion"
        ])

        # Build execution command
        base_cmd = "cd /home/ubuntu/integrated_methane_inversion && "
        if tmux:
            execution_cmd = f"tmux new-session -d -s imi './run_imi.sh {configfile} {options or ''} > imi_output.log'"
        else:
            execution_cmd = f"sbatch run_imi.sh {configfile} {options or ''}"

        subprocess.run([
            "ssh", "-i", SSH_KEY_PATH, f"ubuntu@{public_url}",
            base_cmd + execution_cmd
        ])

        logging.info(f"Inversion started successfully for config: {configfile}")
        tail_logfile(logfile="imi_output.log", instance_no=instance_no, run_name=run_name or config_stem)

    except Exception as e:
        logging.error(f"Failed to execute run command: {e}")
        sys.exit(1)

def tail_logfile(logfile="imi_output.log", instance_no=0, run_name=None):
    if not get_instance(instance_no):
        return
        
    public_url = os.getenv(PUBLIC_URL_VAR)
    
    try:
        cmd = [
            "ssh", "-i", SSH_KEY_PATH, f"ubuntu@{public_url}",
            f"tail -n 1000 -f integrated_methane_inversion/{logfile}"
        ]
        
        if run_name:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
            for line in iter(process.stdout.readline, b''):
                print(line.decode().strip())
                if "Posterior" in line.decode() or "IMI ended" in line.decode():
                    logging.info("Run completed, copying results...")
                    copy_to_local(run_name, instance_no)
                    break
        else:
            subprocess.run(cmd)
            
    except Exception as e:
        logging.error(f"Log tail failed: {e}")

def open_shell(instance_no=0, *args):
    if not get_instance(instance_no):
        return
        
    public_url = os.getenv(PUBLIC_URL_VAR)
    cmd = ["ssh", "-i", SSH_KEY_PATH, f"ubuntu@{public_url}"]
    
    if args:
        cmd.extend(args)
        
    try:
        subprocess.run(cmd)
    except Exception as e:
        logging.error(f"SSH failed: {e}")



def copy_from_s3(run_name, instance_no=0):
    if not get_instance(instance_no):
        return
        
    public_url = os.getenv(PUBLIC_URL_VAR)
    
    try:
        subprocess.run([
            "ssh", "-i", SSH_KEY_PATH, f"ubuntu@{public_url}",
            f"mkdir -p /home/ubuntu/imi_output_dir/{run_name}"
        ])
        
        subprocess.run([
            "ssh", "-i", SSH_KEY_PATH, f"ubuntu@{public_url}",
            f"cd /home/ubuntu/imi_output_dir/{run_name} && "
            f"tmux new-session -d -s s3sync 'aws s3 cp s3://imidata/{run_name}/{run_name}.tar.gz - | tar -xz'"
        ])
        
        logging.info(f"Started S3 download for {run_name} in tmux session")
        
    except Exception as e:
        logging.error(f"S3 copy failed: {e}")

def copy_to_local(run_name, instance_no=0, overwrite=False):
    try:
        # Validate instance connection
        if not get_instance(instance_no):
            logging.error("No valid instance available")
            return

        public_url = os.getenv(PUBLIC_URL_VAR)
        if not public_url:
            logging.error("No public URL found for instance")
            return

        # Define paths
        local_dir_base = os.path.join(LOCAL_DATA_PATH, run_name)
        remote_base = f"/home/ubuntu/imi_output_dir/{run_name}"
        
        # Handle existing directories
        local_dir = local_dir_base
        if not overwrite:
            counter = 1
            while os.path.exists(local_dir):
                local_dir = f"{local_dir_base}_{counter}"
                counter += 1
            logging.info(f"Using new directory: {local_dir}")

        os.makedirs(local_dir, exist_ok=True)

        # Define all remote directories and files to copy
        transfer_items = [
            # Directories (rsync)
            (f"{remote_base}/preview", "preview"),
            (f"{remote_base}/inversion", "inversion"),
            (f"{remote_base}/hemco_prior_emis", "hemco_prior_emis"),
            (f"{remote_base}/archive_sf", "archive_sf"),
            
            # Individual files (scp)
            (f"{remote_base}/imi_output.log", ""),
            (f"{remote_base}/StateVector.nc", ""),
            (f"{remote_base}/*.yml", ""),
            (f"{remote_base}/config_{run_name}.yml", "config.yml")
        ]

        # Copy each item
        for remote_path, local_subdir in transfer_items:
            try:
                local_target = os.path.join(local_dir, local_subdir) if local_subdir else local_dir
                
                if '*' in remote_path:  # Handle wildcard files
                    files = subprocess.check_output([
                        "ssh", "-i", SSH_KEY_PATH, f"ubuntu@{public_url}",
                        f"ls {remote_path}"
                    ]).decode().split()
                    
                    for f in files:
                        subprocess.run([
                            "scp", "-i", SSH_KEY_PATH,
                            f"ubuntu@{public_url}:{f}",
                            local_target
                        ])
                        
                elif os.path.basename(remote_path).endswith('.yml'):  # Config file rename
                    subprocess.run([
                        "scp", "-i", SSH_KEY_PATH,
                        f"ubuntu@{public_url}:{remote_path}",
                        os.path.join(local_dir, "config.yml")
                    ])
                    
                else:  # Directory or single file
                    if 'preview' in remote_path or 'inversion' in remote_path:  # Directory
                        subprocess.run([
                            "rsync", "-azP",
                            "-e", f"ssh -i {SSH_KEY_PATH}",
                            f"ubuntu@{public_url}:{remote_path}/",
                            f"{local_target}/"
                        ])
                    else:  # Single file
                        subprocess.run([
                            "scp", "-i", SSH_KEY_PATH,
                            f"ubuntu@{public_url}:{remote_path}",
                            local_target
                        ])
                        
            except Exception as e:
                logging.warning(f"Failed to copy {remote_path}: {str(e)}")
                continue

        logging.info(f"Successfully copied all data to: {local_dir}")
        return local_dir

    except Exception as e:
        logging.error(f"Copy to local failed: {e}")
        return None

def get_instance(instance_no=0):
    try:
        response = ec2.describe_instances()
        instances = []
        
        # Build instance list
        for res in response['Reservations']:
            for inst in res['Instances']:
                instances.append({
                    'id': inst['InstanceId'],
                    'state': inst['State']['Name'],
                    'public_dns': inst.get('PublicDnsName', 'N/A'),
                    'type': inst['InstanceType'],
                    'launch_time': inst['LaunchTime'].strftime('%Y-%m-%d %H:%M:%S')
                })

        # Print table
        if instances:
            logging.info("\n📋 Available EC2 Instances:")
            print(f"{'Index':<6} {'Instance ID':<20} {'State':<12} {'Type':<12} {'Public DNS':<40} {'Launch Time'}")
            print("-" * 100)
            for idx, inst in enumerate(instances):
                print(f"{idx:<6} {inst['id']:<20} {inst['state'].upper():<12} {inst['type']:<12} {inst['public_dns']:<40} {inst['launch_time']}")
            print()
        else:
            logging.info("ℹ️ No instances found")
            return None

        # Validate selection
        if instance_no >= len(instances):
            logging.error(f"❌ Invalid instance number: {instance_no}")
            return None
            
        selected = instances[instance_no]
        os.environ[INSTANCE_ID_VAR] = selected['id']
        os.environ[PUBLIC_URL_VAR] = selected['public_dns']
        
        logging.info(f"🔍 Selected instance {instance_no}:")
        logging.info(f"   ID: {selected['id']}")
        logging.info(f"   State: {selected['state'].upper()}")
        logging.info(f"   Public DNS: {selected['public_dns']}")
        logging.info(f"   Type: {selected['type']}")
        logging.info(f"   Launched: {selected['launch_time']}")
        
        return selected['state']

    except Exception as e:
        logging.error(f"❌ Error listing instances: {e}")
        return None
    


def print_help():
    help_message = """
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
        ./imirunner.py create --options="--instance-type=c5.18xlarge"
        ./imirunner.py run config.yml -i 0 --tmux
        ./imirunner.py instance_setup 
        ./imirunner.py copy_local my_run -i 1
        ./imirunner.py shell "ls -l"
    """
    print(help_message)

def instance_setup_cli(instance_no=0):
    """Command-line handler for instance setup"""
    if not get_instance(instance_no):
        logging.error("No instance found for setup")
        return False
        
    public_url = os.getenv(PUBLIC_URL_VAR)
    if not public_url:
        logging.error("No public URL found")
        return False
        
    return instance_setup(public_url)


def main():
    parser = argparse.ArgumentParser(description="Manage EC2 instances for methane inversion", 
                                   add_help=False)
    subparsers = parser.add_subparsers(dest="command", title="subcommands",
                                     help='Available operations')

    # Create command
    create_parser = subparsers.add_parser('create', help='Launch EC2 instance')
    create_parser.add_argument('--options', help='AWS CLI options in JSON format')

    # Instance management commands
    for cmd in ['terminate', 'stop', 'restart', 'cancel_spot']:
        cmd_parser = subparsers.add_parser(cmd, help=f'{cmd.capitalize()} instance')
        cmd_parser.add_argument('-i', '--instance', type=int, default=0,
                              help='Instance number (0-based index)')

    # Instance setup command
    setup_parser = subparsers.add_parser('instance_setup', 
                                       help='Run setup scripts on instance')
    setup_parser.add_argument('-i', '--instance', type=int, default=0,
                            help='Instance number (0-based index)')

    # Run command
    run_parser = subparsers.add_parser('run', help='Start inversion')
    run_parser.add_argument('configfile', help='Configuration file path')
    run_parser.add_argument('-i', '--instance', type=int, default=0,
                          help='Instance number (0-based index)')
    run_parser.add_argument('--tmux', action='store_true', 
                          help='Run in tmux session')
    run_parser.add_argument('--options', help='Additional run options')

    # Log command
    log_parser = subparsers.add_parser('log', help='Tail log files')
    log_parser.add_argument('-i', '--instance', type=int, default=0,
                          help='Instance number (0-based index)')
    log_parser.add_argument('--logfile', default='imi_output.log',
                          help='Log file to tail')

    # Copy commands
    copy_parser = subparsers.add_parser('copy_local', 
                                      help='Copy results to local storage')
    copy_parser.add_argument('run_name', help='Name of the run to copy')
    copy_parser.add_argument('-i', '--instance', type=int, default=0,
                           help='Instance number (0-based index)')
    copy_parser.add_argument('--overwrite', action='store_true',
                           help='Overwrite existing files')

    s3_parser = subparsers.add_parser('copy_from_s3', 
                                    help='Copy data from S3 to instance')
    s3_parser.add_argument('run_name', help='Name of the run to copy')
    s3_parser.add_argument('-i', '--instance', type=int, default=0,
                         help='Instance number (0-based index)')

    # Diagnostic commands
    subparsers.add_parser('get_instance', 
                        help='List available instances').add_argument(
                            '-i', '--instance', type=int, default=0)

    shell_parser = subparsers.add_parser('shell', 
                                       help='Open SSH session to instance')
    shell_parser.add_argument('-i', '--instance', type=int, default=0,
                            help='Instance number (0-based index)')
    shell_parser.add_argument('command', nargs=argparse.REMAINDER,
                            help='Command to execute remotely')

    # Help command
    subparsers.add_parser('help', help='Show help').set_defaults(func=print_help)

    # Handle help requests
    if len(sys.argv) == 1 or any(a in sys.argv for a in ('-h', '--help')):
        print_help()
        sys.exit(0 if '-h' in sys.argv or '--help' in sys.argv else 1)

    args = parser.parse_args()

    # Command routing
    handlers = {
        'create': lambda: create_instance(args.options),
        'terminate': lambda: terminate_instance(args.instance),
        'stop': lambda: stop_instance(args.instance),
        'restart': lambda: restart_instance(args.instance),
        'cancel_spot': lambda: cancel_spot(args.instance),
        'instance_setup': lambda: instance_setup_cli(args.instance),
        'run': lambda: run_command(args.configfile, args.instance, args.options, args.tmux),
        'log': lambda: tail_logfile(logfile=args.logfile, instance_no=args.instance),
        'copy_local': lambda: copy_to_local(args.run_name, args.instance, args.overwrite),
        'copy_from_s3': lambda: copy_from_s3(args.run_name, args.instance),
        'get_instance': lambda: get_instance(args.instance),
        'shell': lambda: open_shell(args.instance, *args.command),
        'help': lambda: print_help()
    }

    if args.command in handlers:
        handlers[args.command]()
    else:
        print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()