# `nixseal recover` ISO 부팅 시험 (수동, 2026-11-20 통과)
`sb-recover.nix` 는 ISO 와 같은 `nixseal` 래퍼를 일반 NixOS VM 에서 돌린다. 이 절차는 **실제 ISO 를 부팅**해서 돌린다(ISO 의 `/` 판별·실제 PATH·실제 암호 프롬프트).
1. 대상 디스크(LUKS2+btrfs `@`+vfat ESP+lanzaboote, 변조된 ESP)와 USB 이미지: `nix-build default.nix -A recoverprep.driver -o drv` →
   `PREP_TAKE=/tmp/take TMPDIR=<빈 디렉터리> drv/bin/nixos-test-driver`. 시험이 `SHARED_DIR=<경로>` 를 출력하고 `/tmp/take` 가 생길 때까지 기다린다(driver 는 끝나면 VM 상태를 지워서 이렇게 꺼낸다).
   그 사이 `<경로>/target.img.gz`·`usb.img.gz` 를 복사해 gunzip, 그리고 `touch /tmp/take`.
2. ISO: `nixup iso` → `/tmp/nixup-iso/result/iso/*.iso`.
3. `QEMU_DIR=$(nix build nixpkgs#qemu_kvm --print-out-paths --no-link) OVMF_DIR=$(nix build nixpkgs#OVMF.fd --print-out-paths --no-link) python3 -I isorec.py <ISO> target.img usb.img` (KVM 필요, 약 2분). 디스크는 snapshot 모드라 이미지는 바뀌지 않는다.
한계: BIOS(Secure Boot) 설정·실제 USB·실기 NVMe 는 아니다. OVMF NVRAM 에는 설치된 시스템의 부팅 항목이 없어 `efibootmgr` 단계는 목록 출력만 확인된다.
