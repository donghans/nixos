# NixOS + TPM WebAuthn PRF — 선언형 구성 메모

Tailpass 생체인증(WebAuthn PRF)을 NixOS + Vivaldi 환경에서 선언형으로 구성하는 방법.

---

## 배경

- Tailpass는 WebAuthn PRF 확장을 통해 pinMaterial을 보호한다 (v0.7~).
- Linux에서는 Windows Hello / Touch ID에 해당하는 플랫폼 인증자가 없다.
- TPM 2.0이 있는 머신에서는 tpm-fido 계열 도구로 이를 대체할 수 있다.

---

## 옵션 A — `tpm-fido` (nixpkgs 공식)

```nix
environment.systemPackages = [ pkgs.tpm-fido ];
```

- PRF 지원 여부: 원본(psanford/tpm-fido)은 hmac-secret 기반으로 PRF를 지원한다고
  검색 결과에서 언급됨. 실제 Tailpass PRF 동작 여부는 테스트 필요.
- NixOS 모듈 없음 → native messaging 등록은 아래 home-manager 옵션으로 별도 처리.

---

## 옵션 B — `tpm-fido2-prf` (nixpkgs 미등록, 커스텀 derivation 필요)

PRF 확실히 지원하는 포크. vitorpy/tpm-fido2-prf + vitorpy/tpm-fido2-extension 세트.

```nix
# flake.nix 또는 별도 패키지 파일
tpm-fido2-prf = pkgs.buildGoModule {
  pname = "tpm-fido2-prf";
  version = "0.1.0"; # 최신 태그 확인 필요
  src = pkgs.fetchFromGitHub {
    owner = "vitorpy";
    repo  = "tpm-fido2-prf";
    rev   = "main"; # 고정 커밋 해시 권장
    hash  = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="; # nix hash 계산 필요
  };
  vendorHash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="; # go mod vendor 해시
};
```

hash 계산:
```bash
nix-prefetch-github vitorpy tpm-fido2-prf
# 또는
nix flake prefetch github:vitorpy/tpm-fido2-prf
```

---

## Vivaldi — Native Messaging 선언형 등록

home-manager에 `programs.vivaldi.nativeMessagingHosts` 옵션이 있다.

```nix
# home-manager 설정
programs.vivaldi = {
  enable = true;
  nativeMessagingHosts = [
    pkgs.tpm-fido          # 옵션 A
    # 또는 커스텀 tpm-fido2-prf  # 옵션 B
  ];
};
```

- 이 옵션은 `~/.config/vivaldi/NativeMessagingHosts/` 에 JSON 매니페스트를 생성한다.
- Chrome/Chromium도 같은 방식: `programs.chromium.nativeMessagingHosts`

---

## Vivaldi — Chrome 확장(tpm-fido2-extension) 선언형 등록

```nix
programs.vivaldi = {
  enable = true;
  extensions = [
    { id = "<tpm-fido2-extension의 ID>"; }
    # update_url 없으면 Chrome Web Store에서 가져옴
    # 자체 호스팅 시:
    # { id = "..."; updateUrl = "https://tailpass.internal/api/v1/extension/updates.xml"; }
  ];
};
```

tpm-fido2-extension의 Extension ID는 CRX 서명 키에서 결정된다.
vitorpy의 릴리스 페이지에서 확인하거나, 개발자 모드로 로드 후 chrome://extensions에서 확인.

---

## Policy 파일 경로 (Linux)

엔터프라이즈 Policy로 확장을 강제 설치하는 경우 경로:

| 브라우저 | 경로 |
|---|---|
| Chromium | `/etc/chromium/policies/managed/` |
| Google Chrome | `/etc/opt/chrome/policies/managed/` |
| Vivaldi | `/etc/chromium/policies/managed/` (Chromium과 공유) |
| Brave | `/etc/brave/policies/managed/` |
| Edge | `/etc/opt/edge/policies/managed/` |
| Firefox | `/etc/firefox/policies/policies.json` (형식 다름) |

NixOS에서 선언형으로 관리:
```nix
environment.etc."chromium/policies/managed/tailpass.json".text = builtins.toJSON {
  ExtensionInstallForcelist = [
    "<extension-id>;https://tailpass.internal/api/v1/extension/updates.xml"
  ];
};
```

---

## TPM 2.0 사전 조건

- TPM 2.0 칩 필요 (대부분의 2016년 이후 노트북에 내장)
- NixOS에서 TPM 활성화:
  ```nix
  security.tpm2.enable = true;
  security.tpm2.pkcs11.enable = true;  # 선택적
  ```
- 사용자를 `tss` 그룹에 추가:
  ```nix
  users.users.donghans.extraGroups = [ "tss" ];
  ```

---

## 지문 리더가 있는 경우 (ThinkPad 등)

mc256/tpm-fido2-thinkpad-linux: 지문 + TPM 연동, Chrome 확장 불필요.
nixpkgs 미등록 → buildGoModule으로 커스텀 derivation 필요.
fprintd 필요:
```nix
services.fprintd.enable = true;
```

---

## 참고 링크

- [tpm-fido (nixpkgs)](https://mynixos.com/nixpkgs/package/tpm-fido)
- [programs.vivaldi.nativeMessagingHosts (home-manager)](https://mynixos.com/home-manager/option/programs.vivaldi.nativeMessagingHosts)
- [tpm-fido2-prf (GitHub)](https://github.com/vitorpy/tpm-fido2-prf)
- [tpm-fido2-extension (GitHub)](https://github.com/vitorpy/tpm-fido2-extension)
- [tpm-fido2-thinkpad-linux (GitHub)](https://github.com/mc256/tpm-fido2-thinkpad-linux)
- [Making Confer.to Work on Linux with TPM-backed WebAuthn (2025-12)](https://vitorpy.com/blog/2025-12-25-confer-to-linux-tpm-fido2-prf/)
