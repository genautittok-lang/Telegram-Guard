#!/bin/bash
cd /home/runner/workspace
while true; do
    echo "$(date): Starting bot..."
    python bot.py 2>&1
    echo "$(date): Bot stopped, restarting in 3 seconds..."
    sleep 3
done
