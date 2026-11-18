# msi-summit-me — Secure Boot 운영 지침과 상황별 대응

(작성 2026-11-18, plan `boot-security` S5 실기 경험 기반. 새 노트북에도 거의 그대로 쓴다 — BIOS 메뉴 이름만 기종마다 다르다.)
**실기·시험으로 확인한 절차(§1 의 1~3, §2-2 의 ②~⑤, §2-3, §3 의 확인 부분, `secureboot-doctor status`)와 문서·소스만으로 쓴 절차를 구분한다: 뒤쪽은 제목에 `(미시험)` 을 붙였다.**

## 0. 한눈에
- 구성: UEFI 펌웨어(Secure Boot) → **rEFInd**(서명, 메뉴) → **systemd-boot**(서명) → **lanzaboote 서명 UKI**(`EFI/Linux`, 세대마다) → LUKS 암호 → NixOS(lockdown `integrity`).
- 점검 명령: `secureboot-doctor status`(상태 요약), `verify`, `backup-esp`, `enroll`, `dbx-init`. 도움말은 `secureboot-doctor help`. (Secure Boot 모듈을 켜면 설치된다: `mods/sys/services/secure-boot.nix`)
- 가장 빠른 탈출구: 부팅이 안 되면 **BIOS(Del/F2) → Secure Boot Support = Disabled** → 부팅 → `secureboot-doctor status`. (키는 그대로 남아도 된다.)
- 복구 USB(Ventoy)의 `RECOVERY-secureboot-20261117.txt`·`RECOVERY-addendum-20261118.txt`: ESP 되돌리기·ISO 부팅 절차. **Secure Boot 가 켜진 동안은 이 USB 가 안 뜰 수 있다** → 끄고 들어간다.

## 1. 하면 안 되는 것 / 꼭 지킬 것
1. BIOS 의 **`Restore Factory Keys` / `Install All Factory Default Keys` / `Load Defaults`** 를 켜진 상태로 누르지 않는다 → PK·KEK·db 가 공장 값으로 되돌아가 우리 서명 UKI 가 거부된다(§2-2).
2. BIOS 의 **`Reset To Setup Mode`(= 모든 키 데이터베이스 삭제)** 는 `dbx`(금지 목록)까지 지운다. 하면 §2-3 으로 `dbx` 를 다시 채운다.
3. **`Factory Default Key Provisioning` 은 Disabled 로 둔다**(이 기종 BIOS `Secure Boot → Key Management`). Enabled 면 Setup Mode 가 되자마자 공장 키가 다시 설치되어 키 등록이 안 된다(2026-11-18 실기: 저장할 때마다 PK·KEK·db 가 공장값으로 재작성됨).
4. 서명 키(`/var/lib/sbctl/keys`)는 **암호화해서 오프디스크 사본**을 둔다(현재 USB `sbctl-keys-20261117.tar.age`, 비밀번호는 종이). 키가 유출되면 §2-6.
5. 부팅 사슬을 바꾸는 작업(`nixup` 으로 부트로더·lanzaboote·rEFInd 변경) 전에는 `secureboot-doctor backup-esp` 로 ESP 를 백업하고 **USB 에도 복사**한다.
6. `nixup` 은 dbx 를 건드리지 않는다. dbx 갱신은 fwupd 로 사람이 한다(§3).
7. 커널 모듈(NVIDIA 등 외부 모듈)은 lockdown 때문에 서명 없이는 안 올라온다(이 호스트는 nvidia 모듈을 blacklist, msi-ec 는 인증서 이미지로 해결 — `mods/sys/services/kernel-lockdown.nix`).

## 2. 상황별 대응

### 2-1. 부팅이 안 된다 (`Access Denied`, `Security Violation`, 검은 화면, rEFInd/systemd-boot 로 안 넘어감)
1. BIOS 진입 → `Secure Boot Support` = **Disabled** → 저장 → 부팅. (이 상태가 S5 이전과 같다.)
2. 부팅되면 `secureboot-doctor status`: PK/KEK 가 "공장 기본값과 같음"이면 §2-2, `서명 안 됨` 이 kernel-*.efi 외에 있으면 §2-4.
3. 안 켜지면(ESP 손상 등) 복구 USB → ISO 부팅(Secure Boot 가 꺼져 있어야 함) → `RECOVERY-secureboot-20261117.txt` [B](ESP 를 백업 시점으로 되돌림; 새 백업은 `esp-backup-YYYYMMDD.tar`).

### 2-2. BIOS 업데이트·CMOS 배터리 방전·`Load Defaults` 뒤 키가 공장값으로 돌아갔다
- 증상: Secure Boot 를 켜 둔 채면 우리 서명이 신뢰되지 않아 부팅 실패, 꺼져 있으면 정상 부팅. `secureboot-doctor status` 에서 PK·KEK 가 "공장 기본값과 같음".
- 대응(키를 다시 등록): ① BIOS: Secure Boot Support=Disabled 로 먼저 부팅 → ② BIOS `Factory Default Key Provisioning`=Disabled, `Reset To Setup Mode` 실행 후 **Save & Exit** → ③ 부팅(Setup Mode 에서는 서명 없어도 부팅) → ④ `sudo secureboot-doctor enroll`(= `sbctl enroll-keys --microsoft --firmware-builtin`) → ⑤ BIOS: Secure Boot Support=Enabled, Save & Exit → ⑥ `secureboot-doctor status` 로 확인 → ⑦ dbx 가 비면 §2-3.

### 2-3. `dbx` 가 비었다 (`secureboot-doctor status` 에서 dbx 없음)
- 원인: `Reset To Setup Mode`/`Clear Keys` 가 dbx 를 지웠고 `sbctl enroll-keys` 는 복원하지 않는다.
- 주의(2026-11-18 VM 시험): **fwupd 는 dbx 가 없으면 `Device … has no firmware version` 으로 설치를 거부한다(`--force` 도 소용없음).** 처음 한 번은 직접 채워야 한다.
- 대응: 최신 DBXUpdate 파일을 받는다 — LVFS cab(`fwupdmgr get-updates` 의 `Release` 항목 URL 또는 https://github.com/microsoft/secureboot_objects `PostSignedObjects/DBX/amd64/DBXUpdate.bin`) → `sudo secureboot-doctor dbx-init <파일>`(.bin 또는 .cab). 펌웨어가 KEK 서명을 검증하므로 위조 파일은 거부된다. 이후 갱신은 §3.

### 2-4. `secureboot-doctor verify` 에 서명 안 됨이 있다
- `EFI/nixos/kernel-*.efi` 는 정상(서명 UKI 의 해시로 검증).
- 그 외(`EFI/Linux/*.efi`, `systemd-bootx64.efi`, `refind_x64.efi`, `BOOTX64.EFI`)가 서명 안 됨이면 `nixup` 중 lzbt·rEFInd 단계가 실패했다 → `nixup os --stage` 를 다시 실행하고 `/var/log/nixup/` 의 마지막 로그에서 `lzbt`·`refind:` 줄을 본다. 해결 전에는 **재부팅하지 않는다**(Secure Boot 가 켜져 있으면 해당 항목이 거부된다). 급하면 BIOS 에서 Secure Boot 를 끄고 재부팅.

### 2-5. 설치 USB(Ventoy·NixOS ISO)가 안 뜬다 (미시험)
- Secure Boot 를 켠 동안은 서명 문제로 안 뜰 수 있다(이번에 시험하지 않음). BIOS 에서 Secure Boot Support=Disabled 로 끄고 들어간 뒤 작업이 끝나면 다시 켠다. (rEFInd 의 ISO 항목은 별도 재파티셔닝 계획 `plan/nixstrap-iso-partitions` 참고.)

### 2-6. 서명 키 유출 의심·분실 (미시험)
- 사본이 있으면(USB 암호화 백업) 복호화해서 `/var/lib/sbctl` 에 복원 — `age -d sbctl-keys-….tar.age | sudo tar -C /var/lib/sbctl -xf -`.
- 키를 새로 만들 때: Setup Mode 에서 `sudo sbctl create-keys`(기존 디렉터리를 옮겨 둔 뒤) → `nixup os --stage`(새 db 키로 다시 서명) → §2-2 의 ②~⑤(`secureboot-doctor enroll`). 순서: **새 키로 서명한 UKI 를 ESP 에 먼저 둔 뒤** Setup Mode 로 가야 한다.

### 2-7. 새 노트북·메인보드 교체 (미시험 — §2-2·§2-3 의 단계를 이어 쓴 것)
1. 공장 상태는 보통 dbx 와 MS 키가 이미 있다(`secureboot-doctor status`). 설치(`nixstrap`) 뒤 `secureboot-doctor backup-esp`.
2. 서명 키: 기존 노트북 키를 복원해서 쓰거나(단순) 새로 만든다(`sbctl create-keys`). 백업은 비밀번호로 암호화해서 오프디스크에.
3. BIOS 순서: Secure Boot Mode=Custom → `Factory Default Key Provisioning`=Disabled → `Reset To Setup Mode` → 저장 → NixOS 부팅 → `secureboot-doctor enroll` → Secure Boot Support=Enabled → dbx 가 없으면 §2-3, 있으면 `fwupdmgr`(§3).

### 2-8. ESP 가 지워졌거나 손상됐다 (미시험 — USB 연습은 읽기 전용 확인까지)
- 복구 USB → ISO(Secure Boot 끔) → LUKS 열기 → `/mnt/boot` 에 `esp-backup-*.tar` 복원(USB `RECOVERY-secureboot-20261117.txt` [B]). 또는 NixOS 를 `nixos-enter` 로 열어 `nixup os --stage` 로 lanzaboote 가 ESP 를 다시 만들게 한다(키는 `/var/lib/sbctl` 에 있어야 함).

### 2-9. 이전 세대로 돌아가고 싶다 (미시험)
- systemd-boot 메뉴에서 이전 세대를 고른다. lanzaboote 는 모든 세대를 서명 UKI 로 만든다(`nixup clean` 으로 지운 세대는 없다). 실기로 부팅해 본 것은 최신 세대뿐이다.

### 2-10. 위협 모델과 TPM·FIDO2 선택, 드문 사고 대응 (2026-11-18 논의 정리, 일반 지식·미시험)
**무엇을 막고 무엇을 받아들이나**
- 막는다: 분실·도난(LUKS), 원격 침입(tailscale 전용 접근, hyprlock), 도구 없이 몇 분 안에 하는 부팅 영역 변조(Secure Boot + UKI 해시 + **BIOS 관리자 암호**).
- 받아들인다(확률 낮음): 사적인 공간에서 시간을 들이는 표적 공격 — 뚜껑을 열어 CMOS 를 만지거나, SPI 칩에 클립을 물리거나, DMA·펌웨어 변조. 노트북을 공개된 곳에서 이런 식으로 다루면 눈에 띈다는 점, 그리고 두 번 이상 자리를 비운 사이에 해야 한다는 점이 현실적 장벽이다.
- 주의할 사람·상황: 퇴사 예정자, 야간 시설 인력·외부 방문자, 출장 중(호텔·공항·국경 검사처럼 기기가 오래 내 손을 떠나는 때). 퇴사자는 부팅 보안보다 계정·키 회수가 우선이다.
- **BIOS 관리자 암호를 걸 것**(현재 미설정). 물리 접근자가 BIOS 에서 Secure Boot 를 끄는 길을 막는다. 암호는 서명 키 비밀번호와 같은 종이에 보관. 노트북은 암호 분실 시 제조사 서비스가 필요할 수 있다(기종별로 다름, 이 기종 미확인).

**핵심 원리: 문이 열리는 순간은 사용자가 부팅 코드에 암호를 줄 때뿐**
- ESP 의 실행 파일만으로는 암호화된 `/home`·`/nix/store`·`/var` 를 읽거나 쓸 수 없다. 가짜 initrd 가 암호화된 데이터에 접근하는 때는 **사용자가 그 코드에 복구 암호(또는 FIDO2 PIN+터치)를 줄 때**다. 그때 가짜 코드는 root 로 돌고 있어 루트에 영구 백도어를 심을 수 있다(부팅 뒤에는 ESP 가 실행되는 것이 아니라 루트에 심은 코드가 돈다).
- 그래서 규칙 하나: **부팅이 평소와 다르면(TPM 정책이 깨짐, TOTP 코드가 안 맞음, 암호창이 평소와 다르게 생김) 복구 암호·PIN 을 입력하지 않는다.** 신뢰하는 USB(서명을 믿을 수 있는 설치 USB)로 부팅해 ESP·BIOS 설정을 점검한다.

**TPM+PIN, FIDO2+PIN 차이**
- TPM+PIN: 부팅 체인이 바뀌면 TPM 이 열쇠를 내주지 않아 가짜 코드가 아무것도 못 얻는다. 단 BIOS 업데이트·dbx 갱신·Secure Boot 키 변경도 PCR 7 을 바꿔 재등록이 필요하다(lanzaboote 의 `measuredBoot`·`pcrlock` 옵션이 있으나 실제로 쓰지 않음).
- FIDO2+PIN: 보안키는 **부팅 체인을 확인하지 않는다.** 가짜 initrd 도 사용자가 PIN 과 터치를 하면 해제용 값(hmac-secret 출력)을 받아 갈 수 있다(복제는 못 함). 체인 보호는 Secure Boot + BIOS 암호가 전부 맡는다. LUKS 슬롯은 OR 이라 TPM 슬롯과 FIDO2 슬롯을 같이 두면 체인에 묶이지 않은 FIDO2 가 우회로가 된다.
- 선택 사항: `tpm2-totp`(PCR 7 에 묶은 6자리 코드를 암호창 전에 표시, 폰과 비교)로 이상 신호를 눈에 띄게 할 수 있다. systemd initrd 에 서비스를 직접 만들어야 하고 시험하지 않았다.

**드문 사고(복구 암호를 이상한 상태에서 입력했거나 변조가 확인됨) 대응 = 전부 엎기**
1. 신뢰하는 USB 로 부팅(Secure Boot 끔) → `nixstrap` 모드 2(전체 초기화)로 LUKS 를 새로 포맷한다. 볼륨 키·FIDO2 salt·복구 암호가 모두 새로 만들어져 옛 값은 무효가 된다(`cryptsetup reencrypt` 로 볼륨 키만 바꾸면 슬롯이 남아 가로챈 값으로 다시 열릴 수 있으니 부족하다).
2. 서명 키(`/var/lib/sbctl`)도 새로 만들고 §2-6 처럼 재등록. BIOS 설정·dbx 는 §2-2·§2-3.
3. 데이터는 신뢰하는 백업에서 **선별 복원**(`/home` 통째 복원은 심어진 스크립트·`authorized_keys` 도 가져온다).
4. 디스크 안에 있던 비밀(SSH 키, 토큰, 계정 비밀번호)을 모두 교체.
5. 공격자가 이미 복사해 간 옛 데이터는 되돌릴 수 없다. SPI 칩에 쓴 펌웨어 변조는 재설치로 안 지워진다.

### 2-11. Windows·타사 부트로더와 같이 쓸 때 (미시험)
- `enroll-keys --microsoft` 로 Microsoft 키가 db 에 들어 있어서 Windows 부트 관리자는 신뢰된다. 다만 `--microsoft` 를 빼면 옵션롬·Windows 가 안 뜰 수 있다. 서명 안 된 타사 EFI 는 rEFInd 의 `tools`·`drivers` 로 두지 말고 db 키로 서명한다(`sbsign`).

## 3. dbx 갱신 (fwupd)
- 설정: `mods/sys/services/fwupd.nix`(매시간 타이머는 끔). 부팅 3분 뒤 **마지막 확인이 14일보다 오래됐을 때만** `fwupdmgr refresh`+`get-updates` 를 하고 결과를 `/var/lib/fwupd-check/last-result` 에 남긴다. 갱신이 있으면 journal 에 warning, `secureboot-doctor status` 에도 보인다. **설치는 자동으로 하지 않는다.**
- 수동: `fwupdmgr refresh && fwupdmgr get-updates && sudo fwupdmgr update`(재부팅이 필요하다고 표시되면 재부팅). 적용 뒤 정상 부팅을 확인한다. fwupd 가 ESP 에 새 목록이 막을 부트로더가 있으면 거부한다.
- 주의: dbx 갱신은 되돌리기 어렵다(되돌리려면 Setup Mode). 적용 전에 `secureboot-doctor backup-esp`.

## 4. 알아 둘 사실 (2026-11-18 실기·소스)
- 이 기종 BIOS(AMI UEFI 2.80) Secure Boot 메뉴: `Secure Boot Support`, `Install All Factory Default Keys`, `Reset To Setup Mode`, `Key Management → Factory Default Key Provisioning`. `Secure Boot Mode: Custom`.
- lanzaboote 는 `EFI/nixos` 를 통째로 정리한다(`lzbt` 설치 뒤 옛 방식 항목은 복구 불가) — 그래서 설치 전에 ESP 백업.
- rEFInd 의 수동 `menuentry` 는 `vol_efi` 뱃지를 붙인다. 테마에 그 아이콘이 없으면 검정-노랑 줄무늬 대체 이미지가 나온다(`mods/sys/services/refind.nix` 가 아이콘을 복사).
- 펌웨어는 인증서 만료일을 확인하지 않는다(Microsoft KEK CA 2011 은 2026-06 만료 표시지만 계속 신뢰됨 — 추정, 소스 미확인). 2023 인증서(KEK 2K CA 2023 등)도 db/KEK 에 함께 등록돼 있다.
