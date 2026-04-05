#!/usr/bin/env bash

echo "Cleaning up legacy notification logs..."

# 1. 사용자 .local/share 디렉터리 내의 잔여 파일 삭제
find ~/.local/share -maxdepth 1 -name "notify.log*" -exec rm -f {} + 2>/dev/null
find ~/.local/share -maxdepth 1 -name "custom-notify-logger.log*" -exec rm -f {} + 2>/dev/null
rm -rf ~/.local/share/notify_logs 2>/dev/null

# 2. 레거시 logrotate 상태 파일 삭제
rm -f ~/.local/share/logrotate.state 2>/dev/null

echo "Done!"