#!/usr/bin/env bash
# core/scripts/iocost-calibrate.sh
#
# / 가 마운트된 NVMe/SSD를 fio로 실측(iocost-calibrate.coef-gen.py, 커널 tools/cgroup/
# iocost_coef_gen.py 그대로)해 btrfs cgroup io.weight가 실제로 먹히도록 커널 io.cost 컨트롤러를
# 캘리브레이션한다. 결과를 hosts/<호스트명>/io-cost.nix로 자동 생성하고, 지금 이 세션에도 즉시
# 라이브 적용한다(재부팅 불필요).
#
# 배경: 2026-08-04 msi-summit-me에서 docker(btrfs storage-driver)+incus 컨테이너/이미지 누적으로
# btrfs-cleaner가 상시 부하에 걸린 사고 조사 중 확인 — 이 시스템의 기본 I/O 스케줄러(none)는
# cgroup io.weight를 전혀 참조하지 않고, io.cost 컨트롤러(iocost)가 유일하게 그걸 존중한다.
# io.cost는 디바이스별 성능 계수(rbps/rseqiops/rrandiops/wbps/wseqiops/wrandiops)를 알아야
# 정확히 동작하는데, 이건 하드웨어마다 달라 실측이 필요하다.
#
# 사용법: sudo core/scripts/iocost-calibrate.sh [호스트명]
#   호스트명 생략 시 `hostname` 명령 결과 사용. hosts/<호스트명>/io-cost.nix가 이미 있으면
#   덮어쓰지 않고 종료한다(재측정하려면 기존 파일을 지우거나 백업 후 재실행).
#
# 주의: 12~15분 소요. 대상 디스크(/ 가 마운트된 디바이스)가 조용한 상태여야 정확하다 —
#       docker/incus/빌드 등 무거운 작업 없이 실행할 것. 워크스테이션 전용 —
#       io.weight로 보호할 데스크탑 세션이 없는 서버에는 적용 의미가 없다.

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
fi

if [[ $EUID -ne 0 ]]; then
  echo "root 권한이 필요합니다 — sudo로 다시 실행하세요." >&2
  exit 1
fi

missing=()
for cmd in findmnt pv dd fio lsblk; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "필요한 명령이 없습니다: ${missing[*]}" >&2
  echo "nixos-iocost-calibrate 로 실행하면 fio/pv가 자동으로 PATH에 잡힙니다." >&2
  echo "이 스크립트를 직접 실행 중이라면: nix-shell -p fio pv --run 'sudo env \"PATH=\$PATH\" $0 ${1:-}'" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ROOT_SRC=$(findmnt -nvo SOURCE -T /)
DEVICE=$(lsblk -no PKNAME "$ROOT_SRC" 2>/dev/null | head -1)
[[ -z "$DEVICE" ]] && DEVICE=$(basename "$ROOT_SRC")
[[ -b "/dev/$DEVICE" ]] || { echo "/dev/$DEVICE 를 찾을 수 없습니다 (/ 소스: $ROOT_SRC)." >&2; exit 1; }

TARGET_HOST="${1:-$(hostname)}"
OUT_NIX="$REPO_ROOT/hosts/$TARGET_HOST/io-cost.nix"

if [[ -f "$OUT_NIX" ]]; then
  echo "$OUT_NIX 가 이미 존재합니다 — 덮어쓰지 않고 종료합니다." >&2
  echo "재측정하려면 기존 파일을 지우거나 백업한 뒤 다시 실행하세요." >&2
  exit 1
fi

echo "[iocost-calibrate] 대상 디바이스: /dev/$DEVICE (/ 기준)"
echo "[iocost-calibrate] 대상 호스트: $TARGET_HOST → $OUT_NIX"
echo "[iocost-calibrate] 12~15분 소요됩니다. 다른 무거운 작업 없이 두세요."

WORKDIR="/root/.iocost-calib-tmp"
mkdir -p "$WORKDIR"
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

RESULT=$(python3 "$SCRIPT_DIR/iocost-calibrate.coef-gen.py" --duration 120 2>&1 | tee /dev/stderr | tail -1)

if ! [[ "$RESULT" =~ ^[0-9]+:[0-9]+\ rbps=[0-9]+\ rseqiops=[0-9]+\ rrandiops=[0-9]+\ wbps=[0-9]+\ wseqiops=[0-9]+\ wrandiops=[0-9]+$ ]]; then
  echo "측정 결과 형식이 예상과 다릅니다 — 위 출력을 확인하세요: $RESULT" >&2
  exit 1
fi
echo "[iocost-calibrate] 측정 결과: $RESULT"

DEVNO=$(awk '{print $1}' <<<"$RESULT")
RBPS=$(grep -oP 'rbps=\K[0-9]+' <<<"$RESULT")
RSEQIOPS=$(grep -oP 'rseqiops=\K[0-9]+' <<<"$RESULT")
RRANDIOPS=$(grep -oP 'rrandiops=\K[0-9]+' <<<"$RESULT")
WBPS=$(grep -oP 'wbps=\K[0-9]+' <<<"$RESULT")
WSEQIOPS=$(grep -oP 'wseqiops=\K[0-9]+' <<<"$RESULT")
WRANDIOPS=$(grep -oP 'wrandiops=\K[0-9]+' <<<"$RESULT")

MODEL_LINE="ctrl=user model=linear rbps=$RBPS rseqiops=$RSEQIOPS rrandiops=$RRANDIOPS wbps=$WBPS wseqiops=$WSEQIOPS wrandiops=$WRANDIOPS"
QOS_LINE="enable=1 ctrl=user rpct=95.00 rlat=75000 wpct=95.00 wlat=150000 min=50.00 max=150.00"

mkdir -p "$(dirname "$OUT_NIX")"
cat >"$OUT_NIX" <<NIXEOF
{pkgs, ...}: {
  # (목적: /dev/$DEVICE io.cost 컨트롤러 캘리브레이션 적용)
  # (배경: IOWeight(background.slice/docker.slice 등)는 io.cost 컨트롤러가 켜져 있어야 커널이
  #        실제로 참조함 — bfq가 아닌 기본 스케줄러(none)에서는 io.cost가 유일하게 io.weight를
  #        존중하는 메커니즘이라 이 서비스가 선행조건. core/scripts/iocost-calibrate.sh로
  #        $(date +%Y-%m-%d) 이 기기에서 직접 실측한 값이라 다른 하드웨어로는 이식 불가 — 다른
  #        워크스테이션은 같은 스크립트로 새로 측정해서 자기 host 디렉터리에 별도 파일로 둘 것)
  # (참고: qos의 rpct/rlat/wpct/wlat은 커널 문서 예시값 그대로 — NVMe에는 널널한(=보수적인) 값이라
  #        과도한 스로틀링 위험이 낮음. 필요시 실측 후 좁혀도 됨)
  systemd.services.iocost-$DEVICE = {
    description = "$DEVICE io.cost qos/model 캘리브레이션 적용";
    after = ["dev-$DEVICE.device"];
    requires = ["dev-$DEVICE.device"];
    wantedBy = ["multi-user.target"];
    unitConfig.ConditionPathExists = "/sys/fs/cgroup/io.cost.qos";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = pkgs.writeShellScript "iocost-$DEVICE-apply" ''
        set -eu
        devno=\$(\${pkgs.util-linux}/bin/lsblk -dno MAJ:MIN /dev/$DEVICE | tr -d '[:space:]')
        echo "\$devno $MODEL_LINE" > /sys/fs/cgroup/io.cost.model
        echo "\$devno $QOS_LINE" > /sys/fs/cgroup/io.cost.qos
      '';
    };
  };
}
NIXEOF

echo "[iocost-calibrate] 생성됨: $OUT_NIX"

echo "[iocost-calibrate] 지금 세션에 즉시 적용 중..."
echo "$DEVNO $MODEL_LINE" > /sys/fs/cgroup/io.cost.model
echo "$DEVNO $QOS_LINE" > /sys/fs/cgroup/io.cost.qos

echo "[iocost-calibrate] 완료."
echo "[iocost-calibrate] hosts/$TARGET_HOST.nix의 imports에 다음을 추가하세요:"
echo "    ./$TARGET_HOST/io-cost.nix"
echo "[iocost-calibrate] 그 다음 nixup으로 반영하면 재부팅 후에도 유지됩니다."
