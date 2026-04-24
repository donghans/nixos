# 첫 번째 NixOS 호스트 설정해보기

이 튜토리얼에서는 새 노트북에 이 프레임워크를 처음 설치하고, 설치 후 간단한 변경을 가해 빌드하는 경험을 합니다.

**마치면 알게 되는 것**: 호스트, 프리셋, Mod가 어떤 관계인지, 그리고 `nixup`이 왜 필요한지.

**준비물**: NixOS 공식 Live USB, 인터넷 연결, GitHub 계정

**소요 시간**: 약 45분~1시간 30분

---

## 이 프레임워크의 핵심 아이디어

설치를 시작하기 전에, 이 시스템이 왜 평범한 NixOS 설정과 다른지 잠깐 살펴봅니다.

일반적인 NixOS 설정은 Nix 언어로 직접 모든 것을 기술합니다. 이 프레임워크는 세 가지를 분리합니다:

- **TOML 메타데이터**: "이 기기에 docker와 bluetooth를 켜줘" — Nix를 몰라도 작성 가능
- **Mods**: docker, bluetooth 같은 기능 단위. 각각 독립적으로 켜고 끌 수 있음
- **nixup**: Nix를 직접 부르는 대신 항상 거치는 빌드 도구. TOML을 읽어 Nix에 전달함

이 관계가 설치 과정에서 자연스럽게 와닿게 됩니다.

---

## 1단계: 저장소 Fork하기

GitHub에서 이 저장소를 본인 계정으로 Fork합니다.

Fork를 쓰는 이유: 이 프레임워크의 코드와 여러분의 기기 설정이 같은 저장소에 공존합니다. 직접 clone하면 나중에 프레임워크 업데이트를 받을 때 충돌이 납니다. Fork하면 upstream 변경과 내 설정을 분리해서 관리할 수 있습니다.

Fork가 완료되면 주소를 메모해 둡니다 (`https://github.com/<your-username>/nixos`).

---

## 2단계: Live USB로 부팅하고 저장소 받기

NixOS 공식 ISO로 부팅합니다. 인터넷이 연결됐는지 먼저 확인합니다 (`ping 8.8.8.8`).

저장소를 받습니다:

```bash
nix-shell -p git --run "git clone https://github.com/<your-username>/nixos"
cd nixos
```

`nix-shell -p git`은 git이 없는 Live 환경에서 임시로 git만 빌려오는 명령입니다. 설치 후엔 이럴 필요가 없습니다.

:::note
`hosts/_base.toml`의 `username`, `git.name`, `git.email`, `git.nixosRepo` 항목은 `nixstrap.sh`가 자동으로 채웁니다. GitHub API를 통해 자동 감지하고, 필요한 경우 대화형으로 입력을 요청합니다. 미리 편집할 필요 없습니다.
:::

---

## 3단계: 설치 시작

```bash
./nixstrap.sh
```

터미널에 대화형 질문이 표시됩니다. 각각 무엇을 묻는지 살펴봅니다.

### 호스트 이름

프레임워크는 기기를 **호스트**라는 단위로 관리합니다. 호스트 이름을 입력하면 `hosts/<이름>.toml`과 `hosts/<이름>.nix` 파일이 생성됩니다.

예시: `my-laptop`

### 프리셋

프리셋은 "이 기기 용도에 맞는 기본 Mod 조합"입니다.

| 프리셋 | 설명 | GUI | 개발 환경 | 서버 서비스 |
|--------|------|-----|-----------|------------|
| `workstation` | 데스크탑/랩탑 기본 (Hyprland + 개발 도구) | ✅ | ✅ | ❌ |
| `server` | 헤드리스 서버 (GUI 없음, 서버 서비스 중심) | ❌ | ❌ | ✅ |

노트북이니까 `workstation`을 선택합니다.

프리셋이 "기본 조합"이라면, 나중에 `hosts/<이름>.toml`에서 특정 Mod만 끄거나 켤 수 있습니다. 예: docker가 필요 없으면 `[mods.sys.services] docker = false`.

### 파티션 설정

`nixstrap`이 디스크를 어떻게 포맷할지 묻습니다:

- **mode 1** — 기존 파티션을 직접 지정합니다. 이미 파티션이 나눠진 경우에 사용합니다.
- **mode 2** — 전체 디스크 또는 빈 공간 범위를 지정하면 자동으로 새 파티션을 만듭니다.

새 노트북이라면 mode 2를 선택하고 디스크(`/dev/nvme0n1` 등)를 지정합니다.

:::caution
이 과정에서 지정한 디스크가 완전히 지워집니다. 기존 데이터를 백업했는지 확인하세요.
:::

설정 요약을 검토하고 확인하면 설치가 진행됩니다. 10~20분 소요됩니다.

:::note
설치 파라미터는 확인 후 `/root/nixstrap-params.env`에 저장됩니다. 네트워크 오류 등으로 설치가 중단된 경우, `nixstrap.sh`를 다시 실행하면 저장된 파라미터를 불러와 이어서 진행할 수 있습니다.
:::

---

## 4단계: 재부팅 후 Home Manager 적용

설치가 끝나면 재부팅합니다. 로그인 화면이 뜨기 전 TTY(Ctrl+Alt+F2)에서 로그인한 뒤:

```bash
nixup home
```

이 명령이 왜 필요한지: `nixup os`는 시스템 레벨 설정(패키지, 서비스)을, `nixup home`은 사용자 레벨 설정(쉘 설정, dotfiles, 사용자 앱)을 적용합니다. 둘은 독립적입니다. 설치 과정은 `os`만 완료된 상태입니다.

`nixup home`이 완료되면 재로그인합니다. Hyprland가 뜨고 전체 환경이 활성화됩니다.

---

## 5단계: 첫 번째 변경 적용해보기

시스템이 올라온 상태에서 직접 변경을 가해봅니다.

`hosts/<이름>.toml`을 열고 docker를 끕니다:

```toml
[mods.sys.services]
docker = false
```

저장 후:

```bash
nixup os
```

`nixup`이 무엇을 하는지: TOML을 읽어 JSON으로 변환하고, 소스를 `.build/` 디렉터리에 복사한 뒤 `nix build`를 실행합니다. 진행 과정이 터미널에 실시간으로 표시됩니다. 완료되면 변경된 패키지 목록(NVD diff)을 보여줍니다.

빌드가 성공하면 변경이 즉시 적용됩니다.

---

## 이 튜토리얼에서 배운 것

- **호스트**: 기기 단위. TOML + Nix 파일 한 쌍으로 구성
- **프리셋**: 용도별 Mod 기본 조합. 개별 호스트에서 덮어쓸 수 있음
- **Mod**: 독립적으로 켜고 끌 수 있는 기능 단위
- **nixup**: 직접 nix를 부르지 않고 항상 이것을 통함. TOML → JSON → nix build 파이프라인

---

## 다음으로

- 개발 도구 추가: `<hostname>.toml`의 `[mods.devel]`에서 필요한 것을 `true`로 — 그리고 `nixup os` + `nixup home`
- 나만의 기능 추가: [Mod 만들기](../how-to/create-mod.md)
- 시스템 관리 실전 (원격 서버 설치 포함): [nixup 활용 가이드](../how-to/manage-system.md)
- 이 구조가 왜 이렇게 설계됐는지: [아키텍처와 설계 결정](../explanation/architecture.md)
