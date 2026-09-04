# 데스크탑 반응성 보장: 인터랙티브 세션(user.slice)에 CPU/IO 우선권을 몰아주고,
# 백그라운드(system.slice = nix-daemon 빌드 등)는 메모리 상한을 둬 zram 압축이 CPU까지 잠식하는 것을 방지
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  config,
  lib,
  ...
}: let
  cpuCount = config.workspace.cpuCount;

  # (목적: weight 비율만으로는 총 수요가 코어 수를 넘어서면 전부 굶는 상황을 못 막음 —
  #        system.slice에 절대 상한(CPUQuota)을 걸어 "무슨 일이 있어도" 몇 코어는 실제로 남겨둠)
  # (이유: cpuCount의 20% 또는 최소 2코어 중 더 큰 값을 예약. host.toml에 cpuCount 미지정 시 skip)
  reserveCores =
    if cpuCount == null
    then null
    else lib.max 2 ((cpuCount + 4) / 5); # ceil(cpuCount * 0.2)
  systemSliceQuota =
    if reserveCores == null
    then null
    else "${toString ((cpuCount - reserveCores) * 100)}%";
in {
  os = lib.mkIf config.mods.gui.enable {
    # (목적: Hyprland/Waybar 등 로그인 세션 전체가 여기 속함 — 빌드/서비스 부하와 경쟁 시 압도적 우선)
    systemd.slices."user.slice".sliceConfig = {
      CPUWeight = 9000;
      IOWeight = 9000;
    };

    # (목적: nix-daemon 빌드 등 시스템 서비스 — user.slice 대비 낮은 weight + 메모리 상한 + 절대 상한)
    # (이유: MemoryHigh 없이 메모리 압박이 오면 zram 압축이 CPU를 추가로 잠식해 이중으로 렉 유발.
    #        CPUQuota는 weight와 별개로 "총 수요 초과" 상황에서도 예약된 코어를 실제로 비워둠)
    systemd.slices."system.slice".sliceConfig = {
      CPUWeight = 100;
      IOWeight = 100;
      MemoryHigh = "70%";
      CPUQuota = lib.mkIf (systemSliceQuota != null) systemSliceQuota;
    };

    # (목적: user.slice 내부 세분화 — Hyprland 컴포지터/인프라(session.slice)가 브라우저·터미널·
    #        에디터 등 개별 앱(app.slice/app-graphical.slice)보다 항상 우선하도록)
    # (이유: 앱이 자체 scope로 분리돼 있어도(uwsm app / Chromium 자체 통합) session.slice와
    #        동일 weight(기본 100)면 무거운 앱 하나가 컴포지터 프레임 처리와 동급으로 경쟁함)
    systemd.user.slices."session.slice".sliceConfig = {
      CPUWeight = 2000;
      IOWeight = 2000;
    };
    systemd.user.slices."app.slice".sliceConfig = {
      CPUWeight = 200;
      IOWeight = 200;
    };
    systemd.user.slices."app-graphical.slice".sliceConfig = {
      CPUWeight = 200;
      IOWeight = 200;
    };
  };
})
