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

### 2-10. 앞으로 TPM(S6)을 쓸 때 (미시험, 일반 지식)
- 아직 TPM 으로 암호를 풀지 않는다. 쓰기 시작하면 BIOS 설정·Secure Boot 키·dbx 변경이 **PCR 7** 을 바꿔 TPM 해제가 실패할 수 있다 → 그때는 복구 암호(8단어) 입력. 키·dbx 를 바꿀 계획이면 TPM 슬롯을 다시 등록한다(`plan/boot-security` S6).

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
