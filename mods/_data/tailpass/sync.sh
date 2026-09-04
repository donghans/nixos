#!/usr/bin/env bash
# tailpass 저장소의 deploy/nix/*와 빌드된 .deb를 이 디렉터리로 vendoring하는
# 동기화 스크립트.
#
# deploy/nix/dbus-policy.nix는 원본 저장소에서 deploy/nix/ 한 단계 아래에 있어
# ${../it.bitstep.tailpass.AuthAgent1.conf}로 deploy/(한 단계 위)의 .conf 파일을
# 참조한다. 이 스크립트는 deploy/nix/ 내용만 평탄하게 이 디렉터리로 복사하므로
# (deploy/ 계층 자체는 옮기지 않음), 그 참조를 그대로 두면 매번 깨진다 — 그래서
# .conf 파일을 별도로 같은 디렉터리에 복사하고, dbus-policy.nix 안의 참조를
# ./로 패치한다.
#
# tailpass.deb는 파일명에 버전이 박혀 있어(Tailpass_<version>_amd64.deb)
# 고정 경로로 복사할 수 없다 — target/release/bundle/deb/ 밑에서 가장 최근
# 수정된 *_amd64.deb 하나를 골라 복사한다(빌드를 아직 안 했으면 건너뛰고
# 경고만 남김 — memory: project_nixos_static_copy_gotcha 참조).
set -euo pipefail

SRC="${1:-$HOME/tailpass}"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$SRC/deploy/nix" ]; then
  echo "오류: $SRC/deploy/nix 를 찾을 수 없습니다 (tailpass 저장소 경로 확인)" >&2
  exit 1
fi

cp -a "$SRC/deploy/nix/." "$DEST/"
cp "$SRC/deploy/it.bitstep.tailpass.AuthAgent1.conf" "$DEST/"

# dbus-policy.nix 자신은 deploy/에서 한 단계 위(../)로 .conf를 찾도록 되어 있는데,
# 이 디렉터리에는 .conf를 같은 레벨에 뒀으므로 ./로 고쳐야 한다.
sed -i 's#\${\.\./it\.bitstep\.tailpass\.AuthAgent1\.conf}#${./it.bitstep.tailpass.AuthAgent1.conf}#' "$DEST/dbus-policy.nix"

DEB_DIR="$SRC/target/release/bundle/deb"
DEB_SRC="$(ls -t "$DEB_DIR"/*_amd64.deb 2>/dev/null | head -n1 || true)"
if [ -n "$DEB_SRC" ]; then
  cp "$DEB_SRC" "$DEST/tailpass.deb"
  echo "tailpass.deb 갱신: $DEB_SRC -> $DEST/tailpass.deb"
else
  echo "경고: $DEB_DIR 에서 *_amd64.deb를 못 찾았습니다 — tailpass.deb는 갱신되지 않았습니다." >&2
  echo "       (./build.sh app 먼저 실행했는지 확인)" >&2
fi

echo "동기화 완료: $SRC/deploy/nix -> $DEST (+ it.bitstep.tailpass.AuthAgent1.conf)"
