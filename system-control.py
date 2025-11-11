#!/usr/bin/env python3
"""
Remote Control Service for OrangePi Zero3
Nhận lệnh từ Flutter app qua TCP socket để điều khiển thiết bị
Tương tự như bluetooth-speaker.py nhưng cho remote control
"""

import json
import subprocess
import socket
import threading
import logging
import time
import os
import hashlib
import base64
import sys
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# TCP Server configuration
HOST = '0.0.0.0'
PORT = 8767

# File transfer configuration
ALLOWED_EXTENSIONS = {
    '.py': '/home/orangepi',
    '.sh': '/usr/local/bin',
    '.service': '/etc/systemd/system'
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
CHUNK_SIZE = 64 * 1024  # 64KB chunks
SUDO_PASSWORD = 'orangepi'

class RemoteControlService:
    def __init__(self):
        self.clients = []
        self.server_socket = None

        # Ensure upload directories exist (with proper permissions)
        for ext, directory in ALLOWED_EXTENSIONS.items():
            try:
                if directory == '/home/orangepi':
                    os.makedirs(directory, exist_ok=True)
                # Note: /usr/local/bin and /etc/systemd/system should already exist
                # and need root permissions to write
            except PermissionError:
                logger.warning(f"Cannot create directory {directory} - need root permissions")

    def receive_full_message(self, client_socket):
        """Nhận đầy đủ JSON message từ client"""
        buffer = b""

        try:
            # Nhận data theo chunks
            while True:
                chunk = client_socket.recv(65536)  # 64KB chunks
                if not chunk:
                    logger.warning("No more data received")
                    break

                buffer += chunk
                logger.debug(f"Received chunk: {len(chunk)} bytes, total buffer: {len(buffer)} bytes")

                # Try to decode và parse JSON
                try:
                    message_str = buffer.decode('utf-8')

                    # Thử parse JSON
                    command = json.loads(message_str)
                    logger.info(f"Successfully received complete JSON: {len(message_str)} bytes")
                    return command

                except json.JSONDecodeError as e:
                    # JSON chưa complete, tiếp tục nhận
                    logger.debug(f"Incomplete JSON, continuing... Error: {e}")

                    # Kiểm tra size limit
                    if len(buffer) > 200 * 1024 * 1024:  # 200MB limit
                        logger.error("Message too large, aborting")
                        break
                    continue

                except UnicodeDecodeError:
                    # UTF-8 decode lỗi, có thể data chưa đủ
                    logger.debug("Unicode decode error, continuing...")
                    if len(buffer) > 200 * 1024 * 1024:
                        logger.error("Message too large, aborting")
                        break
                    continue

        except socket.error as e:
            logger.error(f"Socket error while receiving: {e}")
        except Exception as e:
            logger.error(f"Unexpected error receiving message: {e}")

        logger.warning("Failed to receive complete message")
        return None

    def handle_client(self, client_socket, client_address):
        """Xử lý kết nối từ client"""
        logger.info(f"Client connected from {client_address}")
        self.clients.append(client_socket)

        # Set socket timeout to None (no timeout)
        client_socket.settimeout(None)

        try:
            while True:
                command = self.receive_full_message(client_socket)
                if command is None:
                    logger.warning("Received None command, breaking connection")
                    break

                if not isinstance(command, dict):
                    logger.error(f"Invalid command type: {type(command)}")
                    continue

                action = command.get('action', 'unknown')
                logger.info(f"Processing command: {action}")

                try:
                    if action == 'ping':
                        # Respond to ping for device discovery
                        self.send_response(client_socket, {
                            'action': 'pong',
                            'service': 'orangepi-remote-control',
                            'version': '1.0'
                        })
                    elif action == 'upload_file':
                        self.handle_file_upload(command, client_socket)
                    elif action == 'list_files':
                        self.list_uploaded_files(client_socket)
                    elif action == 'execute_script':
                        self.handle_script_execution(command, client_socket)
                    elif action == 'list_services':
                        self.list_custom_services(client_socket)
                    elif action == 'manage_service':
                        self.handle_service_management(command, client_socket)
                    else:
                        logger.warning(f"Unknown action: {action}")
                        self.send_response(client_socket, {
                            "error": f"Unknown action: {action}"
                        })

                except Exception as e:
                    logger.error(f"Error handling command '{action}': {e}")
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

    def write_file_with_sudo(self, file_path, file_data, file_ext):
        """Ghi file với sudo permissions nếu cần"""
        try:
            # Thử ghi file bình thường trước
            with open(file_path, 'wb') as f:
                f.write(file_data)

            # Set executable permissions cho .sh files
            if file_ext == '.sh':
                os.chmod(file_path, 0o755)

            return True, "Success"

        except PermissionError:
            # Nếu không có quyền, dùng sudo
            try:
                logger.info(f"Using sudo to write file to {file_path}")

                # Tạo temp file
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    temp_file.write(file_data)
                    temp_file_path = temp_file.name

                # Copy file với sudo
                copy_cmd = f"echo '{SUDO_PASSWORD}' | sudo -S cp '{temp_file_path}' '{file_path}'"
                result = subprocess.run(copy_cmd, shell=True, capture_output=True, text=True)

                # Cleanup temp file
                os.unlink(temp_file_path)

                if result.returncode == 0:
                    # Set permissions với sudo
                    if file_ext == '.sh':
                        chmod_cmd = f"echo '{SUDO_PASSWORD}' | sudo -S chmod 755 '{file_path}'"
                        subprocess.run(chmod_cmd, shell=True, capture_output=True)

                    return True, "Success with sudo"
                else:
                    return False, f"Sudo failed: {result.stderr}"

            except Exception as e:
                return False, f"Sudo error: {e}"

        except Exception as e:
            return False, f"Write error: {e}"

    def handle_file_upload(self, command, client_socket):
        """Xử lý upload file từ Flutter app"""
        try:
            filename = command.get('filename')
            file_data_b64 = command.get('file_data')
            file_size = command.get('file_size', 0)

            if not filename or not file_data_b64:
                self.send_response(client_socket, {
                    'action': 'upload_error',
                    'error': 'Missing filename or file_data'
                })
                return

            # Check file extension
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in ALLOWED_EXTENSIONS:
                self.send_response(client_socket, {
                    'action': 'upload_error',
                    'error': f'File type not allowed. Allowed: {list(ALLOWED_EXTENSIONS.keys())}'
                })
                return

            # Get destination directory based on file extension
            destination_dir = ALLOWED_EXTENSIONS[file_ext]

            if file_size > MAX_FILE_SIZE:
                self.send_response(client_socket, {
                    'action': 'upload_error',
                    'error': f'File too large. Max size: {MAX_FILE_SIZE} bytes'
                })
                return

            # Decode file data
            try:
                file_data = base64.b64decode(file_data_b64)
                actual_size = len(file_data)

                if file_size > 0 and actual_size != file_size:
                    logger.warning(f"File size mismatch: expected {file_size}, got {actual_size}")

            except Exception as e:
                self.send_response(client_socket, {
                    'action': 'upload_error',
                    'error': f'Invalid base64 data: {e}'
                })
                return

            # Create file path in the appropriate directory
            file_path = os.path.join(destination_dir, filename)

            # Check if file exists (for logging)
            was_overwrite = os.path.exists(file_path)

            # Write file với auto sudo nếu cần
            success, message = self.write_file_with_sudo(file_path, file_data, file_ext)

            if success:
                # Calculate MD5 for verification
                md5_hash = hashlib.md5(file_data).hexdigest()

                action_type = "overwritten" if was_overwrite else "uploaded"
                logger.info(f"File {action_type} successfully: {filename} ({actual_size} bytes) -> {file_path} [{message}]")

                self.send_response(client_socket, {
                    'action': 'upload_success',
                    'filename': filename,
                    'file_path': file_path,
                    'destination_dir': destination_dir,
                    'file_size': actual_size,
                    'md5_hash': md5_hash,
                    'method': message,
                    'overwrite': was_overwrite
                })
            else:
                self.send_response(client_socket, {
                    'action': 'upload_error',
                    'error': f'Failed to write file: {message}'
                })
                return

        except Exception as e:
            logger.error(f"Error handling file upload: {e}")
            self.send_response(client_socket, {
                'action': 'upload_error',
                'error': str(e)
            })

    def list_uploaded_files(self, client_socket):
        """Liệt kê files đã upload từ tất cả directories"""
        try:
            all_files = []

            # List files từ từng directory theo file type
            for file_ext, directory in ALLOWED_EXTENSIONS.items():
                try:
                    if os.path.exists(directory):
                        for filename in os.listdir(directory):
                            file_path = os.path.join(directory, filename)
                            if os.path.isfile(file_path) and filename.endswith(file_ext):
                                stat = os.stat(file_path)
                                all_files.append({
                                    'filename': filename,
                                    'file_path': file_path,
                                    'directory': directory,
                                    'file_type': file_ext,
                                    'size': stat.st_size,
                                    'modified_time': stat.st_mtime,
                                    'created_time': stat.st_ctime,
                                    'permissions': oct(stat.st_mode)[-3:]
                                })
                except PermissionError:
                    logger.warning(f"Cannot access directory {directory}")
                    continue

            self.send_response(client_socket, {
                'action': 'file_list',
                'files': all_files,
                'directories': ALLOWED_EXTENSIONS,
                'total_files': len(all_files)
            })

        except Exception as e:
            logger.error(f"Error listing files: {e}")
            self.send_response(client_socket, {
                'action': 'file_list_error',
                'error': str(e)
            })

    def handle_script_execution(self, command, client_socket):
        """Thực thi script trên thiết bị"""
        try:
            script_path = command.get('script_path')

            if not script_path:
                self.send_response(client_socket, {
                    'action': 'script_error',
                    'error': 'Missing script_path'
                })
                return

            # Kiểm tra file script có tồn tại không
            if not os.path.exists(script_path):
                self.send_response(client_socket, {
                    'action': 'script_error',
                    'error': f'Script not found: {script_path}'
                })
                return

            logger.info(f"Executing script: {script_path}")

            # Thực thi script
            try:
                result = subprocess.run(
                    ['bash', script_path],
                    capture_output=True,
                    text=True,
                    timeout=30  # 30 seconds timeout
                )

                self.send_response(client_socket, {
                    'action': 'script_success',
                    'script_path': script_path,
                    'return_code': result.returncode,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })

                logger.info(f"Script executed successfully: {script_path} (exit code: {result.returncode})")

            except subprocess.TimeoutExpired:
                self.send_response(client_socket, {
                    'action': 'script_error',
                    'error': 'Script execution timeout (30s)'
                })
                logger.error(f"Script timeout: {script_path}")

            except Exception as e:
                self.send_response(client_socket, {
                    'action': 'script_error',
                    'error': f'Execution failed: {e}'
                })
                logger.error(f"Script execution error: {e}")

        except Exception as e:
            logger.error(f"Error handling script execution: {e}")
            self.send_response(client_socket, {
                'action': 'script_error',
                'error': str(e)
            })

    def list_custom_services(self, client_socket):
        """Liệt kê custom services từ /etc/systemd/system/"""
        try:
            services = []
            systemd_dir = '/etc/systemd/system'

            if os.path.exists(systemd_dir):
                # Danh sách service cần lọc (hệ thống)
                system_services = {
                    'dbus.service', 'systemd-', 'getty@', 'network', 'ssh', 'bluetooth',
                    'avahi-', 'cups-', 'plymouth-', 'udev-', 'ModemManager', 'NetworkManager',
                    'accounts-daemon', 'polkit', 'udisks2', 'packagekit', 'snapd',
                    'rsyslog', 'cron', 'atd', 'smartmontools', 'thermald'
                }

                for filename in os.listdir(systemd_dir):
                    if filename.endswith('.service'):
                        # Bỏ qua system services
                        is_system = any(sys_service in filename for sys_service in system_services)
                        if is_system:
                            continue

                        service_path = os.path.join(systemd_dir, filename)
                        if os.path.isfile(service_path):
                            try:
                                # Lấy status service
                                result = subprocess.run(
                                    ['systemctl', 'is-active', filename],
                                    capture_output=True,
                                    text=True
                                )
                                status = result.stdout.strip()

                                # Lấy enabled status
                                enabled_result = subprocess.run(
                                    ['systemctl', 'is-enabled', filename],
                                    capture_output=True,
                                    text=True
                                )
                                enabled = enabled_result.stdout.strip()

                                # Đọc description từ service file
                                description = "Custom service"
                                try:
                                    with open(service_path, 'r') as f:
                                        content = f.read()
                                        for line in content.split('\n'):
                                            if line.strip().startswith('Description='):
                                                description = line.split('=', 1)[1].strip()
                                                break
                                except:
                                    pass

                                services.append({
                                    'name': filename,
                                    'status': status,
                                    'enabled': enabled,
                                    'description': description,
                                    'path': service_path
                                })

                            except Exception as e:
                                logger.warning(f"Could not get status for {filename}: {e}")
                                services.append({
                                    'name': filename,
                                    'status': 'unknown',
                                    'enabled': 'unknown',
                                    'description': 'Custom service',
                                    'path': service_path
                                })

            self.send_response(client_socket, {
                'action': 'services_list',
                'services': services,
                'total': len(services)
            })

            logger.info(f"Listed {len(services)} custom services")

        except Exception as e:
            logger.error(f"Error listing services: {e}")
            self.send_response(client_socket, {
                'action': 'services_error',
                'error': str(e)
            })

    def handle_service_management(self, command, client_socket):
        """Quản lý services (start/stop/restart)"""
        try:
            service_name = command.get('service_name')
            service_action = command.get('service_action')

            if not service_name or not service_action:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': 'Missing service_name or service_action'
                })
                return

            # Validate action
            valid_actions = ['start', 'stop', 'restart', 'status', 'enable', 'disable']
            if service_action not in valid_actions:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': f'Invalid action. Valid actions: {valid_actions}'
                })
                return

            # Validate service exists
            service_path = f'/etc/systemd/system/{service_name}'
            if not os.path.exists(service_path):
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': f'Service {service_name} not found'
                })
                return

            logger.info(f"Managing service: {service_name} -> {service_action}")

            # Execute systemctl command with sudo
            try:
                if service_action == 'status':
                    cmd = ['systemctl', 'status', service_name]
                else:
                    cmd = ['sudo', 'systemctl', service_action, service_name]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                # Get current status after action
                status_result = subprocess.run(
                    ['systemctl', 'is-active', service_name],
                    capture_output=True,
                    text=True
                )
                current_status = status_result.stdout.strip()

                self.send_response(client_socket, {
                    'action': 'service_success',
                    'service_name': service_name,
                    'service_action': service_action,
                    'return_code': result.returncode,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'current_status': current_status
                })

                logger.info(f"Service {service_name} {service_action} completed (exit: {result.returncode})")

            except subprocess.TimeoutExpired:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': 'Service operation timeout (30s)'
                })

            except Exception as e:
                self.send_response(client_socket, {
                    'action': 'service_error',
                    'error': f'Operation failed: {e}'
                })

        except Exception as e:
            logger.error(f"Error handling service management: {e}")
            self.send_response(client_socket, {
                'action': 'service_error',
                'error': str(e)
            })

    def setup_mdns_advertisement(self):
        """Setup mDNS advertisement để Flutter app có thể tự động tìm thấy"""
        try:
            # Tạo file avahi service
            service_content = f"""<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
    <name replace-wildcards="yes">OrangePi Remote Control %h</name>
    <service>
        <type>_orangepi-remote._tcp</type>
        <port>{PORT}</port>
        <txt-record>version=1.0</txt-record>
        <txt-record>service=remote-control</txt-record>
    </service>
</service-group>"""

            # Ghi file service
            service_dir = '/etc/avahi/services'
            service_file = f'{service_dir}/orangepi-remote.service'

            if os.path.exists(service_dir):
                with open(service_file, 'w') as f:
                    f.write(service_content)
                logger.info("mDNS service advertisement created")

                # Restart avahi để load service mới
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
        logger.info("Initializing Remote Control service...")

        # Setup mDNS advertisement
        self.setup_mdns_advertisement()

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORT))
        self.server_socket.listen(5)

        # Lấy IP thực tế
        hostname = socket.gethostname()
        try:
            # Connect to a remote address to get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = socket.gethostbyname(hostname)

        print(f"\n{'='*60}")
        print(f"🚀 Remote Control Service STARTED")
        print(f"{'='*60}")
        print(f"📡 Listening on: {HOST}:{PORT}")
        print(f"🌐 Local IP: {local_ip}")
        print(f"🏠 Hostname: {hostname}")
        print(f"📱 Flutter app connect to: {local_ip}:{PORT}")
        print(f"")
        print(f"📁 File Upload Restrictions:")
        for ext, directory in ALLOWED_EXTENSIONS.items():
            print(f"   {ext:<10} → {directory}")
        print(f"📦 Max file size: {MAX_FILE_SIZE // (1024*1024)}MB")
        print(f"🔐 Auto sudo: Enabled (password configured)")
        print(f"{'='*60}\n")

        logger.info(f"Remote Control Service listening on {HOST}:{PORT}")
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
    service = RemoteControlService()
    service.start_server()

if __name__ == "__main__":
    main()
