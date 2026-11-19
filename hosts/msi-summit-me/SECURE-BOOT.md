# msi-summit-me — Secure Boot 운영 지침과 상황별 대응

(작성 2026-11-18, plan `boot-security` S5 실기 경험 기반. 새 노트북에도 거의 그대로 쓴다 — BIOS 메뉴 이름만 기종마다 다르다.)
**실기·시험으로 확인한 절차(§1 의 1~3, §2-2 의 ②~⑤, §2-3, §3 의 확인 부분, `nixseal sb status`)와 문서·소스만으로 쓴 절차를 구분한다: 뒤쪽은 제목에 `(미시험)` 을 붙였다.**

## 0. 한눈에
- 구성: UEFI 펌웨어(Secure Boot) → **rEFInd**(서명, 메뉴) → **systemd-boot**(서명) → **lanzaboote 서명 UKI**(`EFI/Linux`, 세대마다) → LUKS 암호 → NixOS(lockdown `integrity`).
- 점검 명령: `nixseal sb status`(상태 요약), `verify`, `backup-esp`, `enroll`(키만 등록), `dbx`(빈 dbx 채우기)·`dbx-update`(fwupd 갱신 적용) — **둘 다 자동으로 하지 않고**, dbx 가 바뀌면 TPM 등록이 깨지므로 로그인 때 뜨는 알림(`sb-notify`)을 보고 직접 한다. 시작 전에 「집이고 곁에 낯선 사람이 없는지·바로 재부팅할 수 있는지」 확인을 묻는다. 도움말은 `nixseal help`·`nixseal sb help`. LUKS 쪽은 `nixseal luks slots|backup|verify|restore|reseal`, 한 화면 요약은 `nixseal status`. (Secure Boot 모듈을 켜면 설치된다: `mods/sys/services/secure-boot.nix`)
- 가장 빠른 탈출구: 부팅이 안 되면 **BIOS(Del/F2) → Secure Boot Support = Disabled** → 부팅 → `nixseal sb status`. (키는 그대로 남아도 된다.)
- 복구 USB(Ventoy)의 `RECOVERY-secureboot-20261117.txt`·`RECOVERY-addendum-20261118.txt`: ESP 되돌리기·ISO 부팅 절차. **Secure Boot 가 켜진 동안은 이 USB 가 안 뜰 수 있다** → 끄고 들어간다.

## 1. 하면 안 되는 것 / 꼭 지킬 것
1. BIOS 의 **`Restore Factory Keys` / `Install All Factory Default Keys` / `Load Defaults`** 를 켜진 상태로 누르지 않는다 → PK·KEK·db 가 공장 값으로 되돌아가 우리 서명 UKI 가 거부된다(§2-2).
2. BIOS 의 **`Reset To Setup Mode`(= 모든 키 데이터베이스 삭제)** 는 `dbx`(금지 목록)까지 지운다. 하면 §2-3 으로 `dbx` 를 다시 채운다.
3. **`Factory Default Key Provisioning` 은 Disabled 로 둔다**(이 기종 BIOS `Secure Boot → Key Management`). Enabled 면 Setup Mode 가 되자마자 공장 키가 다시 설치되어 키 등록이 안 된다(2026-11-18 실기: 저장할 때마다 PK·KEK·db 가 공장값으로 재작성됨).
4. 서명 키(`/var/lib/sbctl/keys`)는 **암호화해서 오프디스크 사본**을 둔다(현재 USB `sbctl-keys-20261117.tar.age`, 비밀번호는 종이). 키가 유출되면 §2-6.
5. 부팅 사슬을 바꾸는 작업(`nixup` 으로 부트로더·lanzaboote·rEFInd 변경) 전에는 `nixseal sb backup-esp` 로 ESP 를 백업하고 **USB 에도 복사**한다.
6. `nixup` 은 dbx 를 건드리지 않는다. dbx 갱신은 fwupd 로 사람이 한다(§3).
7. 커널 모듈(NVIDIA 등 외부 모듈)은 lockdown 때문에 서명 없이는 안 올라온다(이 호스트는 nvidia 모듈을 blacklist, msi-ec 는 인증서 이미지로 해결 — `mods/sys/services/kernel-lockdown.nix`).

## 2. 상황별 대응

### 2-1. 부팅이 안 된다 (`Access Denied`, `Security Violation`, 검은 화면, rEFInd/systemd-boot 로 안 넘어감)
1. BIOS 진입 → `Secure Boot Support` = **Disabled** → 저장 → 부팅. (이 상태가 S5 이전과 같다.)
2. 부팅되면 `nixseal sb status`: PK/KEK 가 "공장 기본값과 같음"이면 §2-2, `서명 안 됨` 이 kernel-*.efi 외에 있으면 §2-4.
3. 안 켜지면(ESP 손상 등) 복구 USB → ISO 부팅(Secure Boot 가 꺼져 있어야 함) → `RECOVERY-secureboot-20261117.txt` [B](ESP 를 백업 시점으로 되돌림; 새 백업은 `esp-backup-YYYYMMDD.tar`).

### 2-2. BIOS 업데이트·CMOS 배터리 방전·`Load Defaults` 뒤 키가 공장값으로 돌아갔다
- 증상: Secure Boot 를 켜 둔 채면 우리 서명이 신뢰되지 않아 부팅 실패, 꺼져 있으면 정상 부팅. `nixseal sb status` 에서 PK·KEK 가 "공장 기본값과 같음".
- 대응(키를 다시 등록): ① BIOS: Secure Boot Support=Disabled 로 먼저 부팅 → ② BIOS `Factory Default Key Provisioning`=Disabled, `Reset To Setup Mode` 실행 후 **Save & Exit** → ③ 부팅(Setup Mode 에서는 서명 없어도 부팅) → ④ `sudo nixseal sb enroll`(= `sbctl enroll-keys --microsoft --firmware-builtin`, **키만 등록**) → ⑤ BIOS: Secure Boot Support=Enabled, Save & Exit → ⑥ `nixseal sb status` 로 확인(dbx 가 채워졌는지 포함). dbx 가 비어 있으면 로그인 때 알림이 뜬다 — §2-3 의 `sudo nixseal sb dbx`.

### 2-3. `dbx` 가 비었다 (`nixseal sb status` 에서 dbx 없음)
- 원인: `Reset To Setup Mode`/`Clear Keys` 가 dbx 를 지웠고 `sbctl enroll-keys` 는 복원하지 않는다.
- 주의(2026-11-18 VM 시험): **fwupd 는 dbx 가 없으면 `Device … has no firmware version` 으로 설치를 거부한다(`--force` 도 소용없음).** 이유(fwupd `plugins/uefi-dbx/fu-uefi-dbx-device.c` 확인, 2026-11-19): 버전을 「dbx 의 마지막 Microsoft SHA256 항목」을 LVFS·quirk 목록과 대조해 정하는데, 변수가 없으면 `version_raw=0` 으로 끝나 버전이 안 정해진다(항목 개수로 세던 것은 옛 `org.uefi.dbx` 방식). 처음 한 번은 직접 채워야 한다.
- 대응: 로그인 때 `sb-notify` 가 「dbx 가 비어 있습니다」 긴급 알림을 보낸다(알림 센터 `notif` 에서 명령을 복사). `sudo nixseal sb dbx`(「집이고 바로 재부팅」 확인을 묻는다)가 저장소에 커밋·해시 고정된 내장 DBXUpdate(`mods/sys/services/secure-boot.nix` 의 `dbxInit`)를 채운다 — 키가 등록된 User Mode 에서만(Setup Mode 면 먼저 `enroll`). **자동으로 하지 않는다**: dbx 가 바뀌면 PCR 7 이 달라져 TPM+PIN 등록이 깨지므로 사용자가 알고 하게 한다(채운 뒤 재부팅해서 복구 암호를 한 번 입력하고 TPM 을 다시 등록). 오래된 파일이어도 처음 채우기에는 충분하고 이후 갱신은 fwupd 가 한다. 펌웨어가 KEK 서명을 검증하므로 위조 파일은 거부된다. 이후 갱신은 §3.

### 2-4. `nixseal sb verify` 에 서명 안 됨이 있다
- `EFI/nixos/kernel-*.efi` 는 정상(서명 UKI 의 해시로 검증).
- 그 외(`EFI/Linux/*.efi`, `systemd-bootx64.efi`, `refind_x64.efi`, `BOOTX64.EFI`)가 서명 안 됨이면 `nixup` 중 lzbt·rEFInd 단계가 실패했다 → `nixup os --stage` 를 다시 실행하고 `/var/log/nixup/` 의 마지막 로그에서 `lzbt`·`refind:` 줄을 본다. 해결 전에는 **재부팅하지 않는다**(Secure Boot 가 켜져 있으면 해당 항목이 거부된다). 급하면 BIOS 에서 Secure Boot 를 끄고 재부팅.

### 2-5. 설치 USB(Ventoy·NixOS ISO)가 안 뜬다 (미시험)
- Secure Boot 를 켠 동안은 서명 문제로 안 뜰 수 있다(이번에 시험하지 않음). BIOS 에서 Secure Boot Support=Disabled 로 끄고 들어간 뒤 작업이 끝나면 다시 켠다. (rEFInd 의 ISO 항목은 별도 재파티셔닝 계획 `plan/nixstrap-iso-partitions` 참고.)

### 2-6. 서명 키 유출 의심·분실 (미시험)
- 사본이 있으면(USB 암호화 백업) 복호화해서 `/var/lib/sbctl` 에 복원 — `age -d sbctl-keys-….tar.age | sudo tar -C /var/lib/sbctl -xf -`.
- 키를 새로 만들 때: Setup Mode 에서 `sudo sbctl create-keys`(기존 디렉터리를 옮겨 둔 뒤) → `nixup os --stage`(새 db 키로 다시 서명) → §2-2 의 ②~⑤(`nixseal sb enroll`). 순서: **새 키로 서명한 UKI 를 ESP 에 먼저 둔 뒤** Setup Mode 로 가야 한다.

### 2-7. 새 노트북·메인보드 교체 (미시험 — §2-2·§2-3 의 단계를 이어 쓴 것)
1. 공장 상태는 보통 dbx 와 MS 키가 이미 있다(`nixseal sb status`). 설치(`nixstrap`) 뒤 `nixseal sb backup-esp`.
2. 서명 키: 기존 노트북 키를 복원해서 쓰거나(단순) 새로 만든다(`sbctl create-keys`). 백업은 비밀번호로 암호화해서 오프디스크에.
3. BIOS 순서: Secure Boot Mode=Custom → `Factory Default Key Provisioning`=Disabled → `Reset To Setup Mode` → 저장 → NixOS 부팅 → `nixseal sb enroll` → Secure Boot Support=Enabled → dbx 가 없으면 §2-3, 있으면 `fwupdmgr`(§3).

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
- **TPM+PIN 이 정상적으로 깨지는 경로(PCR 7 을 정책으로 쓸 때, 2026-11-19 정리 — 일반 지식·미시험)**: ① dbx·db·KEK 변경(`nixseal sb dbx`, `fwupdmgr update` — 둘 다 알림을 보고 **내가 직접** 하므로 예상된 변경) ② BIOS·펌웨어 업데이트 ③ CMOS 초기화(배터리 탈착·방전: 설정과 보안 암호가 초기화되고 키가 공장값으로 돌아갈 수 있음) ④ Secure Boot 키 재등록(`nixseal sb enroll`) ⑤ 이 노트북에서 Windows 를 부팅할 때 Windows Update 가 db·dbx 를 서비스함. 커널·initrd 업데이트는 같은 키로 서명하므로 PCR 7 을 바꾸지 않는다(PCR 4·11 에 묶으면 매번 깨지므로 그렇게 하지 않는다 — D3). **규칙: TPM 이 안 풀리는데 위 ①~⑤ 를 직전에 내가 한 적이 없으면 복구 암호를 입력하지 않고 신뢰 USB 로 점검한다.** 예상된 변경 직후의 첫 부팅이라면 복구 암호를 한 번 입력하고 TPM 을 다시 등록한다 — 그때는 변경한 뒤 **자리를 비우지 말고 바로 재부팅**한다(그 사이에 부팅 체인이 바꿔치기될 틈을 없애려고).
- **dbx 변경과 TPM 갱신을 한 번에(2026-11-19 문서 확인, 미시험)**: `systemd-pcrlock`(systemd 260.1 에 있음, 문서에 「experimental」)이 이 용도다. `lock-secureboot-policy` 가 **현재 EFI 변수(SecureBoot·PK·KEK·db·dbx)로 다음 부팅의 PCR 7 측정값을 미리 계산**하고, `make-policy` 가 그 예측으로 TPM NV 인덱스의 정책을 갱신한다. LUKS 슬롯을 `systemd-cryptenroll --tpm2-pcrlock=…`(+`--tpm2-with-pin=yes`)로 등록해 두면 **슬롯은 그대로이고 정책만 갱신**되므로, 흐름은 「dbx 갱신(`nixseal sb dbx-update`) → `systemd-pcrlock lock-secureboot-policy && systemd-pcrlock make-policy` → 재부팅(복구 암호 없이 PIN 으로 열림)」이 된다(문서는 SecureBoot 정책을 바꾸기 전에 `unlock-firmware-config` 를 권한다). **아직 TPM+PIN(S6)이 없어서 구현·시험하지 않았다.** S6 때 swtpm VM 에서 이 흐름(변경 → 정책 갱신 → 재부팅 → PIN 만으로 열림)을 먼저 재현하고, 되면 `dbx-update` 끝에 정책 갱신을 붙인다. 안 되면(예측이 어긋나면) 지금처럼 복구 암호 한 번 + 재등록.
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

### 2-12. 사고 때 LUKS 를 전부 엎는다 — `nixseal luks reseal` (2026-11-19 구현, 파일 이미지·루프 장치로 시험, 실기 디스크·실제 FIDO2/TPM 은 미시험)
- **언제**: TPM 이 의도하지 않게 깨졌거나 변조·유출이 의심될 때(§2-10). 평소 부팅 편의용이 아니다. 헤더 백업을 가진 쪽이 계속 열 수 없게 하려면 슬롯만 바꾸지 말고 **마스터키를 바꿔야** 하고, 이 명령이 그 일을 한다.
- **준비**: 신뢰 USB(NixOS ISO)로 부팅한 **ISO 안에서만** 한다(설치된 시스템에서는 장치가 열려 있어 거부된다). **디스크 안에만 있는 소중한 데이터는 먼저 디스크 밖에 백업**한다(시작 전에 `백업했음` 입력으로 확인을 묻는다 — 아래 「정전 위험」). 충전기도 연결한다(안 되어 있으면 경고만 한다 — 안전의 근거는 아래 백업이다). 백업을 둘 **USB 를 마운트**한다(`/tmp` 같은 RAM 디스크는 거부 — 재부팅하면 사라진다). 종이와 펜을 준비한다. 현재 복구 암호(8단어)를 안다.
- **실행**: `sudo nixseal luks reseal --backup-dir <마운트한 USB 경로> /dev/disk/by-partlabel/cryptroot`
  1. 현재 복구 암호를 묻는다. 새 8단어 복구 암호와 QR 을 보여 준다 → **종이에 적고 Enter**(화면이 지워진다) → 종이를 보고 다시 입력한다. 3번 틀리면 중단하며 **여기까지는 디스크가 그대로**다.
  2. 대상 장치 정보를 보여 주고 **장치 경로를 직접 입력**해야 진행한다.
  3. 되돌림용 헤더 백업을 만들고, 새 암호를 새 슬롯으로 추가해 열리는지 확인한 뒤 `cryptsetup reencrypt` 를 시작한다(디스크 크기에 비례해 오래 걸린다).
  4. 끝나면 새 암호로 열림을 확인하고 옛 FIDO2·TPM 토큰을 지운 뒤, **복구 암호만 등록된 초기 상태의 헤더 백업을 하나** 남기고 되돌림용 백업을 지운다.
- **끝난 뒤(사람이 한다)**: 새 종이 보관·옛 종이 폐기, **옛 헤더 백업은 무효이니 삭제**, 설치된 시스템에서 새 복구 암호로 부팅한 뒤 FIDO2(`systemd-cryptenroll`)·나중에 TPM+PIN 을 다시 등록한다(슬롯이 전부 지워졌다).
- **중간에 멈췄을 때**(정전·실수로 끔·오류): **헤더 백업을 복원하지 말고** 같은 장치로 `sudo nixseal luks reseal --backup-dir <USB> --resume /dev/disk/by-partlabel/cryptroot` 를 실행한다(새 복구 암호 필요). `--resume` 은 먼저 `cryptsetup repair` 를 하고 이어서 끝낸다. 프로세스만 `kill -9` 한 경우와, VM 에서 전원을 갑자기 끊은 경우(reencrypt 앞쪽·중간 지점) 모두 이렇게 데이터가 보존된 채 끝났다.
- **정전 위험 — 후반부에서는 복구하지 못할 수 있다(2026-11-19 VM 시험, cryptsetup 2.8.6)**: 전원이 reencrypt 의 **후반부**(1GB 시험 디스크에서 끝나기 약 1.5~2초 전, 4GB 에서 약 3초 전 — 디스크가 커질수록 길어지는 것으로 보이나 비례 여부는 확정 못 함)에서 끊기면 재부팅 뒤 `repair`·`--resume` 이 모두 `No usable keyslot is available` 로 실패하고 새 암호로도 열리지 않았다(슬롯이 `luks2` 1개 + `reencrypt` 1개만 남음). 복구가 옛 볼륨 키(digest 0)를 요구하는데 옛 슬롯은 이미 지워졌기 때문이다. 같은 결과가 `--resilience journal`, 옛 슬롯을 남기는 방식에서도 나왔다. 되돌림용 백업에서 옛 볼륨 키를 꺼내 새 볼륨 키와 함께 `reencrypt --resume-only --volume-key-file … --new-volume-key-file …` 로 열리게는 만들 수 있었으나 **데이터 해시가 달라졌다(손상)**. 즉 이 구간의 정전은 **데이터 손실로 이어질 수 있다고 봐야 한다.** 그래서 **디스크 밖 백업을 이 명령의 전제**로 둔다(배터리·충전기는 확률을 줄일 뿐 보장하지 못한다). 이 명령은 시작 전에 `백업했음` 입력으로 이를 확인하고, 충전기가 없거나 배터리가 낮으면 경고만 한다. 앞쪽에서 끊긴 경우는 안전했다(20%·50%·70% 지점 등).
- **하면 안 되는 것**
  - **reencrypt 를 시작한 뒤에 옛(또는 되돌림용) 헤더 백업을 복원하지 않는다** — 리허설에서 복원 뒤 데이터 해시가 달라졌다(깨짐). 되돌림용 백업은 「시작 전에 실패」했을 때만 쓴다(화면에도 같은 경고가 나온다).
  - 새 복구 암호를 종이에 적기 전에 Enter 를 누르지 않는다(그 화면은 다시 볼 수 없다).
  - 도중에 전원을 끄거나 충전기를 빼지 않는다. ssh 로 하지 않는다(스크롤백에 암호가 남는다).
  - 디스크 안에만 있는 소중한 데이터를 디스크 밖에 백업하지 않은 채 시작하지 않는다(위 정전 위험).
  - 설치된 시스템 위에서 하려고 우회하지 않는다(거부되는 것이 정상이다).
- **시험하지 못한 것**: 실제 NVMe 디스크에서의 소요 시간과 후반부 위험 구간의 실제 길이(위 VM 시험은 1GB·4GB 가상 디스크), 실제 FIDO2/TPM 슬롯(토큰은 가짜 JSON 으로만 시험), 실제 USB 로 ISO 부팅(ISO 이미지를 QEMU/UEFI VM 에서 시리얼 콘솔로 부팅해 가상 디스크에 reseal 전체를 돌려 데이터 보존까지 확인했다 — 2026-11-19, 그 ISO 는 마지막 문구 수정 전 빌드).

## 3. dbx 갱신 (fwupd)
- 설정: `mods/sys/services/fwupd.nix`(매시간 타이머는 끔, **시간 기반 타이머 없음**). NetworkManager 가 연결(`up`)되거나 인터넷이 확인(`connectivity-change`=FULL)되면 훅이 `fwupd-stale-refresh` 를 시작하고, 이번 부팅에서 확인을 마쳤다는 표시(`/run/fwupd-check-done`)가 있으면 바로 끝난다(`refresh` 가 필요했는데 못 받았으면 표시를 남기지 않아 다음 연결 때 다시 시도). **마지막 새로 받기가 14일보다 오래됐을 때만** `fwupdmgr refresh`(네트워크 필요)를 하고, 갱신 유무(`get-updates`)는 매번 확인해 `/var/lib/fwupd-check/last-result` 에 남긴다. 갱신이 있으면 로그인 때와 결과가 바뀔 때 알림(`sb-notify`, 알림 센터에서 명령 복사)이 뜬다. **설치는 자동으로 하지 않는다.**
- 수동: `sudo nixseal sb dbx-update`(갱신 확인 → 「집이고 바로 재부팅」 확인 → `fwupdmgr update`; 끝나면 **자리를 비우지 말고 바로 재부팅**). 직접 하려면 `fwupdmgr refresh && fwupdmgr get-updates && sudo fwupdmgr update`. 적용 뒤 정상 부팅을 확인한다. fwupd 가 ESP 에 새 목록이 막을 부트로더가 있으면 거부한다.
- 주의: dbx 갱신은 되돌리기 어렵다(되돌리려면 Setup Mode). 적용 전에 `nixseal sb backup-esp`.

## 4. 알아 둘 사실 (2026-11-18 실기·소스)
- 이 기종 BIOS(AMI UEFI 2.80) Secure Boot 메뉴: `Secure Boot Support`, `Install All Factory Default Keys`, `Reset To Setup Mode`, `Key Management → Factory Default Key Provisioning`. `Secure Boot Mode: Custom`.
- lanzaboote 는 `EFI/nixos` 를 통째로 정리한다(`lzbt` 설치 뒤 옛 방식 항목은 복구 불가) — 그래서 설치 전에 ESP 백업.
- rEFInd 의 수동 `menuentry` 는 `vol_efi` 뱃지를 붙인다. 테마에 그 아이콘이 없으면 검정-노랑 줄무늬 대체 이미지가 나온다(`mods/sys/services/refind.nix` 가 아이콘을 복사).
- 펌웨어는 인증서 만료일을 확인하지 않는다(Microsoft KEK CA 2011 은 2026-06 만료 표시지만 계속 신뢰됨 — 추정, 소스 미확인). 2023 인증서(KEK 2K CA 2023 등)도 db/KEK 에 함께 등록돼 있다.
