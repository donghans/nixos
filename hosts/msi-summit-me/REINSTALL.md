# msi-summit-me 재설치 절차 (LUKS2 + btrfs) — 2026-11-17 작성

이 노트북의 내장 NVMe(약 1TB)를 **통째로 지우고** NixOS 를 LUKS2 암호화로 다시 설치하는 순서입니다.
근거·시험 기록: ctx `plan/nixstrap-luks`(§4-2, §9-3), `plan/boot-security`(S4). 이 문서 정본은 저장소의 `hosts/msi-summit-me/REINSTALL.md`, USB 루트의 `NIXOS-REINSTALL.md` 는 복사본입니다.

> **복구 암호(영어 8단어)는 종이에만 적습니다.** 터미널 밖으로 옮기지 말고, Claude 대화·메모·메신저에 붙여 넣지 마세요(대화는 공유 DB 에 저장됩니다).
> 설치 화면은 사람만 보세요. Claude 는 이 단계의 화면을 보거나 자동화하지 않습니다.

---

## 0. 설치 전 (이 노트북이 지금 켜져 있을 때)

- [ ] 전원 어댑터를 계속 연결해 둡니다(설치가 길 수 있습니다 — unstable 커널을 빌드하면 오래 걸립니다).
- [ ] 종이와 펜을 준비합니다(복구 암호 8단어 + 생성 시각).
- [ ] **headscale 에서 옛 `msi-summit-me` 노드를 삭제하거나 만료**시킵니다(headscale-vps 에서). 그대로 두면 새 노드 이름이 `msi-summit-me-1` 처럼 바뀔 수 있습니다(추정, 미확인).
- [ ] 외장 SSD(Blueendless 등)와 쓰지 않는 USB 는 뽑습니다. 디스크 선택 실수를 막기 위해서입니다(Ventoy USB 만 남깁니다).
- [ ] beelink 의 백업 번들이 있는지 확인합니다: `ssh beelink-ser7-co 'ls -la ~/backup-msi-summit-me-20261110'` (6개 파일, 2026-11-17 해시 일치 확인됨).
- [ ] 저장소가 push 돼 있고 `hosts/msi-summit-me.toml` 에 **`luks` 줄이 없어야** 합니다: `cd ~/nixos && git status -sb && grep -n luks hosts/msi-summit-me.toml` (출력 없음이 정상). `luks = true` 는 설치 사본에만 들어가고, 새 시스템에서 커밋합니다. **지금 이 노트북에 커밋하면 부팅이 깨집니다.**
- [ ] 이 노트북에서만 있는 데이터가 없는지 마지막으로 생각합니다(Windows·기존 NixOS 는 전부 사라집니다. 번들 이후 중요한 데이터는 없다고 판단함).

## 1. ISO 부팅

1. Ventoy USB 를 꽂고 재부팅 → 부팅 메뉴(MSI 는 보통 `F11`, BIOS 는 `Del`) → USB 선택.
2. Ventoy 메뉴에서 `ventoy-iso/nixos/nixos-26.05.20260611.a037402-x86_64-linux.iso`(2026-11-17 재빌드본) 선택.
3. Secure Boot 가 켜져 Ventoy 가 안 뜨면 BIOS 에서 끕니다(`plan/boot-security` 도 서명 없는 상태로 설치합니다).

## 2. ISO 안에서

**네트워크**: 유선을 권장합니다. `ping -c1 github.com` 으로 확인. 무선이 필요하면 ISO 의 도구(`nmtui` 가 있으면 그것)로 연결합니다 — ISO 의 무선 도구는 확인하지 못했습니다.

**이 문서 보기**: 다른 터미널(`Alt+F2`)에서 `sudo mount /dev/disk/by-label/Ventoy /mnt && less /mnt/NIXOS-REINSTALL.md` (설치 전에 `sudo umount /mnt`).

**디스크 확인**: `lsblk` — 내장 NVMe 는 `nvme0n1`(약 954G), USB 는 약 57G `sdX`. 
`fdisk` 로 먼저 비울 필요는 없습니다(nixstrap 이 `mklabel gpt` 와 전체 TRIM 을 합니다). 해도 상관없습니다(리허설에서 `fdisk` 의 `g`→`w` 로 비운 디스크에서 성공).

**nixstrap 실행**: `nixstrap` (ISO 에 들어 있는 최신 빌드). 질문 순서와 답:

| 질문 | 답 |
|---|---|
| 레포지터리 | `donghans/nixos` |
| 호스트 선택 | `msi-summit-me` (기존 호스트 — 프리셋·노트북 질문은 나오지 않음) |
| 파티션 모드 | `2` (신규 생성) |
| 대상 디스크 | **`nvme0n1` (954G)**. 첫 항목이 USB 일 수 있으니 Enter 만 치지 마세요 |
| 전체 디스크 사용 | `Y` → 경고에 `yes` |
| 부트 파티션 크기 | Enter (1GiB) |
| LUKS2 로 암호화 | `y` |
| 요약(1~4) | 확인 후 Enter |
| 로그인 비밀번호 | 새로 정합니다(복구 암호와 다른 것) |

**복구 암호 단계** (가장 중요):
1. 8단어와 QR 이 표시됩니다. **종이에 적고**, 표시된 생성 시각도 적습니다. 대문자·철자를 그대로 적습니다.
2. Enter → 화면이 지워집니다. 터미널 스크롤을 올려 **암호가 남아 있지 않은지** 확인합니다(남아 있으면 알려 주세요).
3. 종이를 보고 **다시 입력**합니다(공백으로 구분, 소문자). 틀리면 다시 표시되고 3회까지 시도합니다.
4. 「지울 디스크 경로를 그대로 입력」에 `/dev/nvme0n1` 을 입력하면 **되돌릴 수 없습니다.**
5. LUKS 포맷 직후 종이를 보고 한 번 더 입력합니다(열림 검증).

**설치 대기**: `nixos-install`. 리허설(VM)은 9분, 실기는 커널 빌드 여부에 따라 훨씬 길 수 있습니다. 중간에 Ctrl+C 를 3~5초 안에 두 번 누르면 중단됩니다 — 하지 마세요.

**헤더 백업 질문** (설치 직후, 기본 예): LUKS 헤더가 손상되면 복구 암호가 있어도 못 엽니다. 디스크 밖에 저장합니다.
- 목록에 `Ventoy`(exfat) 파티션이 나오면 선택합니다. 설치 USB 와 같은 USB 인데 부팅 중에도 마운트되는지는 **실기에서 확인하지 못했습니다.** 실패하면 `+ 다른 컴퓨터로 scp` 를 쓰거나 건너뛰고, 새 시스템에서 §4-4 로 합니다.
- 슬롯(TPM2/FIDO2 등)을 바꾸면 이 백업은 옛 암호로만 열립니다. 바꾼 뒤 다시 백업합니다.

**설치 완료 화면**을 읽습니다: 「설치 사본의 hosts/msi-summit-me.toml 에만 luks = true 가 있고 원격 저장소에는 없습니다」. → 재부팅합니다(재부팅은 직접).

## 3. 첫 부팅

1. rEFInd 메뉴(20초 뒤 자동으로 systemd-boot) → NixOS 항목.
2. 암호 입력 화면(`Please enter passphrase for disk cryptroot`)에 **복구 암호 8단어**를 입력합니다. 화면이 안 나오거나 키보드 입력이 안 되면 §5.
3. TTY(`Ctrl+Alt+F2`)에서 로그인 → `cd ~/nixos && nixup home` → 재로그인(README 와 같음).

## 4. 설치 후 해야 할 것 (순서대로)

1. **`luks = true` 커밋·push** (설치 사본에만 있음)
   ```
   cd ~/nixos && git status -sb && git diff
   ```
   `luks = true` 한 줄 말고 다른 변경(예: hardware 파일)이 있으면 내용을 보고 정합니다. GitHub 인증이 필요하면 `gh auth login` 후:
   ```
   git add hosts/msi-summit-me.toml && git commit -m "feat(msi-summit-me): luks = true (S4 재설치)" && git push
   ```
2. **tailscale 로그인**(headscale, 평소 방식) → **claude 로그인**(`claude`). 로그인을 마치면 Claude 에게 이 문서를 보여 주고 이어서 해달라고 하면 됩니다.
3. **ssh 키를 beelink 에 등록** (별도 터미널, beelink 비밀번호는 직접 입력 — 대화에 쓰지 않음):
   ```
   cd ~/nixos && bash core/scripts/restorectl.sh key
   ```
   beelink 는 키 인증이 기본이지만 키보드-인터랙티브(비밀번호)도 받습니다(`ssh -v` 로 확인, 실제 로그인은 미시험).
4. **LUKS 헤더 백업 확인** (설치 중 백업을 건너뛰었거나 실패했으면 지금 합니다):
   ```
   sudo python3 ~/nixos/core/scripts/luksctl.py slots /dev/disk/by-partlabel/cryptroot
   sudo python3 ~/nixos/core/scripts/luksctl.py backup-header /dev/disk/by-partlabel/cryptroot <USB 마운트 경로>
   ```
   `cryptsetup 없음` 오류가 나면 앞에 `nix shell nixpkgs#cryptsetup -c` 를 붙입니다.
5. **데이터 복원** (beelink `~/backup-msi-summit-me-20261110`, Claude 가 도와줄 수 있음 — 파일 내용·목록은 대화에 출력하지 않음):
   ```
   bash core/scripts/restorectl.sh fetch      # 가져오기 + 무결성 확인
   nix shell nixpkgs#zstd -c bash core/scripts/restorectl.sh extract   # 임시 폴더에만 풂, 홈 불변
   bash core/scripts/restorectl.sh pick       # 기본: .ssh .gnupg nix-secrets keyrings Bitwarden .claude/settings.json (기존 파일은 덮어쓰지 않음)
   ```
   - 더 복원할 것은 `pick 경로…`(예: `.zsh_history`, `.local/share/atuin`, Windows 번들의 `Documents/…`). `~/.claude` 기록과 `~/ctx` 는 beelink 가 정본이라 복원하지 않습니다.
   - `donghans secret list` 로 등록된 비밀 7건이 살아 있는지 확인합니다(저장 위치는 계획에서 미확인).
6. **마무리**: `restorectl.sh clean`(평문 임시 폴더 삭제) → 복원이 충분하면 beelink 의 번들 삭제 → Claude 에게 결과 기록을 부탁합니다(`plan/nixstrap-luks` §9, `plan/boot-security` S4 완료).

이후: S5(Secure Boot)·S6(FIDO2/TPM, **슬롯을 바꾼 뒤 헤더 백업을 다시**) — `plan/boot-security`.

## 5. 문제가 생기면

- **암호 입력 화면이 안 나오거나 키보드가 안 먹음**(LUKS·lockdown·i915 initrd 조합은 실기에서 처음 봅니다): 데이터는 beelink 번들이 있으니 ISO 로 다시 부팅해 같은 절차로 재설치할 수 있습니다. 먼저 `Ctrl+Alt+Del` 후 외장 USB 키보드를 시도해 보세요.
- **복구 암호가 안 열림**: 대소문자·공백, 철자, 종이의 8단어 순서를 확인합니다(부팅 때는 정규화하지 않습니다). 설치 때 정규화되어 열린 경우라도 부팅 프롬프트는 그대로 비교합니다.
- **헤더가 의심스러움**: ISO 에서 `python3 luksctl.py verify /dev/nvme0n1p2` → 백업이 있으면 `restore-header`(장치 경로를 직접 입력해야 진행, 열린 매퍼가 있으면 거부).
- **설치가 중간에 멈춤/실패**: 같은 디스크로 `nixstrap` 을 다시 실행해도 됩니다(열린 매퍼를 정리합니다). 암호는 **새로 생성**되므로 옛 종이는 버리고 새로 적습니다.
- **rEFInd 가 안 보임**: BIOS 부팅 메뉴에서 `rEFInd` 또는 `Linux Boot Manager` 를 고릅니다(NVRAM 이 비면 `EFI/BOOT/BOOTX64.EFI` 로 폴백해 NixOS 는 부팅됩니다).
- 이 문서·도구에 오류를 발견하면 알려 주세요(리허설은 VM 에서만 했습니다: 실제 NVMe TRIM·MSI 펌웨어·실제 USB 의 `lsblk` 값·스크롤백 삭제·LUKS 암호 화면+키보드는 실기에서 처음입니다).
