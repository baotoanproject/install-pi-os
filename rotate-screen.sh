#!/bin/bash

DISPLAY=:0
XAUTHORITY=/home/orangepi/.Xauthority
HDMI_OUTPUT="HDMI-1"

STATUS=$(xrandr | grep "^$HDMI_OUTPUT" | awk '{print $2}')

if [ "$STATUS" == "disconnected" ]; then
    echo "HDMI chưa kết nối, thử reset..."
    xrandr --output $HDMI_OUTPUT --off
    sleep 1
    xrandr --output $HDMI_OUTPUT --auto
    sleep 1
fi

xrandr --output $HDMI_OUTPUT --rotate left
echo "Hoàn tất reset & xoay màn hình."
