#!/bin/bash

# OrangePi WiFi Hotspot Setup Script
# Tạo WiFi hotspot để Flutter app có thể kết nối từ xa

echo "=== OrangePi WiFi Hotspot Setup ==="

# Check if NetworkManager is available
if ! command -v nmcli &> /dev/null; then
    echo "❌ NetworkManager không có sẵn"
    echo "   Cài đặt: sudo apt install network-manager"
    exit 1
fi

# Stop any existing hotspot
echo "🔄 Dừng hotspot cũ (nếu có)..."
sudo nmcli connection down Hotspot 2>/dev/null || true

# Create hotspot
echo "📡 Tạo WiFi hotspot..."
HOTSPOT_NAME="OrangePi-Remote"
HOTSPOT_PASSWORD="orangepi123"

sudo nmcli dev wifi hotspot ifname wlan0 ssid "$HOTSPOT_NAME" password "$HOTSPOT_PASSWORD"

if [ $? -eq 0 ]; then
    # Get hotspot IP
    sleep 3
    HOTSPOT_IP=$(ip route show | grep wlan0 | grep 'scope link' | awk '{print $1}' | cut -d'/' -f1 | head -1)

    if [ -z "$HOTSPOT_IP" ]; then
        HOTSPOT_IP="192.168.4.1"  # Default hotspot IP
    fi

    echo ""
    echo "✅ WiFi Hotspot đã khởi động thành công!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📶 Tên WiFi: $HOTSPOT_NAME"
    echo "🔑 Mật khẩu: $HOTSPOT_PASSWORD"
    echo "🌐 IP của OrangePi: $HOTSPOT_IP"
    echo "🔌 Port Remote Control: 8767"
    echo ""
    echo "📱 Từ Flutter app:"
    echo "   1. Kết nối WiFi '$HOTSPOT_NAME'"
    echo "   2. Nhập IP: $HOTSPOT_IP"
    echo "   3. Remote Control sẽ tự kết nối"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Start remote control service if exists
    SCRIPT_DIR="/usr/local/bin"
    SCRIPT_PATH="$SCRIPT_DIR/remote-control.py"

    if [ -f "$SCRIPT_PATH" ]; then
        echo "🚀 Khởi động Remote Control service..."
        cd "$SCRIPT_DIR"
        python3 remote-control.py &
        echo "✅ Remote Control service đang chạy trên $HOTSPOT_IP:8767"
    else
        echo "⚠️  File remote-control.py không tìm thấy"
        echo "   Cần copy file từ:"
        echo "   ~/Documents/GitHub/P2325/welcome-board/install-pi-os/files/remote-control.py"
        echo "   → $SCRIPT_PATH"
        echo ""
        echo "📋 Lệnh copy:"
        echo "   sudo cp ~/Documents/GitHub/P2325/welcome-board/install-pi-os/files/remote-control.py $SCRIPT_PATH"
        echo "   sudo chmod +x $SCRIPT_PATH"
    fi

else
    echo "❌ Không thể tạo hotspot"
    echo "   Kiểm tra:"
    echo "   - WiFi adapter có hỗ trợ AP mode không"
    echo "   - NetworkManager service đang chạy"
    echo "   - Quyền sudo"
fi
