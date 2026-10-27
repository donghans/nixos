# uikit 화면 검증 도구 (2026-10-26)

TUI 를 **실제 터미널(헤드리스 cage + kitty + grim)** 로 띄워 촬영하고, 키 입력으로 동작을 확인하는 도구. Textual 의 SVG 내보내기는 한글 칸 폭을 실제와 다르게 그려 정렬 문제를 놓치므로 이 방식을 쓴다.
`/tmp` 는 재부팅하면 지워지므로 여기에 보존했다(스크래치패드에서 복사 — 경로가 맞는지 먼저 확인).

- `shoot.sh <스크래치 디렉터리> '<앱 명령>' <이름> <키|-> …` — 각 키를 `kitten @ send-text` 로 보내고 `$S/shots/<이름>-N.png` 로 촬영. `-` 는 4초 대기만. 사용: `nix shell nixpkgs#cage nixpkgs#grim -c bash -c "shoot.sh …"`.
  앱 명령에 공백이 든 환경 변수(DSN 등)를 넣을 땐 래퍼 스크립트로 감싼다. cage 를 연달아 띄울 땐 사이에 `sleep 3`. `pkill -f` 로 cage 를 죽이지 말 것(자기 셸이 죽음) — `pkill -x cage`.
  키 예: Esc=`$'\x1b'` Shift+Tab=`$'\x1b[Z'` F2=`$'\x1bOQ'` F8=`$'\x1b[19~'` F9=`$'\x1b[20~'` F10=`$'\x1b[21~'` Enter=`$'\r'`(줄바꿈 `\n` 은 Enter 가 아님).
- `gallery_ctx_pg.py <env 파일>` — 임시 Postgres 에 **합성** ctx 데이터(긴 한글 세션 160개 메시지·미등록 키·비밀·통계·지침)를 올리고 접속 환경을 env 파일에 쓴 뒤 15분 유지. ctxui 화면 촬영에 쓴다(실제 대화·비밀을 화면에 올리지 않으려고). `CTX_PG_BIN=/nix/store/*-postgresql-and-plugins-17*/bin`, psycopg 있는 파이썬 필요.
- `keyprobe.py <앱>` — q·Esc·Ctrl+C·Ctrl+Q 와 도움말 닫기 키를 눌러 종료·닫힘을 표로 낸다(usageui·procui·sessions·notif·clip·display; clip·notif·display 는 합성 환경 변수 필요).
- `lint_width.py <파일…>` — f-string 의 문자열 폭 서식(`{x:<n}`)을 AST 로 찾는다(한글이 들어갈 수 있는 변수에 쓰면 열이 어긋남).
