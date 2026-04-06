# 📦 Devbox 통합 관리 도구

프로젝트별로 격리된 개발 환경을 구축하기 위한 Devbox 템플릿과 통합 명령어를 제공합니다.

## 🚀 빠른 시작 (3초 세팅)

원하는 프로젝트 폴더에서 다음 명령어 한 줄만 입력하세요.

### Node.js / Prisma 프로젝트
```bash
devbox-setup node
```

### Flutter / FVM 프로젝트
```bash
devbox-setup flutter
```

## ✨ 수행되는 작업 (Automation)
`devbox-setup`을 실행하면 내부적으로 다음 과정이 자동으로 진행됩니다:
1.  **템플릿 복사**: 프로젝트 성격에 맞는 `devbox.json`을 현재 폴더로 가져옵니다.
2.  **direnv 연동**: `.envrc`를 생성하여 쉘 진입 시 환경이 자동 활성화되도록 합니다.
3.  **Stealth 모드**: `.git/info/exclude`에 모든 Devbox 및 direnv 관련 설정(.devbox, .direnv, devbox.json 등)을 등록하여 팀원들과의 마찰을 방지합니다.
4.  **환경 승인**: `direnv allow`를 실행하여 즉시 사용 가능한 상태로 만듭니다.

## 💡 JetBrains IDE 연동
1.  IDE에서 **`direnv`** 플러그인을 설치합니다.
2.  프로젝트를 열면 플러그인이 자동으로 환경을 감지하여 Prisma 경로, SDK 경로 등을 주입합니다.
