#!/bin/bash

# Set display environment
export DISPLAY=:0
export XAUTHORITY=/home/orangepi/.Xauthority

# Lock file to prevent concurrent executions
LOCK_FILE="/tmp/rotate-screen.lock"

# Check if another instance is running
if [ -f "$LOCK_FILE" ]; then
    echo "Another rotation process is running. Exiting."
    exit 1
fi

# Create lock file
touch "$LOCK_FILE"

# Cleanup function
cleanup() {
    rm -f "$LOCK_FILE"
}

# Set trap to cleanup on exit
trap cleanup EXIT

# Wait a moment to ensure X server is ready
sleep 0.5

# Check if display is available
if ! xrandr --query &>/dev/null; then
    echo "Error: Cannot connect to display"
    exit 1
fi

# Check if HDMI-1 output exists
if ! xrandr --query | grep -q "HDMI-1"; then
    echo "Error: HDMI-1 output not found"
    exit 1
fi

# Perform the rotation with error handling
if xrandr --output HDMI-1 --rotate left; then
    echo "Screen rotated successfully"
else
    echo "Error: Failed to rotate screen"
    exit 1
fi

# Small delay to allow X server to process the change
sleep 0.2
