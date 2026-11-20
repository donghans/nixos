{mkMod, ...}:
# TPM+PIN 으로 부팅한 직후 greetd 로그인·gnome-keyring 을 비밀번호 입력 없이 여는 옵션 (plan/boot-doctor-keyring §11-B). **기본 꺼짐.**
#  - 부팅 PIN 은 로그인 비밀번호로 쓰이지 않는다. PIN 은 TPM 에 봉인해 둔 별도의 강한 비밀번호를 푸는 열쇠이고, PAM 은 그 비밀번호만 읽는다.
#  - 켠 뒤 한 번 `sudo nixseal pw seal` 로 봉인해야 동작한다(그 전에는 평소처럼 비밀번호를 묻는다). 자세한 운영·한계: hosts/msi-summit-me/SECURE-BOOT.md §2-15.
#  - 실제 설정은 core/lib/tpm-login.nix(VM 시험이 같은 파일을 검증한다).
mkMod __curPos "TPM+PIN 부팅 직후 greetd 로그인·키링 자동 해제(봉인된 비밀번호, 기본 꺼짐)" ({
  cfg,
  lib,
  pkgs,
  config,
  ...
}: {
  options = {
    user = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "봉인된 비밀번호로 로그인할 계정(한 계정). 다른 계정은 매 부팅 첫 시도가 한 번 실패한 뒤 평소처럼 비밀번호를 묻는다.";
    };
    cacheSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 120;
      description = "풀어 둔 비밀번호(login-pw)가 커널 키링에 머무는 최대 시간(초). 부팅~로그인 화면이 이보다 오래 걸리면 평소 비밀번호 입력으로 돌아간다(의도된 안전 실패).";
    };
  };
  os = lib.mkIf cfg.enable (lib.mkMerge [
    {
      assertions = [
        {
          assertion = cfg.user != "";
          message = "mods.sys.services.tpm-login.user: 봉인된 비밀번호로 로그인할 계정 이름을 정해야 한다.";
        }
        {
          assertion = config.mods.sys.services.luks.enable && config.mods.sys.services.luks.tpm2;
          message = "mods.sys.services.tpm-login: TPM+PIN 으로 연 부팅 PIN 이 필요하다 — mods.sys.services.luks.enable 과 luks.tpm2 를 켜라.";
        }
        {
          assertion = config.services.greetd.enable;
          message = "mods.sys.services.tpm-login: greetd 로그인 화면(mods.gui.base.greeter)이 필요하다.";
        }
        {
          assertion = (config.security.pam.services ? greetd) && config.security.pam.services.greetd.enableGnomeKeyring;
          message = "mods.sys.services.tpm-login: greetd 의 PAM 에 gnome-keyring 이 켜져 있어야 한다(mods/gui/base/polkit.nix) — 규칙의 순서 기준이 그 스택이다.";
        }
      ];
    }
    (import ../../../core/lib/tpm-login.nix {
      inherit lib pkgs config;
      inherit (cfg) user cacheSeconds;
      greeterUser = config.services.greetd.settings.default_session.user or "greeter";
    })
  ]);
})
