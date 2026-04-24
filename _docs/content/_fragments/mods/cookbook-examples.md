## Cookbook (실전 예시)

아래 예시들은 실제 프로젝트 모듈을 기반으로 한 패턴별 스니펫입니다. API 파라미터의 세부 사항은 [Mod API](../reference/mod-api.md)를 참조하세요.

### 예시 1: 기본 — 패키지 설치 (mkMod)

가장 단순한 형태. NixOS 시스템에 서비스를 추가하고 사용자 그룹을 설정.

```nix
# mods/sys/services/docker.nix
{mkMod, ...}:
mkMod __curPos "Docker Daemon and tools" ({config, ...}: {
  os = {
    virtualisation.docker = {
      enable = true;
      autoPrune.enable = true;
    };
    users.users.${config.workspace.username}.extraGroups = ["docker"];
  };
})
```

- 파일 위치 `mods/sys/services/docker.nix` → 옵션 경로 `mods.sys.services.docker.enable`
- `os` 블록에 `mkIf cfg.enable` 자동 적용

### 예시 2: Dual-Context — NixOS + HM 동시 (mkMod)

시스템 데몬과 사용자 설정을 한 파일에서 모두 선언.

```nix
# mods/sys/services/bluetooth.nix
{mkMod, ...}:
mkMod __curPos "Bluetooth support" ({pkgs, ...}: {
  os = {
    hardware.bluetooth.enable = true;
    services.blueman.enable = true;
  };
  hm = {
    home.packages = [pkgs.bluetuith];
  };
})
```

- `os`는 NixOS 평가 시, `hm`은 Home Manager 평가 시 각각 적용
- 모듈 파일 하나로 양쪽 설정을 관리

### 예시 3: 커스텀 옵션 — options 키 활용

`enable` 외에 사용자 정의 옵션을 추가하는 패턴.

```nix
# mods/gui/base/greeter.nix
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Login greeter (greetd + tuigreet)" ({cfg, pkgs, lib, ...}: {
  options.sessionCmd = lib.mkOption {
    type = lib.types.str;
    description = "Session command passed to tuigreet --cmd";
  };
  os = {
    services.greetd = {
      enable = true;
      settings.default_session.command =
        "${pkgs.tuigreet}/bin/tuigreet --time --cmd '${cfg.sessionCmd}'";
    };
  };
})
```

- `options`에 선언한 `sessionCmd`는 `cfg.sessionCmd`로 접근
- 다른 모듈에서 `mods.gui.base.greeter.sessionCmd = "uwsm start hyprland-uwsm.desktop";`로 설정

### 예시 4: 부모 연쇄 활성화 — mkModOf

`mods.gui.enable = true` 시 자동으로 활성화되는 GUI 앱.

```nix
# mods/gui/apps/vivaldi.nix
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Vivaldi Browser" ({unstable, ...}: {
  hm = {
    home.packages = [
      (unstable.vivaldi.override {proprietaryCodecs = true;})
    ];
  };
})
```

- `mods.gui.enable = true` → `mods.gui.apps.vivaldi.enable = mkDefault true` (연쇄 활성화)
- `<hostname>.toml`에서 `vivaldi = false`로 개별 비활성화 가능

### 예시 5: 부모 귀속 — mkPartOf

자체 toggle 없이 부모와 항상 같이 움직이는 서브파트.

```nix
# mods/gui/base/fuzzel.nix
{mkPartOf, ...}:
mkPartOf "mods.gui" ({config, ...}: {
  hm = {
    programs.fuzzel = {
      enable = true;
      settings.main = {
        terminal = config._module.args.hyprTerm;
        width = 80;
      };
    };
  };
})
```

- enable 옵션 없음 — `mods.gui.enable`이 곧 이 모듈의 활성화 조건
- `cfg`는 `config.mods.gui` (부모)를 가리킴
- 프리셋 TOML에 등록할 필요 없음

### 예시 6: 외부 데이터 — `_data/` + `builtins.readFile`

CSS, 셸 스크립트, XML 등을 별도 파일로 분리하는 패턴.

```nix
# mods/sys/base/zsh.nix
{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({lib, ...}: {
  hm = {
    programs.zsh = {
      enable = true;
      initContent = lib.mkMerge [
        (lib.mkBefore (builtins.readFile ../../_data/zsh/init.pre.zsh))
        (builtins.readFile ../../_data/zsh/init.zsh)
      ];
    };
  };
})
```

- 비-Nix 파일은 `mods/_data/` 하위에 배치
- `_data/`는 `_` prefix이므로 `recursiveImportDir`에서 자동 제외
- `builtins.readFile`은 Nix 인터폴레이션 없이 파일 내용을 그대로 문자열로 읽음

### 예시 7: 항상-켜지는 모듈 — mkPartOf

enable 없이 모든 호스트에 적용되는 베이스 설정.

```nix
# mods/sys/base/core.nix
{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({config, pkgs, ...}: {
  os = {
    users.users.${config.workspace.username} = {
      isNormalUser = true;
      extraGroups = ["wheel"];
      shell = pkgs.zsh;
    };
  };
})
```
