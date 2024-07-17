import subprocess
import os
import json
import click
from colorama import Fore, Style
import time
import re
from .utils import print_error, print_success, print_info, print_warning
from ..metadata.common_utils import get_ignore_patterns, get_folder_structure


class Executor:
    def __init__(self):
        self.current_dir = os.getcwd()
        self.allowed_directories = [self.current_dir]
        self.disallowed_commands = [
            'rmdir', 'del', 'format', 'mkfs',
            'dd', 'fsck', 'mkswap', 'mount', 'umount',
            'sudo', 'su', 'chown', 'chmod'
        ]
        self.env = os.environ.copy()

    def is_safe_path(self, path):
        full_path = os.path.abspath(os.path.join(self.current_dir, path))
        return any(full_path.startswith(allowed_dir) for allowed_dir in self.allowed_directories)

    def is_safe_rm_command(self, command):
        parts = command.split()
        if parts[0] != 'rm':
            return False

        # Check for dangerous flags
        dangerous_flags = ['-r', '-f', '-rf', '-fr']
        if any(flag in parts for flag in dangerous_flags):
            return False

        # Check if it's removing a specific file
        if len(parts) != 2:
            return False

        file_to_remove = parts[1]
        return self.is_safe_path(file_to_remove) and os.path.isfile(os.path.join(self.current_dir, file_to_remove))

    def is_safe_command(self, command):
        command_parts = command.split()
        if command_parts[0] == 'rm':
            return self.is_safe_rm_command(command)
        return not any(cmd in self.disallowed_commands for cmd in command_parts)

    def perform_file_operation(self, operation, filename, content=None, force=False):
        full_path = os.path.abspath(os.path.join(self.current_dir, filename))

        if not self.is_safe_path(full_path):
            error_message = f"File operation not allowed outside of the project directory: {filename}"
            print_error(error_message)
            return False

        print_info(f"File: {filename}")
        if content:
            print_info(f"Content preview: {content[:100]}...")

        if operation in ['DELETE', 'UPDATE']:
            if not click.confirm(f"Allow Dravid to {operation.lower()} the file '{filename}'?", default=False):
                print_info(f"File {operation.lower()} cancelled by user.")
                return False

        if operation == 'CREATE':
            if os.path.exists(full_path) and not force:
                print_info(f"File already exists: {filename}")
                return False
            try:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w') as f:
                    f.write(content)
                print_success(f"File created successfully: {filename}")
                return True
            except Exception as e:
                print_error(f"Error creating file: {str(e)}")
                return False

        elif operation == 'UPDATE':
            if not os.path.exists(full_path):
                print_info(f"File does not exist: {filename}")
                return False
            try:
                with open(full_path, 'w') as f:
                    f.write(content)
                print_success(f"File updated successfully: {filename}")
                return True
            except Exception as e:
                print_error(f"Error updating file: {str(e)}")
                return False

        elif operation == 'DELETE':
            if not os.path.isfile(full_path):
                print_info(
                    f"Delete operation is only allowed for files: {filename}")
                return False
            try:
                os.remove(full_path)
                print_success(f"File deleted successfully: {filename}")
                return True
            except Exception as e:
                print_error(f"Error deleting file: {str(e)}")
                return False

        else:
            print_error(f"Unknown file operation: {operation}")
            return False

    def parse_json(self, json_string):
        try:
            return json.loads(json_string)
        except json.JSONDecodeError as e:
            print_error(f"JSON parsing error: {str(e)}")
            return None

    def merge_json(self, existing_content, new_content):
        try:
            existing_json = json.loads(existing_content)
            new_json = json.loads(new_content)
            merged_json = {**existing_json, **new_json}
            return json.dumps(merged_json, indent=2)
        except json.JSONDecodeError as e:
            print_error(f"Error merging JSON content: {str(e)}")
            return None

    def get_folder_structure(self):
        ignore_patterns, _ = get_ignore_patterns(self.current_dir)
        return get_folder_structure(self.current_dir, ignore_patterns)

    def execute_shell_command(self, command, timeout=300):  # 5 minutes timeout
        if not self.is_safe_command(command):
            print_warning(f"Please verify the command once: {command}")

        if not click.confirm(f"Do you want to execute the following command?\n{command}", default=False):
            print_info("Command execution cancelled by user.")
            return None

        click.echo(
            f"{Fore.YELLOW}Executing shell command: {command}{Style.RESET_ALL}")

        if command.strip().startswith(('source ', '.')):
            return self._handle_source_command(command)

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self.env,
            )

            start_time = time.time()
            output = []
            while True:
                return_code = process.poll()
                if return_code is not None:
                    break
                if time.time() - start_time > timeout:
                    process.terminate()
                    error_message = f"Command timed out after {timeout} seconds: {command}"
                    print_error(error_message)
                    raise Exception(error_message)

                line = process.stdout.readline()
                if line:
                    print(line.strip())
                    output.append(line)

                time.sleep(0.1)

            stdout, stderr = process.communicate()
            output.append(stdout)

            if return_code != 0:
                error_message = f"Command failed with return code {return_code}\nError output: {stderr}"
                print_error(error_message)
                raise Exception(error_message)

            # Update environment variables if the command was successful
            self._update_env_from_command(command)

            print_success("Command executed successfully.")
            return ''.join(output)

        except Exception as e:
            error_message = f"Error executing command '{command}': {str(e)}"
            print_error(error_message)
            raise Exception(error_message)

    def _handle_source_command(self, command):
        # Extract the file path from the source command
        _, file_path = command.split(None, 1)
        file_path = os.path.expandvars(os.path.expanduser(file_path))

        if not os.path.isfile(file_path):
            error_message = f"Source file not found: {file_path}"
            print_error(error_message)
            raise Exception(error_message)

        # Execute the source command in a subshell and capture the environment changes
        try:
            result = subprocess.run(
                f'source {file_path} && env',
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                executable='/bin/bash'
            )

            # Update the environment with any changes
            for line in result.stdout.splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    self.env[key] = value

            print_success(f"Sourced file successfully: {file_path}")
            return "Source command executed successfully"
        except subprocess.CalledProcessError as e:
            error_message = f"Error executing source command: {str(e)}"
            print_error(error_message)
            raise Exception(error_message)

    def _update_env_from_command(self, command):
        if '=' in command:
            if command.startswith('export '):
                # Handle export command
                _, var_assignment = command.split(None, 1)
                key, value = var_assignment.split('=', 1)
                self.env[key.strip()] = value.strip().strip('"\'')
            elif command.startswith('set '):
                # Handle set command
                _, var_assignment = command.split(None, 1)
                key, value = var_assignment.split('=', 1)
                self.env[key.strip()] = value.strip().strip('"\'')
            else:
                # Handle simple assignment
                key, value = command.split('=', 1)
                self.env[key.strip()] = value.strip().strip('"\'')
