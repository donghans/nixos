#!/usr/bin/env bash
# shellcheck disable=SC2148

# == nixup.lib-help.sh ==
# 도움말 출력 함수 모음. nixup.sh에서 source하여 사용.

print_help() {
    cat <<'EOF'
NixOS update utility

사용법: nixup [SUBCOMMAND] [HOST] [FLAGS]
       nixup help [SUBCOMMAND]

서브커맨드:
  os        NixOS 시스템 빌드 및 적용 (기본값)
  home      Home Manager 빌드 및 적용
  check     코드 무결성 검사
  update    flake.lock 갱신
  clean     오래된 세대 정리
  iso       ISO 이미지 빌드
  fix       unstable 패키지 버전 고정
  help      이 도움말 표시

공통 플래그:
  -b, --build         빌드만 수행 (적용 안 함)
  -t, --try           즉시 활성화 (세대 등록 없음, 재부팅 시 원복)
  -s, --stage         다음 부팅 시 적용
  -h, --help          도움말 표시

예시:
  nixup                         현재 호스트에 OS 설정 적용
  nixup os --try                임시 활성화 (재부팅 시 원복)
  nixup home --build            홈 설정 빌드만 수행
  nixup clean --all --keep=5    시스템 전체 정리, 5세대 보존
  nixup check --deep            전체 호스트 완전 검사

서브커맨드별 도움말: nixup SUBCOMMAND --help
EOF
}

print_help_subcmd() {
    local subcmd="${1:-}"
    case "$subcmd" in
        os)
            cat <<'EOF'
nixup os [FLAGS]  —  NixOS 시스템 빌드 및 적용

  플래그:
    -b, --build         빌드만 수행, 새 세대 생성 안 함
    -t, --try           즉시 활성화 (세대 등록 없음, 재부팅 시 원복)
    -s, --stage         다음 부팅 시 적용
    -h, --help          이 도움말

  예시:
    nixup                       현재 호스트 즉시 적용 (os 생략 가능)
    nixup os --build            빌드만 수행 (미리보기)
    nixup os --try              임시 활성화 (재부팅 시 원복)
EOF
            ;;
        home)
            cat <<'EOF'
nixup home [FLAGS]  —  Home Manager 빌드 및 적용

  플래그:
    -b, --build         빌드만 수행
    -t, --try           즉시 활성화 (세대 등록 없음, 재부팅 시 원복)
    -s, --stage         다음 부팅 시 적용
    -h, --help          이 도움말

  예시:
    nixup home                  현재 호스트 홈 설정 적용
    nixup home --build          빌드만 수행
EOF
            ;;
        check)
            cat <<'EOF'
nixup check [FLAGS]  —  코드 무결성 검사

  단계: deadnix → statix fix → alejandra → shellcheck → nix eval

  플래그:
    --deep     nix eval 대신 nix flake check로 전체 호스트 완전 검사
    -h, --help 이 도움말

  참고: check는 NIXUP_LAST_HOST를 갱신하지 않습니다.
EOF
            ;;
        update)
            cat <<'EOF'
nixup update  —  flake.lock 갱신

  Rolling 호스트: _rolling.lock 갱신
  Stable  호스트: <hostname>.lock 갱신

  플래그:
    -h, --help  이 도움말
EOF
            ;;
        clean)
            cat <<'EOF'
nixup clean [--all] [--keep=N]  —  오래된 세대 정리

  기본값: 사용자 홈 영역만, 최근 3세대 보존

  플래그:
    --all       시스템 프로필(sudo 필요) + 전체 GC 포함
    --keep=N    보존 세대 수 지정 (기본값: 3)
    -a          --all 단축형
    -h, --help  이 도움말

  예시:
    nixup clean                   사용자 영역만 정리 (3세대 보존)
    nixup clean --all             시스템 전체 정리 (3세대 보존)
    nixup clean --all --keep=5    시스템 전체 정리, 5세대 보존
EOF
            ;;
        iso)
            cat <<'EOF'
nixup iso [FLAGS]  —  커스텀 ISO 이미지 빌드

  결과물: .build/ 디렉터리에 심볼릭 링크로 생성

  플래그:
    --arm       aarch64 타겟 빌드 (기본값: x86_64)
    -h, --help  이 도움말
EOF
            ;;
        fix)
            cat <<'EOF'
nixup fix [PKG...]  —  unstable 패키지 버전 고정

  지정한 패키지의 이전 정상 커밋을 찾아 .env에 고정합니다.
  고정된 패키지는 *.nix에서 unstable-fallback.<pkgName>으로 참조하세요.

  플래그:
    -h, --help  이 도움말

  예시:
    nixup fix python311Packages.tensorflow
    nixup fix pkg1 pkg2
EOF
            ;;
        *)
            print_help
            ;;
    esac
}

# 조기 help 감지 — nixup.sh 서브커맨드 파싱 전에 호출
# nixup --help [SUBCMD] / nixup help [SUBCMD] 형태 처리
_nixup_maybe_help() {
    case "${1:-}" in
        --help|-h)
            if [[ "${2:-}" =~ ^(os|home|check|update|clean|iso|fix)$ ]]; then
                print_help_subcmd "$2"
            else
                print_help
            fi
            exit 0
            ;;
        help)
            print_help_subcmd "${2:-}"
            exit 0
            ;;
    esac
}
