#!/bin/bash
sleep 5

xset s off
xset -dpms
xset s noblank

HDMI_SINK=$(pactl list short sinks | grep -i hdmi | awk '{print $2}' | head -n 1)
if [ -n "$HDMI_SINK" ]; then
  pactl set-default-sink "$HDMI_SINK"
  pacmd suspend-sink "$HDMI_SINK" 0
fi
