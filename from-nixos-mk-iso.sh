#!/usr/bin/env bash
# 기존 NixOS 환경(예: Live ISO)에서 현재 프로젝트의 사용자 지정 ISO를 빌드합니다.

set -e

SCRIPT_DIR=$(dirname $(readlink -f "$0"))

# 터미널 색상
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}==> Using nhw dispatcher to build custom NixOS ISO...${NC}"

# nhw.sh 스크립트는 nix-shell 쉬뱅을 통해 nom, nh, jq, git 등을 자동으로 가져오고,
# /tmp/nixos-build 디렉토리 격리 및 로깅을 자동으로 처리합니다.
exec "$SCRIPT_DIR/core/scripts/nhw.sh" iso
