#!/usr/bin/env bash
# 기존 NixOS 시스템을 현재 프로젝트의 Flake 설정으로 전환(Bootstrap)합니다.

set -e

SCRIPT_DIR=$(dirname $(readlink -f "$0"))

# 터미널 색상
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}==> Bootstrapping NixOS with Flake configuration...${NC}"

if [ ! -f "$SCRIPT_DIR/dev/_info.json" ]; then
    echo -e "${RED}Error: dev/_info.json not found! Please run this from the project root.${NC}"
    exit 1
fi

# 의존성 없이 호스트 목록 파싱 (nhw.sh 실행 전이므로 grep과 awk 활용)
AVAILABLE_HOSTS=$(grep '"hostname":' "$SCRIPT_DIR/dev/_info.json" | awk -F '"' '{print $4}')
echo -e "Available hosts: ${CYAN}$(echo $AVAILABLE_HOSTS | tr '\n' ' ')${NC}"

echo ""
read -rp "Enter the hostname to switch to: " HOSTNAME

if [ -z "$HOSTNAME" ]; then
    echo -e "${RED}Error: Hostname cannot be empty.${NC}"
    exit 1
fi

echo -e "\n${CYAN}==> Preparing /etc/nixos symbolic link...${NC}"

# /etc/nixos 심볼릭 링크 처리
ETC_NIXOS="/etc/nixos"
if [ -e "$ETC_NIXOS" ] || [ -L "$ETC_NIXOS" ]; then
    # 이미 현재 디렉토리를 가리키고 있는지 확인
    CURRENT_LINK=$(readlink -f "$ETC_NIXOS" 2>/dev/null || echo "")
    if [ "$CURRENT_LINK" != "$SCRIPT_DIR" ]; then
        echo -e "${YELLOW}Existing $ETC_NIXOS found. Backing up to ${ETC_NIXOS}.old...${NC}"
        sudo mv "$ETC_NIXOS" "${ETC_NIXOS}.old"
        sudo ln -sfn "$SCRIPT_DIR" "$ETC_NIXOS"
        echo -e "${GREEN}Created symbolic link: $ETC_NIXOS -> $SCRIPT_DIR${NC}"
    else
        echo -e "${GREEN}$ETC_NIXOS is already linked correctly.${NC}"
    fi
else
    echo -e "${YELLOW}Creating $ETC_NIXOS symbolic link...${NC}"
    sudo ln -sfn "$SCRIPT_DIR" "$ETC_NIXOS"
    echo -e "${GREEN}Created symbolic link: $ETC_NIXOS -> $SCRIPT_DIR${NC}"
fi

echo -e "\n${CYAN}==> Switching system to host: ${HOSTNAME} using nhw...${NC}"

# nhw.sh 스크립트는 nix-shell 쉬뱅을 통해 nh, jq, nom, git 등을 자동으로 가져오고,
# /tmp/nixos-build 디렉토리 격리 및 로깅을 자동으로 처리합니다.
exec "$SCRIPT_DIR/core/scripts/nhw.sh" os switch "$HOSTNAME"
