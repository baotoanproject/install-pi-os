#!/usr/bin/env python3
import http.server
import socketserver
import json

PORT = 5000

def get_pi_serial():
    serial = "Unknown"
    try:
        # Ưu tiên đọc từ /proc/cpuinfo (Raspberry Pi)
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    serial = line.split(":")[1].strip()
                    return serial

        # Nếu không có (Orange Pi), thử device-tree
        with open("/proc/device-tree/serial-number", "r") as f:
            serial = f.read().strip().replace("\x00", "")
    except Exception as e:
        print(f"Error getting serial: {e}")
    return serial

class SerialHandler(http.server.BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*") 
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/serial":
            serial = get_pi_serial()
            self.send_response(200)
            self._set_headers()
            self.end_headers()
            response = json.dumps({
                "serial": serial
            })
            self.wfile.write(response.encode("utf-8"))
        else:
            self.send_response(404)
            self._set_headers()
            self.end_headers()

with socketserver.TCPServer(("", PORT), SerialHandler) as httpd:
    print(f"✅ Serving at port {PORT}")
    print(f"→ Try opening http://<ip_of_orangepi>:{PORT}/api/serial")
    httpd.serve_forever()
