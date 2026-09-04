# workspace 옵션 선언
# nixup.resolve.py가 생성한 resolved.json 값을 config.workspace.* 네임스페이스로 주입하기 위한
# 타입 선언 파일. 사용자가 직접 설정하는 것이 아니라 TOML 메타데이터에서 자동으로 채워짐.
# mods의 기능 토글(config.mods.*.*.enable)과는 완전히 별개의 네임스페이스임.
{lib, ...}:
with lib; {
  options = {
    workspace = {
      username = mkOption {
        type = types.str;
        description = "Main user username";
      };
      gitName = mkOption {
        type = types.str;
        description = "Git user name";
      };
      gitEmail = mkOption {
        type = types.str;
        description = "Git user email";
      };
      nixosRepo = mkOption {
        type = types.str;
        description = "NixOS repository path or URL";
      };
      hostname = mkOption {
        type = types.str;
        # default 없음 — nixup.resolve.py가 resolved.json에 항상 주입하므로 평가 오류 발생 안 함
        description = "System hostname";
      };
      type = mkOption {
        type = types.enum ["desktop" "laptop" "server" "rpi"];
        description = "Device type: desktop, laptop, server, rpi";
      };
      ramGb = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "RAM size in GB. Auto-detected from /proc/meminfo by nixup.resolve.py. Not configurable via host.toml.";
      };
      swapGb = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "Swap file size in GB. Default: ceil(ramGb * 0.75). Set to 0 to disable swap.";
      };
      tmpfsSize = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "tmpfs /tmp size (e.g. \"100%\", \"4G\"). Set to \"0\" to disable. Default: \"100%\".";
      };
      zramPercent = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "ZRAM pool size as percentage of physical RAM. Default: 50.";
      };
      cpuCount = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "Logical CPU core count. host.toml에 명시 필요 (자동 감지 없음) — CPUQuota 등 코어 수 기반 cgroup 계산에 사용.";
      };
      diskDevice = mkOption {
        type = types.str;
        description = "Btrfs root partition device path (e.g. /dev/disk/by-label/nixos)";
      };
      bootDevice = mkOption {
        type = types.str;
        description = "Boot (FAT32) partition device path (e.g. /dev/disk/by-label/boot or /dev/disk/by-uuid/...)";
      };
      timeZone = mkOption {
        type = types.str;
        description = "System timezone (e.g. \"Asia/Seoul\"). Default: base.toml timeZone.";
      };
      defaultLocale = mkOption {
        type = types.str;
        description = "Primary system locale (e.g. \"en_US.UTF-8\"). Default: base.toml defaultLocale.";
      };
      extraLocale = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Additional locale to include in supportedLocales (e.g. \"ko_KR.UTF-8\"). Null to disable.";
      };
      stateVersion = mkOption {
        type = types.str;
        description = "NixOS/Home-Manager state version";
      };
      pkgsVersion = mkOption {
        type = types.str;
        description = "Nixpkgs channel version used for building this host";
      };

      nixCacheAddr = mkOption {
        type = types.str;
        default = "";
        description = "Nix binary cache proxy server address (e.g. 192.168.1.10:7070). Leave empty to disable client substituter.";
      };
      bootLoader = mkOption {
        type = types.enum ["systemd-boot" "grub-bios" "grub-uefi"];
        default = "systemd-boot";
        description = "Boot loader: systemd-boot=local EFI with manual fileSystems (default), grub-bios=disko+GRUB+MBR, grub-uefi=disko+GRUB+EFI-removable (canTouchEfiVariables=false). Auto-injected from host.toml bootLoader.";
      };
      isRemote = mkOption {
        type = types.bool;
        default = false;
        description = "True if this host is a remote deploy-rs target (has [deploy] section in host.toml). Auto-injected from resolved.json.";
      };
      hasDeployRs = mkOption {
        type = types.bool;
        default = false;
        description = "True if this host uses deploy-rs ([deploy] section exists). Standalone servers are isRemote=true but hasDeployRs=false.";
      };
      cloudProvider = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Cloud provider identifier (e.g. \"aws\"). Set via top-level cloud field in host.toml. Enables vendor-specific modules (kernel params, SSM agent, etc).";
      };
    };
  };
}
