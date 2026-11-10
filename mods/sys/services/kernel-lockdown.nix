{mkMod, ...}:
# unstable 커널로 바꿔 lockdown LSM 을 쓸 수 있게 한다 (plan boot-security S1; 아직 시험 단계).
#  - 지금(stable 26.05)의 NixOS 커널은 lockdown 이 컴파일되지 않아 `/sys/kernel/security/lockdown` 이 없다 (2026-11-09 `/proc/config.gz` 확인).
#  - 이 mod 는 **커널 패키지만** 바꾼다. `lsm=lockdown,...`·`lockdown=integrity` 인자는 호스트가 kernelParams 목록을 통째로 지정하므로 호스트에서 넣는다
#    (hosts/msi-summit-me.nix 의 specialisation.lockdown-test).
#  - 시험은 호스트에서 specialisation 안에서만 이 mod 를 켠다. 기본 부팅 항목은 바뀌지 않는다.
#  - rolling 락이라 `nixup` 마다 unstable 리비전이 바뀌어 커널 패치 버전이 달라지거나 바이너리 캐시에 없으면 로컬 빌드가 필요할 수 있다 (plan §9).
mkMod __curPos "unstable 커널 (lockdown LSM 시험용)" ({
  unstable,
  lib,
  ...
}: {
  os = {
    boot.kernelPackages = lib.mkForce unstable.linuxPackages;
  };
})
