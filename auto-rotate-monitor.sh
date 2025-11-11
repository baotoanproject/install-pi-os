#!/bin/bash
OUTPUT="HDMI-1"
ROTATE_SCRIPT="/usr/local/bin/rotate-screen.sh"

while true; do
    bash /usr/local/bin/reload-hdmi.sh
    CONNECTED=$(xrandr | grep "$OUTPUT connected")
    if [ -n "$CONNECTED" ]; then
        bash "$ROTATE_SCRIPT"
    fi
    sleep 5
done
