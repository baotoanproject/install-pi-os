#!/bin/bash

OUTPUT="HDMI-1"
ROTATE_SCRIPT="/usr/local/bin/rotate-screen.sh"

while true; do
    # Kiểm tra HDMI có kết nối không
    CONNECTED=$(xrandr | grep "$OUTPUT connected")
    if [ -n "$CONNECTED" ]; then
        # HDMI đang kết nối => gọi script xoay
        bash "$ROTATE_SCRIPT"
    fi
    sleep 5
done
