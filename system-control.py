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
UPLOAD_DIR = '/home/orangepi'
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
CHUNK_SIZE = 64 * 1024  # 64KB chunks

class RemoteControlService:
    def __init__(self):
        self.clients = []
        self.server_socket = None

        # Ensure upload directory exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)

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

        # Set socket timeout
        client_socket.settimeout(60.0)  # 60 seconds timeout

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

            # Create file path
            file_path = os.path.join(UPLOAD_DIR, filename)

            # Check if file already exists, create unique name if needed
            if os.path.exists(file_path):
                name, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(file_path):
                    new_filename = f"{name}_{counter}{ext}"
                    file_path = os.path.join(UPLOAD_DIR, new_filename)
                    counter += 1
                filename = os.path.basename(file_path)

            # Write file
            with open(file_path, 'wb') as f:
                f.write(file_data)

            # Calculate MD5 for verification
            md5_hash = hashlib.md5(file_data).hexdigest()

            logger.info(f"File uploaded successfully: {filename} ({actual_size} bytes)")

            self.send_response(client_socket, {
                'action': 'upload_success',
                'filename': filename,
                'file_path': file_path,
                'file_size': actual_size,
                'md5_hash': md5_hash
            })

        except Exception as e:
            logger.error(f"Error handling file upload: {e}")
            self.send_response(client_socket, {
                'action': 'upload_error',
                'error': str(e)
            })

    def list_uploaded_files(self, client_socket):
        """Liệt kê files đã upload"""
        try:
            if not os.path.exists(UPLOAD_DIR):
                files = []
            else:
                files = []
                for filename in os.listdir(UPLOAD_DIR):
                    file_path = os.path.join(UPLOAD_DIR, filename)
                    if os.path.isfile(file_path):
                        stat = os.stat(file_path)
                        files.append({
                            'filename': filename,
                            'file_path': file_path,
                            'size': stat.st_size,
                            'modified_time': stat.st_mtime,
                            'created_time': stat.st_ctime
                        })

            self.send_response(client_socket, {
                'action': 'file_list',
                'files': files,
                'upload_dir': UPLOAD_DIR,
                'total_files': len(files)
            })

        except Exception as e:
            logger.error(f"Error listing files: {e}")
            self.send_response(client_socket, {
                'action': 'file_list_error',
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

        print(f"\n{'='*50}")
        print(f"🚀 Remote Control Service STARTED")
        print(f"{'='*50}")
        print(f"📡 Listening on: {HOST}:{PORT}")
        print(f"🌐 Local IP: {local_ip}")
        print(f"🏠 Hostname: {hostname}")
        print(f"📱 Flutter app connect to: {local_ip}:{PORT}")
        print(f"{'='*50}\n")

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
