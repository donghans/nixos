#!/usr/bin/env bash
# 기존 NixOS 환경(예: Live ISO)에서 현재 프로젝트의 사용자 지정 ISO를 빌드합니다.

set -e

# 1. 프로젝트 경로 설정
PROJECT_ROOT=$(dirname "$(readlink -f "$0")")
NHW_PATH="$PROJECT_ROOT/core/scripts/nhw.sh"

# 2. 필수 파일 존재 여부 확인
if [ ! -f "$NHW_PATH" ]; then
    echo -e "${RED}Error: Cannot find '$NHW_PATH'.${NC}"
    echo -e "Make sure you are running this script inside the full repository."
    exit 1
fi

# 3. 프로젝트 루트로 이동하여 실행 (nhw.sh의 상대 경로 참조 보장)
cd "$PROJECT_ROOT"

echo -e "${CYAN}==> Using nhw dispatcher to build custom NixOS ISO...${NC}"

# nhw.sh는 nix-shell 쉬뱅을 통해 필요한 도구(nom, nh, jq 등)를 자동으로 가져옵니다.
exec "$NHW_PATH" iso
