#!/bin/bash
# Xoay màn hình ngang sang phải

DISPLAY=:0
XAUTHORITY=/home/orangepi/.Xauthority
xrandr --output HDMI-1 --rotate right
