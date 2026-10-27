
# 화면 확인용 QA 데스크톱 (incus VM `qa-desktop`)
- 사용자와 같이 화면을 보는 headed 브라우저 확인이나 접근성 트리가 필요한 확인은 `donghans-qa-desktop` 스킬(접속·실행·창 배치·도구·공유 규칙·복구)을 먼저 읽고 따르세요. 위 playwright 「Docker 에서만」 규칙은 headless 자동 E2E 에 그대로 적용됩니다.
- 사용자 승인 없이 하지 마세요: VM 생성·재프로비저닝(`qa-desktop-ctl ensure`·`provision`)·삭제, VM 설정·gsettings·확장 변경, apt 설치·업그레이드, 재로그인·재부팅, 스냅샷 복원. 화면 잠금은 **꺼진 상태**(`lock-enabled false`, `idle-delay 0`)를 항상 유지하세요. 계정에 비밀번호가 없어 GUI 로는 풀 수 없습니다(잠겼다면 스킬의 `loginctl` 복구 절차).
- QA 세션 역할(코드를 고치지 않고 측정·보고)이면 먼저 `donghans-qa` 스킬(범용 원칙 + 프로젝트별 추가 지침 읽는 법)을 읽으세요.
- 다른 프로젝트 QA 세션의 파일(`~/qa-playwright` 의 다른 디렉터리·package.json)은 건드리지 말고, 쓰기 전에 상대 QA 세션에 시작과 예상 시간을 알리세요.
- 사용자에게 현재 가상 데스크톱 번호를 묻지 마세요(화면에 안 보입니다). 스킬의 도구로 직접 확인합니다.
