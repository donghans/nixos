# 🚀 처음 사용자용 부트스트랩 (ISO 기반)

이 프로젝트는 **Btrfs 서브볼륨 구조(`@`, `@home`, `@nix`, `@log`)**에 최적화되어 설계되었습니다. 따라서 기존 시스템에서 단순히 설정을 전환하는 것보다, **전용 설치 ISO**를 통해 정해진 구조대로 시스템을 구축하는 것이 가장 안전하고 권장되는 방법입니다.

## 1. 저장소 준비 (Fork & Clone)

이 프로젝트는 본인의 GitHub 계정으로 **Fork**하여 관리하는 것을 전제로 합니다.

```bash
# 본인의 저장소로 클론 (유저명을 본인 것으로 수정하세요)
git clone https://github.com/<your-username>/nixos.git
cd nixos
```

## 2. 초기 설정 수정 (`dev/_info.json`)

설치 스크립트는 이 파일의 정보를 읽어 GitHub에서 소스 코드를 가져오고 유저를 생성합니다.

```json
{
  "username": "linux_user", // 생성할 유저명
  "git": {
    "name": "Your Name",
    "email": "your@email.com",
    "nixosRepo": "<your-username>/nixos" // 설치 시 클론할 저장소 경로
  },
  "hosts": [
    { 
      "hostname": "my-machine", // 기기 이름
      "system": "x86_64-linux", // 현재 x86_64 시스템만 테스트해봤습니다. 다른게 되는진 잘 모르겠네요.
      "isLaptop": false, // 랩탑의 경우 배터리 표시 등이 필요하므로 랩탑에선 true를 권장합니다.
      "isRolling": true, // 데일리 머신으로써 사용할 경우 unstable 패키지의 최신 버전 사용을 위해 true로 할 수 있습니다.
      "ramGb": 16 // 물리 스왑으로 tmpfs의 크기를 늘리고싶을 경우, 해당 기기의 실제 메모리 크기를 GB로 넣어두면 정상동작을 보장합니다. 필요없다면 빼주세요.
    }
  ]
}
```

## 3. 새로운 호스트 정의 (템플릿 활용)

설치할 기기에 맞는 설정을 미리 준비해야 합니다.

1.  **설정 파일 복사**:
    ```bash
    cp dev/.template.nix dev/<hostname>.nix
    cp dev/.template.home.nix dev/<hostname>.home.nix
    ```
2.  **내용 수정**: `dev/<hostname>.nix` 파일을 열어 필요한 서비스나 패키지를 수정하세요.

## 4. 나만의 설치 ISO 빌드 및 설치

프로젝트 루트의 스크립트를 사용하여 커스텀 ISO를 만듭니다.

```bash
./from-nixos-mk-iso.sh
```

- 빌드가 완료되면 `.build/` 폴더에 ISO 파일이 생성됩니다.
- 이 ISO로 부팅하면 터미널에 **한글 안내 메시지**가 나타납니다.
- 안내에 따라 `nixos-setup` 명령어를 실행하면 다음과 같은 작업이 자동으로 진행됩니다:
  1. **Btrfs 파티셔닝**: `@`, `@home`, `@nix`, `@log` 서브볼륨 자동 생성 및 최적 옵션 마운트.
  2. **하드웨어 감지**: `nixos-generate-config`를 실행하여 해당 기기의 하드웨어 설정을 `dev/hardware/<hostname>.nix` 경로에 자동으로 저장합니다.
  3. **자동 설치**: `dev/_info.json`에 정의된 저장소를 다시 클론하고 시스템을 빌드합니다.

설치가 완료되고 재부팅하면, 전역 명령어 `nhw`를 통해 시스템을 관리할 수 있습니다.
