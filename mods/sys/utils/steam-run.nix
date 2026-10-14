{mkMod, ...}:
mkMod __curPos "steam-run (FHS 환경에서 서드파티 바이너리 실행)" ({pkgs, ...}: {
  # (목적: 다운로드한 리눅스 바이너리/.exe 래퍼(NUSGet, GBxCart 등)를 `steam-run ./<바이너리>`로 실행)
  # (이유: NixOS는 /lib64, /usr/lib 같은 FHS 경로가 없어 외부 바이너리가 바로 실행되지 않음)
  # (참고: unfree 패키지 — core/lib/host.nix에서 allowUnfree = true로 허용됨)
  os.environment.systemPackages = with pkgs; [steam-run];
  hm.home.packages = with pkgs; [steam-run];
})
