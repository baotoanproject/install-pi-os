#!/usr/bin/env python3
"""
System Control Service for OrangePi Zero3
Nhận lệnh từ Flutter app qua TCP socket để điều khiển hệ thống
- File operations
- Service control
- Script execution
Port: 8766
"""

import json
import subprocess
import socket
import threading
import logging
import time
import os
import base64
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# TCP Server configuration
HOST = '0.0.0.0'
PORT = 8766

class SystemControlService:
    def __init__(self):
        self.clients = []
        self.server_socket = None
        self.running_scripts = {}  # Track running processes

    def handle_client(self, client_socket, client_address):
        """Xử lý kết nối từ client"""
        logger.info(f"Client connected from {client_address}")
        self.clients.append(client_socket)

        try:
            while True:
                data = client_socket.recv(1024)
                if not data:
                    break

                try:
                    command = json.loads(data.decode())
                    logger.info(f"Received command: {command}")

                    if command.get('action') == 'ping':
                        # Respond to ping for device discovery
                        self.send_response(client_socket, {
                            'action': 'pong',
                            'service': 'orangepi-system-control',
                            'version': '1.0'
                        })

                    # FILE OPERATIONS
                    elif command.get('action') == 'list_files':
                        self.list_files(command, client_socket)
                    elif command.get('action') == 'download_file':
                        self.download_file(command, client_socket)
                    elif command.get('action') == 'delete_file':
                        self.delete_file(command, client_socket)

                    # SERVICE OPERATIONS
                    elif command.get('action') == 'list_services':
                        self.list_services(client_socket)
                    elif command.get('action') == 'start_service':
                        self.start_service(command, client_socket)
                    elif command.get('action') == 'stop_service':
                        self.stop_service(command, client_socket)
                    elif command.get('action') == 'restart_service':
                        self.restart_service(command, client_socket)
                    elif command.get('action') == 'service_status':
                        self.service_status(command, client_socket)

                    # SCRIPT OPERATIONS
                    elif command.get('action') == 'execute_command':
                        self.execute_command(command, client_socket)
                    elif command.get('action') == 'list_running_scripts':
                        self.list_running_scripts(client_socket)
                    elif command.get('action') == 'kill_script':
                        self.kill_script(command, client_socket)

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    self.send_response(client_socket, {"error": "Invalid JSON"})
                except Exception as e:
                    logger.error(f"Error handling command: {e}")
                    self.send_response(client_socket, {"error": str(e)})

        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
            client_socket.close()
            logger.info(f"Client {client_address} disconnected")

    def send_response(self, client_socket, response):
        """Gửi response về client"""
        try:
            message = json.dumps(response) + "\n"
            client_socket.sendall(message.encode())
        except Exception as e:
            logger.error(f"Error sending response: {e}")

    def broadcast_response(self, response):
        """Gửi response tới tất cả clients"""
        for client in self.clients[:]:
            try:
                self.send_response(client, response)
            except:
                if client in self.clients:
                    self.clients.remove(client)

    # =============================================================================
    # FILE OPERATIONS
    # =============================================================================

    def list_files(self, command, client_socket):
        """List files trong directory"""
        try:
            directory = command.get('directory', '/home/orangepi')
            show_hidden = command.get('show_hidden', False)

            if not os.path.exists(directory):
                self.send_response(client_socket, {
                    'action': 'list_error',
                    'error': 'Directory not found'
                })
                return

            if not os.path.isdir(directory):
                self.send_response(client_socket, {
                    'action': 'list_error',
                    'error': 'Path is not a directory'
                })
                return

            files = []
            for item in os.listdir(directory):
                if not show_hidden and item.startswith('.'):
                    continue

                item_path = os.path.join(directory, item)
                try:
                    stat = os.stat(item_path)
                    file_info = {
                        'name': item,
                        'path': item_path,
                        'is_directory': os.path.isdir(item_path),
                        'size': stat.st_size,
                        'modified': stat.st_mtime,
                        'permissions': oct(stat.st_mode)[-3:]
                    }
                    files.append(file_info)
                except Exception as e:
                    logger.warning(f"Could not stat {item_path}: {e}")

            # Sort: directories first, then files, alphabetically
            files.sort(key=lambda x: (not x['is_directory'], x['name'].lower()))

            self.send_response(client_socket, {
                'action': 'list_success',
                'directory': directory,
                'files': files,
                'total_count': len(files)
            })

        except Exception as e:
            logger.error(f"Error listing files: {e}")
            self.send_response(client_socket, {
                'action': 'list_error',
                'error': str(e)
            })

    def download_file(self, command, client_socket):
        """Download file từ Pi"""
        try:
            file_path = command.get('file_path')

            if not file_path:
                self.send_response(client_socket, {
                    'action': 'download_error',
                    'error': 'Missing file_path'
                })
                return

            if not os.path.exists(file_path):
                self.send_response(client_socket, {
                    'action': 'download_error',
                    'error': 'File not found'
                })
                return

            if os.path.isdir(file_path):
                self.send_response(client_socket, {
                    'action': 'download_error',
                    'error': 'Path is a directory, not a file'
                })
                return

            # Read file and encode to base64
            with open(file_path, 'rb') as f:
                file_content = f.read()

            content_base64 = base64.b64encode(file_content).decode()
            file_stat = os.stat(file_path)

            logger.info(f"File downloaded: {file_path} ({len(file_content)} bytes)")

            self.send_response(client_socket, {
                'action': 'download_success',
                'file_path': file_path,
                'content': content_base64,
                'size': len(file_content),
                'modified': file_stat.st_mtime,
                'permissions': oct(file_stat.st_mode)[-3:]
            })

        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            self.send_response(client_socket, {
                'action': 'download_error',
                'error': str(e)
            })

    def delete_file(self, command, client_socket):
        """Delete file hoặc directory"""
        try:
            file_path = command.get('file_path')
            recursive = command.get('recursive', False)

            if not file_path:
                self.send_response(client_socket, {
                    'action': 'delete_error',
                    'error': 'Missing file_path'
                })
                return

            if not os.path.exists(file_path):
                self.send_response(client_socket, {
                    'action': 'delete_error',
                    'error': 'File or directory not found'
                })
                return

            if os.path.isdir(file_path):
                if recursive:
                    import shutil
                    shutil.rmtree(file_path)
                    logger.info(f"Directory deleted recursively: {file_path}")
                else:
                    os.rmdir(file_path)  # Only works if empty
                    logger.info(f"Empty directory deleted: {file_path}")
            else:
                os.remove(file_path)
                logger.info(f"File deleted: {file_path}")

            self.send_response(client_socket, {
                'action': 'delete_success',
                'file_path': file_path
            })

        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            self.send_response(client_socket, {
                'action': 'delete_error',
                'error': str(e)
            })

    # =============================================================================
    # SERVICE OPERATIONS
    # =============================================================================

    def list_services(self, client_socket):
        """List all systemd services"""
        try:
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--no-pager'],
                capture_output=True,
                text=True
            )

            services = []
            for line in result.stdout.split('\n'):
                if '.service' in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        service_info = {
                            'name': parts[0],
                            'load': parts[1],
                            'active': parts[2],
                            'sub': parts[3],
                            'description': ' '.join(parts[4:]) if len(parts) > 4 else ''
                        }
                        services.append(service_info)

            self.send_response(client_socket, {
                'action': 'services_list',
                'services': services,
                'total_count': len(services)
            })

        except Exception as e:
            logger.error(f"Error listing services: {e}")
            self.send_response(client_socket, {
                'action': 'service_error',
                'error': str(e)
            })

    def start_service(self, command, client_socket):
        """Start systemd service"""
        try:
            service_name = command.get('service_name')

            if not service_name:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': 'Missing service_name'
                })
                return

            result = subprocess.run(
                ['sudo', 'systemctl', 'start', service_name],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                logger.info(f"Service started: {service_name}")
                self.send_response(client_socket, {
                    'action': 'service_success',
                    'operation': 'start',
                    'service_name': service_name,
                    'message': f'Service {service_name} started successfully'
                })
            else:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'operation': 'start',
                    'service_name': service_name,
                    'error': result.stderr
                })

        except Exception as e:
            logger.error(f"Error starting service: {e}")
            self.send_response(client_socket, {
                'action': 'service_error',
                'error': str(e)
            })

    def stop_service(self, command, client_socket):
        """Stop systemd service"""
        try:
            service_name = command.get('service_name')

            if not service_name:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': 'Missing service_name'
                })
                return

            result = subprocess.run(
                ['sudo', 'systemctl', 'stop', service_name],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                logger.info(f"Service stopped: {service_name}")
                self.send_response(client_socket, {
                    'action': 'service_success',
                    'operation': 'stop',
                    'service_name': service_name,
                    'message': f'Service {service_name} stopped successfully'
                })
            else:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'operation': 'stop',
                    'service_name': service_name,
                    'error': result.stderr
                })

        except Exception as e:
            logger.error(f"Error stopping service: {e}")
            self.send_response(client_socket, {
                'action': 'service_error',
                'error': str(e)
            })

    def restart_service(self, command, client_socket):
        """Restart systemd service"""
        try:
            service_name = command.get('service_name')

            if not service_name:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': 'Missing service_name'
                })
                return

            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', service_name],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                logger.info(f"Service restarted: {service_name}")
                self.send_response(client_socket, {
                    'action': 'service_success',
                    'operation': 'restart',
                    'service_name': service_name,
                    'message': f'Service {service_name} restarted successfully'
                })
            else:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'operation': 'restart',
                    'service_name': service_name,
                    'error': result.stderr
                })

        except Exception as e:
            logger.error(f"Error restarting service: {e}")
            self.send_response(client_socket, {
                'action': 'service_error',
                'error': str(e)
            })

    def service_status(self, command, client_socket):
        """Get systemd service status"""
        try:
            service_name = command.get('service_name')

            if not service_name:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': 'Missing service_name'
                })
                return

            # Get status
            status_result = subprocess.run(
                ['systemctl', 'is-active', service_name],
                capture_output=True,
                text=True
            )

            # Get enabled status
            enabled_result = subprocess.run(
                ['systemctl', 'is-enabled', service_name],
                capture_output=True,
                text=True
            )

            # Get detailed status
            detail_result = subprocess.run(
                ['systemctl', 'status', service_name, '--no-pager'],
                capture_output=True,
                text=True
            )

            status_info = {
                'action': 'service_status',
                'service_name': service_name,
                'active_state': status_result.stdout.strip(),
                'enabled_state': enabled_result.stdout.strip(),
                'status_detail': detail_result.stdout,
                'is_running': status_result.stdout.strip() == 'active'
            }

            self.send_response(client_socket, status_info)

        except Exception as e:
            logger.error(f"Error getting service status: {e}")
            self.send_response(client_socket, {
                'action': 'service_error',
                'error': str(e)
            })

    # =============================================================================
    # SCRIPT OPERATIONS
    # =============================================================================

    def execute_command(self, command, client_socket):
        """Execute shell command"""
        try:
            cmd = command.get('command')
            background = command.get('background', False)

            if not cmd:
                self.send_response(client_socket, {
                    'action': 'command_error',
                    'error': 'Missing command'
                })
                return

            if background:
                # Run in background
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                cmd_id = f"cmd_{process.pid}_{int(time.time())}"
                self.running_scripts[cmd_id] = {
                    'process': process,
                    'script_path': cmd,
                    'args': [],
                    'started': time.time()
                }

                logger.info(f"Command started in background: {cmd} (PID: {process.pid})")

                self.send_response(client_socket, {
                    'action': 'command_started',
                    'command_id': cmd_id,
                    'command': cmd,
                    'pid': process.pid
                })

            else:
                # Run and wait for completion
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60  # 1 minute timeout
                )

                logger.info(f"Command executed: {cmd} (exit code: {result.returncode})")

                self.send_response(client_socket, {
                    'action': 'command_completed',
                    'command': cmd,
                    'exit_code': result.returncode,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })

        except subprocess.TimeoutExpired:
            self.send_response(client_socket, {
                'action': 'command_error',
                'error': 'Command execution timeout'
            })
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            self.send_response(client_socket, {
                'action': 'command_error',
                'error': str(e)
            })

    def list_running_scripts(self, client_socket):
        """List all running scripts"""
        try:
            # Clean up finished processes
            finished_scripts = []
            for script_id, script_info in self.running_scripts.items():
                if script_info['process'].poll() is not None:
                    finished_scripts.append(script_id)

            for script_id in finished_scripts:
                del self.running_scripts[script_id]

            # Prepare response
            running_scripts = []
            for script_id, script_info in self.running_scripts.items():
                running_scripts.append({
                    'script_id': script_id,
                    'script_path': script_info['script_path'],
                    'args': script_info['args'],
                    'pid': script_info['process'].pid,
                    'started': script_info['started'],
                    'running_time': time.time() - script_info['started']
                })

            self.send_response(client_socket, {
                'action': 'running_scripts',
                'scripts': running_scripts,
                'total_count': len(running_scripts)
            })

        except Exception as e:
            logger.error(f"Error listing running scripts: {e}")
            self.send_response(client_socket, {
                'action': 'script_error',
                'error': str(e)
            })

    def kill_script(self, command, client_socket):
        """Kill running script"""
        try:
            script_id = command.get('script_id')

            if not script_id:
                self.send_response(client_socket, {
                    'action': 'kill_error',
                    'error': 'Missing script_id'
                })
                return

            if script_id not in self.running_scripts:
                self.send_response(client_socket, {
                    'action': 'kill_error',
                    'error': 'Script not found or already finished'
                })
                return

            script_info = self.running_scripts[script_id]
            process = script_info['process']

            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

            del self.running_scripts[script_id]

            logger.info(f"Script killed: {script_info['script_path']}")

            self.send_response(client_socket, {
                'action': 'kill_success',
                'script_id': script_id,
                'script_path': script_info['script_path']
            })

        except Exception as e:
            logger.error(f"Error killing script: {e}")
            self.send_response(client_socket, {
                'action': 'kill_error',
                'error': str(e)
            })

    def setup_mdns_advertisement(self):
        """Setup mDNS advertisement"""
        try:
            service_content = f"""<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
    <name replace-wildcards="yes">OrangePi System Control %h</name>
    <service>
        <type>_orangepi-system._tcp</type>
        <port>{PORT}</port>
        <txt-record>version=1.0</txt-record>
        <txt-record>service=system-control</txt-record>
    </service>
</service-group>"""

            service_dir = '/etc/avahi/services'
            service_file = f'{service_dir}/orangepi-system.service'

            if os.path.exists(service_dir):
                with open(service_file, 'w') as f:
                    f.write(service_content)
                logger.info("mDNS service advertisement created")

                try:
                    subprocess.run(['systemctl', 'restart', 'avahi-daemon'], capture_output=True)
                except:
                    pass
            else:
                logger.warning("Avahi not available, skipping mDNS advertisement")

        except Exception as e:
            logger.warning(f"Could not setup mDNS: {e}")

    def start_server(self):
        """Start TCP server"""
        # Setup mDNS advertisement
        self.setup_mdns_advertisement()

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORT))
        self.server_socket.listen(5)

        # Get local IP
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        logger.info(f"System Control Service listening on {HOST}:{PORT}")
        logger.info(f"Local IP: {local_ip}")
        logger.info(f"mDNS name: {hostname}.local")

        try:
            while True:
                client_socket, client_address = self.server_socket.accept()
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_address)
                )
                client_thread.daemon = True
                client_thread.start()

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.server_socket:
                self.server_socket.close()

def main():
    service = SystemControlService()
    service.start_server()

if __name__ == "__main__":
    main()
