#!/bin/bash
# Reload HDMI driver if disconnected

# --- chỉnh tên module HDMI đúng của bạn ở đây ---
MOD=sun8i_dw_hdmi
# -------------------------------------------------

STATUS_FILE="/sys/class/drm/card0-HDMI-A-1/status"

if [ -f "$STATUS_FILE" ]; then
    STATUS=$(cat "$STATUS_FILE")
    if [ "$STATUS" != "connected" ]; then
        echo "[HDMI] Disconnected, reloading module $MOD..."
        /sbin/modprobe -r $MOD
        sleep 2
        /sbin/modprobe $MOD
        sleep 3
    fi
else
    echo "[HDMI] Status file not found: $STATUS_FILE"
fi
