#!/usr/bin/env python3
"""
Bluetooth Speaker Service for OrangePi Zero3
Nhận lệnh từ Flutter app qua TCP socket để kết nối/disconnect loa Bluetooth
Sử dụng bluetoothctl và pactl có sẵn trên Debian 12
"""

import json
import subprocess
import socket
import threading
import logging
import time
import os
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# TCP Server configuration
HOST = '0.0.0.0'
PORT = 8765

class BluetoothSpeakerService:
    def __init__(self):
        self.connected_speakers = []
        self.clients = []
        self.server_socket = None
        self.monitoring_enabled = True
        self.last_known_devices = {}  # Track device states
        self.monitoring_thread = None

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
                            'service': 'orangepi-bluetooth-speaker',
                            'version': '1.0'
                        })
                    elif command.get('action') == 'scan_speakers':
                        self.scan_bluetooth_speakers(client_socket)
                    elif command.get('action') == 'connect_speaker':
                        mac_address = command.get('mac_address')
                        self.connect_speaker(mac_address, client_socket)
                    elif command.get('action') == 'disconnect_speaker':
                        mac_address = command.get('mac_address')
                        self.disconnect_speaker(mac_address, client_socket)
                    elif command.get('action') == 'list_speakers':
                        self.list_connected_speakers(client_socket)
                    elif command.get('action') == 'auto_reconnect':
                        # Manual trigger auto-reconnect từ app
                        threading.Thread(target=self.auto_reconnect_paired_devices, daemon=True).start()
                        self.send_response(client_socket, {
                            'action': 'auto_reconnect_started',
                            'message': 'Auto-reconnect process started'
                        })

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

    def set_bluetooth_as_default_sink(self, mac_address, device_name=None):
        """Set Bluetooth device làm default audio sink trong PulseAudio"""
        try:
            mac_formatted = mac_address.replace(":", "_")
            logger.info(f"Setting Bluetooth device {mac_address} as default sink...")
            logger.info(f"Device name: {device_name}")

            # Đợi PulseAudio nhận diện thiết bị
            max_retries = 10
            for retry in range(max_retries):
                # Lấy danh sách sinks
                pa_result = subprocess.run(
                    ['pactl', 'list', 'short', 'sinks'],
                    capture_output=True,
                    text=True
                )

                logger.info(f"Retry {retry+1}/{max_retries}: Available sinks:\n{pa_result.stdout}")
                logger.info(f"Looking for MAC: {mac_formatted} or device name: {device_name}")

                # Tìm sink của Bluetooth device
                found_sink = None
                best_match_score = 0

                for line in pa_result.stdout.split('\n'):
                    if line.strip() and 'bluez' in line.lower():
                        # Split bằng whitespace
                        # Format: [index] [sink-name] [module] [sample-spec] [state]
                        # Example: 2    bluez_sink.XX_XX_XX_XX_XX_XX.a2dp_sink    module-bluez5-device.c    ...
                        parts = line.split()
                        if len(parts) >= 2:
                            sink_name = parts[1]  # ✅ Cột thứ 2 là sink name
                            sink_lower = sink_name.lower()
                            logger.debug(f"Checking Bluetooth sink: {sink_name}")

                            match_score = 0

                            # ✅ Check 1: MAC address trong sink name (ưu tiên cao nhất)
                            if mac_formatted.lower() in sink_lower:
                                match_score = 100
                                logger.info(f"✅ Match by MAC address: {sink_name}")

                            # ✅ Check 2: Device name trong sink name
                            elif device_name:
                                # Thử nhiều format của device name
                                device_variants = [
                                    device_name.replace(" ", "_"),
                                    device_name.replace(" ", "-"),
                                    device_name.replace("-", "_"),
                                    device_name  # Giữ nguyên
                                ]
                                for variant in device_variants:
                                    if variant.lower() in sink_lower:
                                        match_score = 80
                                        logger.info(f"✅ Match by device name variant '{variant}': {sink_name}")
                                        break

                            # ✅ Check 3: Chỉ cần có "bluez_sink" và là sink duy nhất
                            elif 'bluez_sink' in sink_lower or 'bluez_output' in sink_lower:
                                match_score = 50
                                logger.info(f"⚠️ Fallback match (bluez sink found): {sink_name}")

                            # Chọn sink có điểm cao nhất
                            if match_score > best_match_score:
                                best_match_score = match_score
                                found_sink = sink_name
                                logger.info(f"Current best match (score {match_score}): {found_sink}")

                                # Nếu tìm thấy perfect match (MAC address), không cần tìm nữa
                                if match_score == 100:
                                    break

                if found_sink and best_match_score >= 50:  # Chỉ chấp nhận match score >= 50
                    # Set as default sink
                    logger.info(f"Attempting to set {found_sink} as default sink...")
                    set_result = subprocess.run(
                        ['pactl', 'set-default-sink', found_sink],
                        capture_output=True,
                        text=True
                    )

                    if set_result.returncode == 0:
                        logger.info(f"✅ Successfully set {found_sink} as default audio sink")

                        # Chuyển tất cả audio streams sang sink mới
                        self.move_all_streams_to_sink(found_sink)

                        # Verify
                        verify_result = subprocess.run(
                            ['pactl', 'get-default-sink'],
                            capture_output=True,
                            text=True
                        )
                        logger.info(f"Current default sink: {verify_result.stdout.strip()}")
                        return True
                    else:
                        logger.error(f"❌ Failed to set default sink!")
                        logger.error(f"Return code: {set_result.returncode}")
                        logger.error(f"Stderr: {set_result.stderr}")
                        logger.error(f"Stdout: {set_result.stdout}")
                        return False

                # Nếu chưa tìm thấy hoặc match score thấp, đợi một chút
                elif not found_sink or best_match_score < 50:
                    if retry < max_retries - 1:
                        logger.info(f"No suitable Bluetooth sink found yet (best score: {best_match_score}). Waiting... ({retry+1}/{max_retries})")
                        time.sleep(2)

            logger.warning(f"Could not find PulseAudio sink for device {mac_address} after {max_retries} retries")
            # Không set gì, giữ nguyên default hiện tại (HDMI)
            return False

        except Exception as e:
            logger.error(f"Error setting default sink: {e}")
            # Không set gì, giữ nguyên default hiện tại (HDMI)
            return False

    def set_default_to_audiocodec(self):
        """Set default sink về HDMI (LUÔN LUÔN ưu tiên HDMI)"""
        try:
            logger.info("Setting default audio sink to HDMI (always prioritize HDMI)...")

            # Lấy danh sách sinks
            pa_result = subprocess.run(
                ['pactl', 'list', 'short', 'sinks'],
                capture_output=True,
                text=True
            )

            logger.info(f"Available sinks:\n{pa_result.stdout}")

            # Tìm HDMI sink (LUÔN LUÔN ưu tiên HDMI)
            hdmi_sink = None

            for line in pa_result.stdout.split('\n'):
                if line.strip() and 'bluez' not in line.lower():  # Bỏ qua Bluetooth
                    # Split bằng whitespace
                    # Format: [index] [sink-name] [module] [sample-spec] [state]
                    # Example: 1    HDMI-Playback    module-alsa-sink.c    s16le 2ch 44100Hz    SUSPENDED
                    parts = line.split()
                    if len(parts) >= 2:
                        sink_name = parts[1]  # ✅ Cột thứ 2 là sink name
                        logger.debug(f"Checking sink: {sink_name}")

                        # ✅ LUÔN LUÔN tìm HDMI
                        if 'hdmi' in sink_name.lower():
                            hdmi_sink = sink_name
                            logger.info(f"✅ Found HDMI sink: {hdmi_sink}")
                            break  # Tìm thấy HDMI thì dừng luôn

            # ✅ CHỈ dùng HDMI, KHÔNG dùng AudioCodec
            default_sink = hdmi_sink

            if default_sink:
                set_result = subprocess.run(
                    ['pactl', 'set-default-sink', default_sink],
                    capture_output=True,
                    text=True
                )
                if set_result.returncode == 0:
                    logger.info(f"✅ Set default audio sink to HDMI: {default_sink}")
                    self.move_all_streams_to_sink(default_sink)

                    # Verify
                    verify_result = subprocess.run(
                        ['pactl', 'get-default-sink'],
                        capture_output=True,
                        text=True
                    )
                    logger.info(f"Verified current default sink: {verify_result.stdout.strip()}")
                    return True
                else:
                    logger.error(f"❌ Failed to set HDMI as default sink!")
                    logger.error(f"Stderr: {set_result.stderr}")
                    return False
            else:
                logger.error("❌ HDMI sink NOT FOUND! Available sinks:")
                logger.error(pa_result.stdout)
                return False

        except Exception as e:
            logger.error(f"Error setting default sink: {e}")
            return False

    def move_all_streams_to_sink(self, sink_name):
        """Di chuyển tất cả audio streams sang sink mới"""
        try:
            # Lấy danh sách các sink inputs
            list_result = subprocess.run(
                ['pactl', 'list', 'short', 'sink-inputs'],
                capture_output=True,
                text=True
            )

            # Di chuyển từng stream
            for line in list_result.stdout.split('\n'):
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 1:
                        input_id = parts[0]
                        subprocess.run(
                            ['pactl', 'move-sink-input', input_id, sink_name],
                            capture_output=True
                        )
                        logger.info(f"Moved audio stream {input_id} to {sink_name}")

        except Exception as e:
            logger.warning(f"Could not move audio streams: {e}")

    def force_set_hdmi_fallback(self):
        """
        Fallback method mạnh mẽ hơn để force set HDMI
        Sử dụng khi method chính thất bại
        """
        try:
            logger.info("🔧 [FALLBACK] Attempting to force HDMI audio output...")

            # Method 1: Tìm tất cả sinks và force set HDMI
            all_sinks = subprocess.run(
                ['pactl', 'list', 'short', 'sinks'],
                capture_output=True,
                text=True
            )
            logger.info(f"[FALLBACK] All available sinks:\n{all_sinks.stdout}")

            # CHỈ tìm HDMI sink
            hdmi_sinks = []
            for line in all_sinks.stdout.split('\n'):
                if line.strip() and 'bluez' not in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        sink_name = parts[1]
                        if 'hdmi' in sink_name.lower():
                            hdmi_sinks.append(sink_name)
                            logger.info(f"[FALLBACK] Found HDMI sink: {sink_name}")

            # Dùng HDMI sink đầu tiên
            if hdmi_sinks:
                target_sink = hdmi_sinks[0]
                logger.info(f"[FALLBACK] Using HDMI sink: {target_sink}")

                # Set as default
                set_result = subprocess.run(
                    ['pactl', 'set-default-sink', target_sink],
                    capture_output=True,
                    text=True
                )

                if set_result.returncode == 0:
                    logger.info(f"✅ [FALLBACK] Successfully set {target_sink} as default")

                    # Move all streams
                    self.move_all_streams_to_sink(target_sink)

                    # Verify
                    verify_result = subprocess.run(
                        ['pactl', 'get-default-sink'],
                        capture_output=True,
                        text=True
                    )
                    logger.info(f"[FALLBACK] Current default sink: {verify_result.stdout.strip()}")
                    return True
                else:
                    logger.error(f"❌ [FALLBACK] Failed to set default sink: {set_result.stderr}")
            else:
                logger.error("❌ [FALLBACK] No HDMI sink found!")
                return False

            # Method 2: If all fails, restart PulseAudio
            logger.warning("🔄 [FALLBACK] Attempting PulseAudio restart...")
            restart_result = subprocess.run(
                ['pulseaudio', '--kill'],
                capture_output=True,
                text=True
            )
            time.sleep(2)
            start_result = subprocess.run(
                ['pulseaudio', '--start'],
                capture_output=True,
                text=True
            )

            if start_result.returncode == 0:
                logger.info("✅ [FALLBACK] PulseAudio restarted")
                time.sleep(3)
                # Try setting HDMI again
                return self.set_default_to_audiocodec()

            return False

        except Exception as e:
            logger.error(f"❌ [FALLBACK] Error: {e}")
            return False

    def get_current_default_sink(self):
        """Lấy default sink hiện tại từ PulseAudio"""
        try:
            result = subprocess.run(
                ['pactl', 'get-default-sink'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.error(f"Error getting default sink: {e}")
            return None

    def scan_bluetooth_speakers(self, client_socket):
        """Scan và tìm loa Bluetooth"""
        try:
            logger.info("Scanning for Bluetooth speakers...")

            # Đảm bảo Bluetooth đã bật
            subprocess.run(['bluetoothctl', 'power', 'on'], capture_output=True)

            # Setup agent
            subprocess.run(['bluetoothctl', 'agent', 'on'], capture_output=True)
            subprocess.run(['bluetoothctl', 'default-agent'], capture_output=True)
            subprocess.run(['bluetoothctl', 'discoverable', 'on'], capture_output=True)
            subprocess.run(['bluetoothctl', 'pairable', 'on'], capture_output=True)

            logger.info("Starting scan without disconnecting existing devices...")

            # Dừng scan cũ nếu có
            subprocess.run(['bluetoothctl', 'scan', 'off'], capture_output=True)

            # Bắt đầu scan mới
            logger.info("Starting Bluetooth scan...")
            scan_proc = subprocess.Popen(
                ['bluetoothctl', 'scan', 'on'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Đợi scan 15 giây
            time.sleep(15)

            # Dừng scan
            scan_proc.terminate()
            subprocess.run(['bluetoothctl', 'scan', 'off'], capture_output=True)

            # Lấy danh sách devices
            result = subprocess.run(
                ['bluetoothctl', 'devices'],
                capture_output=True,
                text=True
            )

            devices = []
            for line in result.stdout.split('\n'):
                if line.strip() and 'Device' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        mac = parts[1]
                        name = ' '.join(parts[2:])

                        # Lấy thêm info của device
                        info_result = subprocess.run(
                            ['bluetoothctl', 'info', mac],
                            capture_output=True,
                            text=True
                        )

                        logger.info(f"Found device: {name} ({mac})")

                        # Lấy thông tin cơ bản
                        device_type = 'unknown'
                        if 'Audio Sink' in info_result.stdout or 'Audio Source' in info_result.stdout:
                            device_type = 'audio'
                        elif 'Headset' in info_result.stdout or 'A2DP' in info_result.stdout:
                            device_type = 'headset'
                        elif 'Mouse' in info_result.stdout or 'Keyboard' in info_result.stdout:
                            device_type = 'input'
                        elif 'Phone' in info_result.stdout:
                            device_type = 'phone'

                        device_info = {
                            'mac': mac,
                            'name': name,
                            'type': device_type
                        }
                        devices.append(device_info)

            response = {
                'action': 'scan_result',
                'devices': devices
            }

            self.send_response(client_socket, response)

        except Exception as e:
            logger.error(f"Error scanning speakers: {e}")
            self.send_response(client_socket, {
                'action': 'scan_error',
                'error': str(e)
            })

    def connect_speaker(self, mac_address, client_socket):
        """Kết nối tới loa Bluetooth"""
        try:
            logger.info(f"Connecting to speaker: {mac_address}")

            # Lấy tên thiết bị trước
            device_name = None
            info_result = subprocess.run(
                ['bluetoothctl', 'info', mac_address],
                capture_output=True,
                text=True
            )
            for line in info_result.stdout.split('\n'):
                if 'Name:' in line:
                    device_name = line.split('Name:')[1].strip()
                    break

            # Trust device
            subprocess.run(['bluetoothctl', 'trust', mac_address], capture_output=True)

            # Pair device nếu chưa pair
            pair_result = subprocess.run(
                ['bluetoothctl', 'pair', mac_address],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Connect device
            connect_result = subprocess.run(
                ['bluetoothctl', 'connect', mac_address],
                capture_output=True,
                text=True,
                timeout=20
            )

            if 'Connection successful' in connect_result.stdout or connect_result.returncode == 0:
                # Đợi kết nối ổn định
                time.sleep(3)

                # Set as default audio sink
                self.set_bluetooth_as_default_sink(mac_address, device_name)

                if mac_address not in self.connected_speakers:
                    self.connected_speakers.append(mac_address)

                response = {
                    'action': 'connect_result',
                    'status': 'connected',
                    'mac_address': mac_address,
                    'device_name': device_name
                }
                self.send_response(client_socket, response)
                logger.info(f"Successfully connected to {device_name} ({mac_address})")
            else:
                response = {
                    'action': 'connect_result',
                    'status': 'failed',
                    'mac_address': mac_address,
                    'error': connect_result.stderr
                }
                self.send_response(client_socket, response)
                logger.error(f"Failed to connect to {mac_address}")

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout connecting to {mac_address}")
            self.send_response(client_socket, {
                'action': 'connect_result',
                'status': 'timeout',
                'mac_address': mac_address
            })
        except Exception as e:
            logger.error(f"Error connecting speaker: {e}")
            self.send_response(client_socket, {
                'action': 'connect_error',
                'error': str(e),
                'mac_address': mac_address
            })

    def disconnect_speaker(self, mac_address, client_socket):
        """Ngắt kết nối loa Bluetooth"""
        try:
            logger.info(f"Disconnecting speaker: {mac_address}")

            result = subprocess.run(
                ['bluetoothctl', 'disconnect', mac_address],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                if mac_address in self.connected_speakers:
                    self.connected_speakers.remove(mac_address)

                # ✅ Set default sink về HDMI sau khi disconnect Bluetooth
                self.set_default_to_audiocodec()

                response = {
                    'action': 'disconnect_result',
                    'status': 'disconnected',
                    'mac_address': mac_address
                }
                self.send_response(client_socket, response)
                logger.info(f"✅ Successfully disconnected from {mac_address}")

                # Đợi một chút để PulseAudio cập nhật
                time.sleep(2)

                # ✅ Set default sink về HDMI sau khi disconnect Bluetooth
                logger.info("Setting audio back to HDMI after Bluetooth disconnect...")
                hdmi_success = self.set_default_to_audiocodec()

                if not hdmi_success:
                    logger.warning("Primary HDMI method failed, trying fallback...")
                    fallback_success = self.force_set_hdmi_fallback()
                    if not fallback_success:
                        logger.error("❌ All HDMI setting methods failed!")
                else:
                    logger.info("✅ Successfully set audio back to HDMI")
            else:
                response = {
                    'action': 'disconnect_result',
                    'status': 'failed',
                    'mac_address': mac_address,
                    'error': result.stderr
                }
                self.send_response(client_socket, response)

        except Exception as e:
            logger.error(f"Error disconnecting speaker: {e}")
            self.send_response(client_socket, {
                'action': 'disconnect_error',
                'error': str(e),
                'mac_address': mac_address
            })

    def list_connected_speakers(self, client_socket):
        """Liệt kê loa đã kết nối"""
        try:
            connected_devices = []
            all_paired_devices = []
            all_devices = []

            # Lấy tất cả devices
            all_devices_result = subprocess.run(
                ['bluetoothctl', 'devices'],
                capture_output=True,
                text=True
            )
            logger.info(f"All devices output: {all_devices_result.stdout}")

            # Lấy danh sách paired devices
            paired_result = subprocess.run(
                ['bluetoothctl', 'paired-devices'],
                capture_output=True,
                text=True
            )
            logger.info(f"Paired devices output: {paired_result.stdout}")

            # Xử lý tất cả devices
            for line in all_devices_result.stdout.split('\n'):
                if line.strip() and 'Device' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        mac = parts[1]
                        name = ' '.join(parts[2:])

                        # Kiểm tra connection status và device info
                        info_result = subprocess.run(
                            ['bluetoothctl', 'info', mac],
                            capture_output=True,
                            text=True
                        )

                        logger.info(f"=== Device: {name} ({mac}) ===")
                        logger.debug(f"Info output: {info_result.stdout}")

                        is_connected = 'Connected: yes' in info_result.stdout
                        is_paired = 'Paired: yes' in info_result.stdout
                        is_trusted = 'Trusted: yes' in info_result.stdout

                        # Detect device type
                        device_type = 'unknown'
                        if 'Audio Sink' in info_result.stdout or 'Audio Source' in info_result.stdout:
                            device_type = 'audio'
                        elif 'Headset' in info_result.stdout or 'A2DP' in info_result.stdout:
                            device_type = 'headset'
                        elif 'Mouse' in info_result.stdout or 'Keyboard' in info_result.stdout:
                            device_type = 'input'
                        elif 'Phone' in info_result.stdout:
                            device_type = 'phone'

                        logger.info(f"Device: {name} - Connected: {is_connected}, Paired: {is_paired}, Type: {device_type}")

                        # Lấy thêm thông tin battery nếu có
                        battery_level = None
                        for info_line in info_result.stdout.split('\n'):
                            if 'Battery Percentage' in info_line:
                                try:
                                    battery_level = int(info_line.split('(')[1].split(')')[0])
                                except:
                                    pass

                        device_info = {
                            'mac': mac,
                            'name': name,
                            'connected': is_connected,
                            'paired': is_paired,
                            'type': device_type,
                            'battery': battery_level,
                            'trusted': is_trusted
                        }

                        all_devices.append(device_info)

                        if is_paired:
                            all_paired_devices.append(device_info)

                        if is_connected:
                            connected_devices.append(device_info)

            # Kiểm tra audio sink hiện tại
            current_sink = None
            sink_result = subprocess.run(
                ['pactl', 'get-default-sink'],
                capture_output=True,
                text=True
            )
            if sink_result.returncode == 0:
                current_sink = sink_result.stdout.strip()

            # Kiểm tra thêm từ PulseAudio
            pa_sinks_result = subprocess.run(
                ['pactl', 'list', 'short', 'sinks'],
                capture_output=True,
                text=True
            )
            logger.info(f"PulseAudio sinks: {pa_sinks_result.stdout}")

            response = {
                'action': 'connected_speakers',
                'connected_devices': connected_devices,
                'all_paired_devices': all_paired_devices,
                'all_devices': all_devices,
                'current_audio_sink': current_sink,
                'pulseaudio_sinks': pa_sinks_result.stdout,
                'total_connected': len(connected_devices),
                'total_paired': len(all_paired_devices),
                'total_all': len(all_devices)
            }

            self.send_response(client_socket, response)
            logger.info(f"Found {len(connected_devices)} connected, {len(all_paired_devices)} paired, {len(all_devices)} total devices")

        except Exception as e:
            logger.error(f"Error listing speakers: {e}")
            self.send_response(client_socket, {
                'action': 'list_error',
                'error': str(e)
            })

    def setup_mdns_advertisement(self):
        """Setup mDNS advertisement để Flutter app có thể tự động tìm thấy"""
        try:
            # Tạo file avahi service
            service_content = f"""<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
    <name replace-wildcards="yes">OrangePi Bluetooth Speaker %h</name>
    <service>
        <type>_orangepi-speaker._tcp</type>
        <port>{PORT}</port>
        <txt-record>version=1.0</txt-record>
        <txt-record>service=bluetooth-speaker</txt-record>
    </service>
</service-group>"""

            # Ghi file service
            service_dir = '/etc/avahi/services'
            service_file = f'{service_dir}/orangepi-speaker.service'

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

    def monitor_pulseaudio_events(self):
        """
        Monitor PulseAudio events để detect khi Bluetooth sink biến mất ngay lập tức
        Đây là layer bảo vệ thứ 2 - nhanh hơn Bluetooth monitoring
        """
        logger.info("🎵 Starting PulseAudio event monitoring...")

        # Đợi system ổn định
        time.sleep(20)

        while self.monitoring_enabled:
            try:
                # Sử dụng pactl subscribe để lắng nghe events real-time
                logger.info("Starting pactl subscribe for real-time sink monitoring...")

                # Start pactl subscribe process
                proc = subprocess.Popen(
                    ['pactl', 'subscribe'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1  # Line buffered
                )

                last_check = time.time()

                # Read events from pactl subscribe
                for line in proc.stdout:
                    if not self.monitoring_enabled:
                        proc.terminate()
                        break

                    line = line.strip()

                    # Detect sink-related events
                    if 'sink' in line.lower() or 'server' in line.lower():
                        logger.debug(f"PulseAudio event: {line}")

                        # Throttle checks (không check quá nhanh)
                        now = time.time()
                        if now - last_check < 2:  # Chỉ check mỗi 2 giây
                            continue

                        last_check = now

                        # Check default sink hiện tại
                        current_sink = self.get_current_default_sink()

                        if current_sink:
                            logger.debug(f"Current default sink: {current_sink}")

                            # Nếu sink là Bluetooth
                            if 'bluez' in current_sink.lower():
                                # Verify xem có Bluetooth device nào đang connected không
                                device_states = self.get_current_device_states()
                                has_active_bt = any(
                                    state['connected'] and state['is_audio']
                                    for state in device_states.values()
                                )

                                # Nếu KHÔNG có BT device nào connected => orphaned sink
                                if not has_active_bt:
                                    logger.warning(f"⚠️ [Event Monitor] Orphaned Bluetooth sink detected: {current_sink}")
                                    logger.info("🔧 [Event Monitor] Forcing HDMI...")

                                    if self.set_default_to_audiocodec():
                                        logger.info("✅ [Event Monitor] HDMI set successfully")
                                    else:
                                        logger.error("❌ [Event Monitor] Failed to set HDMI, trying fallback...")
                                        self.force_set_hdmi_fallback()

            except Exception as e:
                logger.error(f"Error in PulseAudio event monitoring: {e}")
                logger.info("Restarting PulseAudio event monitoring in 10 seconds...")
                time.sleep(10)

        logger.info("PulseAudio event monitoring stopped")

    def get_current_device_states(self):
        """Lấy trạng thái hiện tại của tất cả paired/connected devices"""
        try:
            device_states = {}

            # Lấy danh sách tất cả devices
            all_devices_result = subprocess.run(
                ['bluetoothctl', 'devices'],
                capture_output=True,
                text=True,
                timeout=10
            )

            for line in all_devices_result.stdout.split('\n'):
                if line.strip() and 'Device' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        mac = parts[1]
                        name = ' '.join(parts[2:])

                        # Lấy thông tin chi tiết
                        info_result = subprocess.run(
                            ['bluetoothctl', 'info', mac],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )

                        is_connected = 'Connected: yes' in info_result.stdout
                        is_paired = 'Paired: yes' in info_result.stdout
                        is_audio_device = ('Audio Sink' in info_result.stdout or
                                         'Audio Source' in info_result.stdout or
                                         'A2DP' in info_result.stdout or
                                         'Headset' in info_result.stdout)

                        device_states[mac] = {
                            'name': name,
                            'connected': is_connected,
                            'paired': is_paired,
                            'is_audio': is_audio_device,
                            'last_seen': datetime.now() if is_connected else None
                        }

            return device_states
        except Exception as e:
            logger.error(f"Error getting device states: {e}")
            return {}

    def continuous_monitoring(self):
        """Continuous monitoring thread để detect khi loa bị tắt đột ngột"""
        logger.info("🔄 Starting continuous Bluetooth monitoring...")

        # Đợi initial setup hoàn thành
        time.sleep(15)

        consecutive_errors = 0
        max_consecutive_errors = 3

        while self.monitoring_enabled:
            try:
                current_states = self.get_current_device_states()

                # Reset error counter khi thành công
                consecutive_errors = 0

                # ✅ CHECK 1: So sánh với trạng thái trước đó (Bluetooth level)
                for mac, current_state in current_states.items():
                    if mac in self.last_known_devices:
                        last_state = self.last_known_devices[mac]

                        # Detect disconnection của audio device
                        if (last_state['connected'] and not current_state['connected'] and
                            current_state['is_audio']):
                            logger.info(f"🔋 Detected audio device disconnection: {current_state['name']} ({mac})")

                            # Remove from connected list
                            if mac in self.connected_speakers:
                                self.connected_speakers.remove(mac)

                            # Set HDMI khi audio device disconnect
                            logger.info("Setting audio output back to HDMI...")
                            if self.set_default_to_audiocodec():
                                logger.info("✅ HDMI set as default after BT disconnect")
                            else:
                                logger.warning("⚠️ Failed to set HDMI!")

                            # Broadcast disconnect event tới clients
                            self.broadcast_response({
                                'action': 'device_disconnected',
                                'mac_address': mac,
                                'device_name': current_state['name'],
                                'reason': 'monitoring_detected'
                            })

                        # Detect reconnection của audio device
                        elif (not last_state['connected'] and current_state['connected'] and
                              current_state['is_audio']):
                            logger.info(f"🔌 Detected audio device reconnection: {current_state['name']} ({mac})")

                            # Add to connected list
                            if mac not in self.connected_speakers:
                                self.connected_speakers.append(mac)

                            # Đợi PulseAudio ổn định
                            time.sleep(3)

                            # Set làm default audio sink
                            if self.set_bluetooth_as_default_sink(mac, current_state['name']):
                                logger.info(f"✅ Auto-set {current_state['name']} as default audio sink")

                                # Broadcast reconnect event tới clients
                                self.broadcast_response({
                                    'action': 'device_reconnected',
                                    'mac_address': mac,
                                    'device_name': current_state['name'],
                                    'reason': 'monitoring_detected'
                                })
                            else:
                                logger.warning(f"⚠️ Could not set {current_state['name']} as default sink")

                # ✅ CHECK 2: Verify PulseAudio sink state (Audio level)
                # Quan trọng: Check xem có Bluetooth sink nào đang active không
                current_sink = self.get_current_default_sink()
                has_active_bt_device = any(state['connected'] and state['is_audio']
                                          for state in current_states.values())

                logger.debug(f"Current sink: {current_sink}, Has active BT: {has_active_bt_device}")

                # Nếu sink hiện tại là Bluetooth nhưng KHÔNG có BT device nào connected
                # => Loa bị tắt đột ngột, chưa kịp update state
                if current_sink and 'bluez' in current_sink.lower() and not has_active_bt_device:
                    logger.warning(f"⚠️ Detected orphaned Bluetooth sink: {current_sink}")
                    logger.info("🔧 Bluetooth device disconnected but sink still active - forcing HDMI...")

                    if self.set_default_to_audiocodec():
                        logger.info("✅ HDMI set as default after detecting orphaned BT sink")
                    else:
                        logger.warning("⚠️ Failed to set HDMI!")

                    # Broadcast event
                    self.broadcast_response({
                        'action': 'orphaned_sink_detected',
                        'sink_name': current_sink,
                        'reason': 'device_powered_off'
                    })

                # Update last known states
                self.last_known_devices = current_states.copy()

                # Đợi 3 giây trước lần check tiếp theo (nhanh hơn để catch disconnect sớm)
                time.sleep(3)

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Error in continuous monitoring (attempt {consecutive_errors}/{max_consecutive_errors}): {e}")

                if consecutive_errors >= max_consecutive_errors:
                    logger.error("⚠️ Too many consecutive errors in monitoring, restarting...")
                    consecutive_errors = 0
                    time.sleep(30)  # Đợi lâu hơn trước khi restart
                else:
                    time.sleep(10)  # Đợi ngắn hơn giữa các retry

    def auto_reconnect_paired_devices(self):
        """Tự động kết nối lại thiết bị đã pair sau khi reboot"""
        try:
            logger.info("Auto-reconnecting devices after reboot...")

            # Đảm bảo Bluetooth đã sẵn sàng
            subprocess.run(['bluetoothctl', 'power', 'on'], capture_output=True)
            time.sleep(5)

            # Setup agent
            subprocess.run(['bluetoothctl', 'agent', 'on'], capture_output=True)
            subprocess.run(['bluetoothctl', 'default-agent'], capture_output=True)

            # Lấy TẤT CẢ devices
            all_devices_result = subprocess.run(
                ['bluetoothctl', 'devices'],
                capture_output=True,
                text=True
            )

            # Lấy danh sách paired devices
            paired_result = subprocess.run(
                ['bluetoothctl', 'paired-devices'],
                capture_output=True,
                text=True
            )

            logger.info(f"All devices: {all_devices_result.stdout}")
            logger.info(f"Paired devices: {paired_result.stdout}")

            reconnected_count = 0
            attempted_devices = []
            audio_devices_reconnected = []

            # Xử lý tất cả devices từ cache
            for line in all_devices_result.stdout.split('\n'):
                if line.strip() and 'Device' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        mac = parts[1]
                        name = ' '.join(parts[2:])

                        # Kiểm tra trạng thái hiện tại
                        info_result = subprocess.run(
                            ['bluetoothctl', 'info', mac],
                            capture_output=True,
                            text=True
                        )

                        is_connected = 'Connected: yes' in info_result.stdout
                        is_paired = 'Paired: yes' in info_result.stdout
                        is_trusted = 'Trusted: yes' in info_result.stdout

                        # Kiểm tra xem đây có phải audio device không
                        is_audio_device = ('Audio Sink' in info_result.stdout or
                                         'Audio Source' in info_result.stdout or
                                         'A2DP' in info_result.stdout or
                                         'Headset' in info_result.stdout)

                        logger.info(f"Device {name} ({mac}): Connected={is_connected}, Paired={is_paired}, Trusted={is_trusted}, Audio={is_audio_device}")

                        # Thử reconnect nếu chưa kết nối và đã paired/trusted
                        if not is_connected and (is_paired or is_trusted):
                            logger.info(f"Attempting to reconnect: {name} ({mac})")
                            attempted_devices.append(name)

                            # Trust device trước khi connect
                            subprocess.run(['bluetoothctl', 'trust', mac], capture_output=True)

                            # Nếu chưa pair, thử pair lại
                            if not is_paired:
                                logger.info(f"Re-pairing {name}...")
                                pair_result = subprocess.run(
                                    ['bluetoothctl', 'pair', mac],
                                    capture_output=True,
                                    text=True,
                                    timeout=20
                                )
                                if pair_result.returncode != 0:
                                    logger.warning(f"Pairing failed for {name}: {pair_result.stderr}")

                            # Thử connect
                            connect_result = subprocess.run(
                                ['bluetoothctl', 'connect', mac],
                                capture_output=True,
                                text=True,
                                timeout=15
                            )

                            if connect_result.returncode == 0 or 'Connection successful' in connect_result.stdout:
                                logger.info(f"✅ Reconnected: {name}")
                                reconnected_count += 1

                                # Nếu là audio device, set làm default sink
                                if is_audio_device:
                                    logger.info(f"Setting {name} as default audio sink...")
                                    time.sleep(3)  # Đợi PulseAudio nhận diện thiết bị

                                    if self.set_bluetooth_as_default_sink(mac, name):
                                        audio_devices_reconnected.append(name)
                                        logger.info(f"✅ {name} is now the default audio sink")
                                    else:
                                        logger.warning(f"⚠️ Could not set {name} as default audio sink")

                            else:
                                logger.warning(f"❌ Failed to reconnect: {name} - {connect_result.stderr}")

                        elif is_connected:
                            logger.info(f"Already connected: {name}")
                            # Nếu đã kết nối và là audio device, đảm bảo nó là default sink
                            if is_audio_device:
                                logger.info(f"Ensuring {name} is set as default audio sink...")
                                if self.set_bluetooth_as_default_sink(mac, name):
                                    audio_devices_reconnected.append(name)
                                    logger.info(f"✅ {name} is confirmed as default audio sink")

            # Nếu không reconnect được thiết bị audio nào, set về HDMI
            if not audio_devices_reconnected:
                logger.info("No audio devices reconnected, setting default sink to HDMI...")
                self.set_default_to_audiocodec()

            logger.info(f"Auto-reconnect completed: {reconnected_count}/{len(attempted_devices)} devices reconnected")
            if audio_devices_reconnected:
                logger.info(f"Audio devices set as default: {', '.join(audio_devices_reconnected)}")
            if attempted_devices:
                logger.info(f"Attempted devices: {', '.join(attempted_devices)}")

        except Exception as e:
            logger.error(f"Error in auto-reconnect: {e}")

    def start_server(self):
        """Start TCP server"""
        # ✅ Set HDMI làm default sink ngay từ đầu
        logger.info("Initializing audio system...")
        self.set_default_to_audiocodec()

        # Setup mDNS advertisement
        self.setup_mdns_advertisement()

        # Auto-reconnect paired devices sau khi service khởi động
        def delayed_reconnect():
            time.sleep(10)  # Đợi 10 giây để system ổn định
            logger.info("=== Starting auto-reconnect ===")

            # Gọi auto_reconnect một lần
            self.auto_reconnect_paired_devices()

            logger.info("Auto-reconnect completed")

        threading.Thread(target=delayed_reconnect, daemon=True).start()

        # ✅ Start continuous monitoring thread (Bluetooth level)
        self.monitoring_thread = threading.Thread(target=self.continuous_monitoring, daemon=True)
        self.monitoring_thread.start()
        logger.info("🔄 Continuous Bluetooth monitoring thread started")

        # ✅ Start PulseAudio event monitoring thread (Audio level - faster detection)
        self.pa_monitoring_thread = threading.Thread(target=self.monitor_pulseaudio_events, daemon=True)
        self.pa_monitoring_thread.start()
        logger.info("🎵 PulseAudio event monitoring thread started")

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORT))
        self.server_socket.listen(5)

        # Lấy IP thực tế
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        logger.info(f"Bluetooth Speaker Service listening on {HOST}:{PORT}")
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
            # Stop monitoring
            self.monitoring_enabled = False
            if self.monitoring_thread and self.monitoring_thread.is_alive():
                logger.info("Stopping monitoring thread...")
                self.monitoring_thread.join(timeout=5)

            if self.server_socket:
                self.server_socket.close()

def main():
    service = BluetoothSpeakerService()
    service.start_server()

if __name__ == "__main__":
    main()
