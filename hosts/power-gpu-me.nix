{mkHostConfiguration, ...}:
mkHostConfiguration ({
  config,
  pkgs,
  lib,
  ...
}: {
  os = {
    # GPU: NVIDIA RTX 2060 SUPER (TU106, compute capability 7.5) — whisper.cpp/llama.cpp CUDA 가속용
    # 원래 GTX 1660 Ti(TU116, 마찬가지로 compute capability 7.5)에서 업그레이드함.
    # 다시 1660 Ti로 되돌릴 수도 있는데, 둘 다 7.5라 아래 cudaCapabilities는 그대로 둬도 됨.
    # (참고: 헤드리스 서버라 xserver는 켜지 않고, videoDrivers 지정만으로 드라이버 활성화)
    nixpkgs.config.cudaSupport = true;
    # (이유: 기본값이 sm_75/80/86/89/90/100/120a 등 여러 세대를 전부 빌드해서
    #   4GB RAM 서버에서 스왑까지 발생하며 극도로 느려짐 — 실제 보유 GPU만 지정)
    nixpkgs.config.cudaCapabilities = ["7.5"];
    services.xserver.videoDrivers = ["nvidia"];
    hardware.graphics.enable = true;
    hardware.nvidia = {
      modesetting.enable = true;
      open = false; # Turing 세대는 open kernel module 지원이 불안정해 proprietary 사용
      package = config.boot.kernelPackages.nvidiaPackages.stable;
    };

    # (임시) beelink-ser7-co의 eth0-share(NAT) 경유 설치 중 — 그쪽 물리 인터페이스가
    # tailscale MTU 정책상 1400으로 낮아져 있어 여기도 맞춰야 대용량 다운로드가 안 멈춤.
    # 최종 네트워크에 연결되면 이 블록은 제거할 것.
    systemd.network.links."10-eth-mtu" = {
      matchConfig.OriginalName = "en*";
      linkConfig.MTUBytes = "1400";
    };

    # llama-cpp(Qwen2.5-3B 로컬 LLM 서버용, record-stt 파이프라인 stage4/Stage7)와
    # ffmpeg(record-stt 오디오 정규화/턴 슬라이싱 단계에서 사용)가 environment.systemPackages에
    # 없어서 GC 보호를 못 받다가 몇 차례 사라짐 - 여기에 등록해 매번 수동 재빌드하지
    # 않도록 고정 (2026-09-22, ffmpeg는 Phase 3 파일럿 중 추가로 사라진 게 발견되어 같은 날 등록).
    environment.systemPackages = [pkgs.whisper-cpp pkgs.llama-cpp pkgs.ffmpeg];
  };
  hm = {};
})
