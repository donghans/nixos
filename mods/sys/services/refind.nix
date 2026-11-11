{mkMod, ...}:
# 노트북 공용: rEFInd(최상위 메뉴) 를 nix 로 설치·관리한다 (plan refind-theme §12, boot-security 선택 지점 13).
#  - rEFInd 는 systemd-boot 를 체인으로 부르는 **메뉴 프로그램**이다(NixOS 세대를 직접 나열하는 nixpkgs `boot.loader.refind` 와 다른 구조라 그 모듈은 쓰지 않는다).
#  - 이 mod 는 ESP 의 `EFI/refind/` 를 채운다: 본체(nixpkgs refind), 생성한 `refind.conf`, 테마(원본 아이콘·글꼴 + `refind-black`).
#    ESP 가 사라져도(재파티션) `nixup` 으로 다시 채워진다. 파일시스템 드라이버·도구·샘플 항목은 만들지 않는다(필요하면 `extraConfig`·`extraEntries`).
#  - **파일을 지우지는 않는다**: 예전 수동 설치가 남긴 `drivers_x64/`·`icons/` 등은 그대로 남는다(덮어쓰기만 한다).
#  - 펌웨어 NVRAM 의 부팅 항목은 만들지 않는다(`efibootmgr` 으로 따로 등록; plan §12 (a)).
#  - 테마: bobafetthotmail/refind-theme-regular(원 저자 munlik 의 포크) 2023-08-28 리비전(fb58a79) — 이전 수동 설치 사본과 가장 가까운 시점(쓰는 파일 중 3개 차이).
#    아이콘은 원본 그대로, 배경은 검정·선택 영역은 흰색 30% (`mods/_tools/refind-theme/gen.py`).
mkMod __curPos "rEFInd 메뉴(nix 관리): 본체·설정·검정 테마를 ESP 에 둔다" ({
  cfg,
  config,
  lib,
  pkgs,
  ...
}: let
  theme = pkgs.fetchFromGitHub {
    owner = "bobafetthotmail";
    repo = "refind-theme-regular";
    rev = "fb58a797e5d8667a80afd7e71d719cf951edfa15";
    hash = "sha256-QFBYPvMksZI8Bb9uO5nZHmu36w2xfSpPW5Ljpsv6XLY=";
  };
  py = pkgs.python3.withPackages (p: [p.pillow]);
  refindConf = pkgs.writeText "refind.conf" ''
    # nix 가 만든 파일(mods/sys/services/refind.nix) — 직접 고치지 말고 저장소에서 고친다.
    timeout ${toString cfg.timeout}
    use_nvram false
    banner_scale fillscreen
    resolution max
    enable_mouse
    mouse_size 32
    mouse_speed 16
    use_graphics_for osx,linux,windows
    showtools shell, gdisk, memtest, mok_tool, apple_recovery, windows_recovery, about, hidden_tags, reboot, shutdown, firmware, fwupdate
    dont_scan_dirs EFI/nixos,EFI/systemd
    dont_scan_files bootx64.efi
    ${cfg.extraConfig}

    menuentry "NixOS (systemd-boot)" {
        icon     /EFI/refind/themes/refind-theme-regular/icons/128-48/os_nixos.png
        loader   /EFI/systemd/systemd-bootx64.efi
    }
    ${cfg.extraEntries}

    include themes/refind-black/theme.conf
  '';
  # ESP 의 EFI/refind 에 들어갈 트리
  tree = pkgs.runCommand "refind-esp-tree" {nativeBuildInputs = [py];} ''
    mkdir -p $out/themes/refind-theme-regular/icons $out/themes/refind-theme-regular/fonts
    cp ${pkgs.refind}/share/refind/refind_x64.efi $out/refind_x64.efi
    cp ${refindConf} $out/refind.conf
    cp -r ${theme}/icons/128-48 $out/themes/refind-theme-regular/icons/128-48
    cp ${theme}/fonts/source-code-pro-extralight-14.png $out/themes/refind-theme-regular/fonts/
    cp ${theme}/LICENSE $out/themes/refind-theme-regular/LICENSE
    chmod -R u+w $out
    # 원본 테마 구조(icons/128-48)를 gen.py 가 읽을 수 있게 같은 모양의 입력을 쓴다
    python3 ${../../_tools/refind-theme/gen.py} ${theme} $out/themes/refind-black --sel-alpha ${toString cfg.selectionAlpha}
  '';
  esp = config.boot.loader.efi.efiSysMountPoint;
in {
  options = {
    timeout = lib.mkOption {
      type = lib.types.int;
      default = 20;
      description = "Seconds before rEFInd boots the default entry (0 = menu is skipped).";
    };
    selectionAlpha = lib.mkOption {
      type = lib.types.float;
      default = 0.30;
      description = "Opacity multiplier of the white selection highlight on the black background (see mods/_tools/refind-theme/gen.py).";
    };
    extraConfig = lib.mkOption {
      type = lib.types.lines;
      default = "";
      description = "Extra refind.conf lines (global options), placed before the menu entries.";
    };
    extraEntries = lib.mkOption {
      type = lib.types.lines;
      default = "";
      description = "Extra refind.conf menuentry blocks (host-specific volumes, Windows VHDX chain, ...).";
    };
  };
  os = lib.mkIf cfg.enable {
    boot.loader.systemd-boot.extraInstallCommands = ''
      ${pkgs.coreutils}/bin/install -d ${esp}/EFI/refind
      ${pkgs.coreutils}/bin/cp -rfT --no-preserve=mode,ownership ${tree} ${esp}/EFI/refind
    '';
  };
})
