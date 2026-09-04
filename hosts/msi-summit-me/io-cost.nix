{pkgs, ...}: {
  # (목적: NVMe(WDC PC SN810) io.cost 컨트롤러 캘리브레이션 적용)
  # (배경: mods/gui/base/core.cgroups.nix 등에서 설정한 IOWeight(background.slice/docker.slice
  #        등)는 io.cost 컨트롤러가 켜져 있어야 커널이 실제로 참조함 — bfq가 아닌 기본
  #        스케줄러(none)에서는 io.cost가 유일하게 io.weight를 존중하는 메커니즘이라 이 서비스가
  #        선행조건. 2026-08-04 이 기기에서 tools/cgroup/iocost_coef_gen.py로 직접 실측한 값이라
  #        WDC PC SN810 이외 하드웨어로는 이식 불가 — 다른 워크스테이션은 동일 스크립트로 새로
  #        측정해서 자기 host 디렉터리에 별도 파일로 두는 것을 권장)
  # (참고: qos의 rpct/rlat/wpct/wlat은 커널 문서 예시값 그대로 — NVMe에는 널널한(=보수적인) 값이라
  #        과도한 스로틀링 위험이 낮음. 필요시 실측 후 좁혀도 됨)
  systemd.services.iocost-nvme0n1 = {
    description = "NVMe(nvme0n1) io.cost qos/model 캘리브레이션 적용";
    after = ["dev-nvme0n1.device"];
    requires = ["dev-nvme0n1.device"];
    wantedBy = ["multi-user.target"];
    unitConfig.ConditionPathExists = "/sys/fs/cgroup/io.cost.qos";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = pkgs.writeShellScript "iocost-nvme0n1-apply" ''
        set -eu
        devno=$(${pkgs.util-linux}/bin/lsblk -dno MAJ:MIN /dev/nvme0n1 | tr -d '[:space:]')
        echo "$devno ctrl=user model=linear rbps=6646136058 rseqiops=210783 rrandiops=22580 wbps=3731004104 wseqiops=91938 wrandiops=72258" > /sys/fs/cgroup/io.cost.model
        echo "$devno enable=1 ctrl=user rpct=95.00 rlat=75000 wpct=95.00 wlat=150000 min=50.00 max=150.00" > /sys/fs/cgroup/io.cost.qos
      '';
    };
  };
}
