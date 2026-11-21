# TPM2+PIN(pcrlock) 로 LUKS 를 initrd 에서 풀기 위한 NixOS 설정 조각 (plan/boot-security 6-S6·6-S6a).
# luks mod(mods/sys/services/luks.nix)와 VM 시험(core/scripts/tests/vm/sb-pcrlock.nix)이 같은 것을 쓴다 — 시험이 실제 설정을 그대로 검증하게 하려고 분리했다.
# 반환값은 NixOS 설정 attrset 이다(모듈 함수가 아님): `config = lib.mkIf cond (import ./luks-tpm2.nix { inherit lib pkgs config; name = ...; })`.
#
# 각 항목이 필요한 이유(VM 시험으로 확인 — 빠뜨리면 에러 없이 보호가 사라진다):
#  - systemd-pcrphase-initrd·systemd-pcrosseparator 를 initrd 에서 시작해야 이벤트 로그에 750-enter-initrd·750-os-separator 가 생기고, 그래야
#    `systemd-pcrlock make-policy` 가 PCR 7(Secure Boot 정책)을 보호 대상에 남긴다. 없으면 PCR 7 이 조용히 빠진다.
#  - 정책은 ESP 의 loader/credentials/pcrlock.*.cred 로 initrd 에 전달된다(lanzaboote 스텁이 붙인다) — 별도 설정은 필요 없다.
{
  lib,
  pkgs,
  config,
  name, # LUKS 매퍼 이름(cryptroot 등) — 경고 유닛이 systemd-cryptsetup@<name> 의 저널을 본다
  failWarning ? true, # TPM 이 정책 불일치로 거부하면 복구 암호창 전에 영어 경고를 화면에 띄운다
  kernelModules ? ["tpm_tis" "tpm_crb"],
}: let
  warnScript = pkgs.writeShellScript "tpm-fail-warning" ''
    journalctl -f -n0 -o cat -u systemd-cryptsetup@${name}.service | grep -m1 -q "does not match current system state" || exit 0
    echo
    echo "=================================================================="
    echo " WARNING: the TPM refused to unlock this disk."
    echo " The boot state (Secure Boot keys / dbx / firmware / boot files)"
    echo " differs from what was registered."
    echo
    echo " If you did NOT just change them yourself, do NOT type the recovery"
    echo " passphrase. Power off and check with your trusted USB (nixseal)."
    echo "=================================================================="
    echo
  '';
  # systemd 261 부터 `750-os-separator` pcrlock 컴포넌트(PCR 0~7·9·12~14)와 그 측정 유닛이 생겼다. 260.x 에는 둘 다 없다(유닛 파일이 없어 initrd 빌드가 실패한다).
  # 261 에서 이 유닛이 없으면 make-policy 가 PCR 7 을 조용히 뺀다(VM 시험 확인). 260.1 에서는 아래 VM 시험(저장소 nixpkgs)이 PCR 7 유지를 확인한다.
  hasOsSeparator = lib.versionAtLeast config.systemd.package.version "261";
in {
  boot.initrd.availableKernelModules = kernelModules;
  boot.initrd.systemd.storePaths =
    [
      "${config.systemd.package}/lib/systemd/systemd-pcrextend"
      "${pkgs.tpm2-tss}/lib"
      "${pkgs.openssl.out}/lib"
    ]
    ++ lib.optional failWarning warnScript;
  boot.initrd.systemd.additionalUpstreamUnits = ["systemd-pcrphase-initrd.service"] ++ lib.optional hasOsSeparator "systemd-pcrosseparator.service";
  boot.initrd.systemd.services =
    {
      systemd-pcrphase-initrd.wantedBy = ["initrd.target"];
    }
    // lib.optionalAttrs hasOsSeparator {
      systemd-pcrosseparator.wantedBy = ["initrd.target"];
    }
    // lib.optionalAttrs failWarning {
      tpm-fail-warning = {
        description = "Warn when the TPM refuses to unlock the disk";
        wantedBy = ["initrd.target"];
        unitConfig.DefaultDependencies = false;
        serviceConfig = {
          Type = "simple";
          ExecStart = "${warnScript}";
          StandardOutput = "journal+console"; # 화면(콘솔)에 뜨고 저널에도 남는다
        };
      };
    };
  systemd.additionalUpstreamSystemUnits = ["systemd-pcrphase.service" "systemd-pcrphase-sysinit.service"];
  environment.etc.systemd-pcrlock-builtin = {
    target = "pcrlock.d";
    source = "${config.systemd.package}/lib/pcrlock.d";
  };

  # 정책 불일치(「TPM policy does not match current system state」)가 저널에 나오면 한 번 경고한다.
  # 부팅 콘솔(VT)에는 한글 글꼴이 없어 영어로 쓴다. 경고만 하고 아무 것도 막지 않는다(복구 암호 입력은 그대로 가능).
  boot.initrd.systemd.extraBin = lib.mkIf failWarning {
    journalctl = "${config.systemd.package}/bin/journalctl";
    grep = "${pkgs.gnugrep}/bin/grep";
  };
}
