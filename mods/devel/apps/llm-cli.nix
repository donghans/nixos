{
  mkModOf,
  unstable,
  ...
}:
mkModOf "mods.devel" __curPos "LLM CLI tools" ({
  pkgs,
  unstable,
  config,
  lib,
  ...
}: let
  # 노트북에서는 Claude Code TUI 의 애니메이션(스피너 등)을 줄여서 켠다(`--settings` 로 한 키만 덧씌움; 사용자 settings.json 은 Claude 가 직접 쓰는 가변 파일이라 건드리지 않음).
  # 목적: (1) **측정 위생** — 이 저장소의 목적은 Wayland 세션 사용 시 배터리 최적화이고 Claude 를 VT2(kmscon)에 두는 것도 그 측정에 변수를 섞지 않으려는 것인데,
  # VT2 가 활성일 때 TUI 가 화면을 갱신하면 약 +1.3 W 가 섞인다(2026-10-20 측정, power-evidence.md #34). (2) 화면 갱신이 줄면 PSR 등 모니터 출력 최적화가 더 잘 걸리므로
  # 모션 감소는 효과 측정 결과와 무관하게 유지한다(사용자 결정). `CLAUDE_MOTION=normal claude` 로 끌 수 있다.
  reduceMotion = config.workspace.type == "laptop";

  # observectl(관측 시스템)이 설치된 호스트에서만 지침에 넣는다(호스트 toml 의 observe = true; workstation 프리셋은 기본 켬).
  # 호스트 종류별 목표가 다르다: 노트북 = 배터리 사용량 관리·개선, 데스크톱 = 비효율 프로세스 관리·집중할 곳에 자원 쓰기.
  observeInstructions = lib.optionalString config.mods.sys.services.observe.enable ''

    # 관측(observectl) — 성능·자원·전력 문제는 추측하지 말고 기록으로 확인
    - 「느리다」「CPU/메모리를 많이 쓴다」「누가 깨우나」「어느 앱에 시간을 썼나」「배터리가 빨리 닳는다」 같은 질문은 추측하기 전에 먼저 `observectl status` 로 수집이 켜져 있는지 보고 조회하세요.
      수집 기본값: **노트북은 꺼짐**(전력 측정에 변수를 섞지 않으려고; 켜기 `observectl on`, 끄기 `observectl off`), 그 밖(데스크톱·서버)은 켜짐. 노트북에서 켜거나 수준(L1)·eBPF 를 올릴 때는 측정에 영향을 주니 먼저 사용자에게 말하세요.
    - 이 호스트의 방향: 노트북은 **전력→배터리 사용량 관리·개선**, 데스크톱은 **비효율 프로세스 관리와 집중할 곳에 자원 쓰기**(배터리·psys·Intel C-state 지표는 없거나 비어 있을 수 있음 — 값이 `None`/없음이면 없는 것이지 0 이 아님).
    - 자주 쓰는 조회(sudo 불필요, 개별 조건은 `observectl <명령> --help`):
      - 상위 프로세스: `observectl top --by cpu|ctxsw|app --since 1h -n 15`(cpu 는 코어 1개=100%, ctxsw 는 자발적 문맥 전환/s)
      - 시간대별·그룹별 집계: `observectl query app:<앱>.cpu proc:<comm>.cpu --since 6h --step 10m --agg mean`(신호 별칭은 `observectl query --help`)
      - 누가 CPU 를 깨우나: `observectl wakers 10`  · 그 순간 무슨 일이: `observectl timeline --at 12:09:37 --span 60`
      - 한 구간을 포커스·프로세스·스팬으로 묶어 기준 구간과 비교: `observectl explain …`  · 구간(스팬) 폭포: `observectl trace --since 1h`(nixup·덮개 정책 등)
      - 브라우저 탭·확장별 CPU: `observectl browser top` / 폭주 기록 `observectl browser bursts`(Vivaldi 디버깅 포트 127.0.0.1:9222 필요)
      - 실험 전후 비교는 `observectl mark` 로 조건 표지를 붙이고 `observectl window --by mark`.
    - 정밀 도구(`observectl bpf <프리셋>`, `observectl ebpf on …`)는 요청할 때만 N초 실행되고 시간이 제한됩니다. 오래 켜 두지 마세요. `observectl display` 는 읽는 것이 디스플레이를 깨울 수 있어 노트북 전력 측정 중에는 쓰지 마세요.
    - 개인정보: 프로세스는 comm·exe 이름만, 창 제목·URL·명령 인자·입력 내용은 기록하지 않습니다. 조회 결과를 외부로 보낼 때도 이 원칙을 지키세요.
    - 앱별 전력량 추정(Wh)은 psys 센서가 있는 호스트에서만 의미가 있습니다. 자세한 설명·한계는 `~/nixos/_docs/content/explanation/observe.md`.
  '';
  # 훅(claude-ctx)은 항상 --settings 로 주입한다 — ~/.claude/settings.json 은 Claude 가 직접 쓰는 가변 파일이라 nix 로 소유하지 않는다.
  # --settings 를 두 번 주면 어떻게 합쳐지는지 확인하지 않아서(미확인) 모션 감소 키는 같은 파일에 넣어 한 번만 준다.
  settingsSnippet =
    if reduceMotion
    then ''
      if [ "''${CLAUDE_MOTION:-reduced}" != normal ]; then
        set -- --settings ${hooksReducedFile} "$@"
      else
        set -- --settings ${hooksFile} "$@"
      fi
    ''
    else ''
      set -- --settings ${hooksFile} "$@"
    '';
  # (목적: Wayland 터미널(kitty, alacritty 등)에서 LLM CLI의 Home/End 키 깨짐 현상 수정)
  #
  # (claude-code 쪽 패치는 제거함: 4월에 패키지가 네이티브 바이너리 배포로 바뀌면서 패치 대상 cli.js 가 사라져
  #  "pattern not found, skipping" 으로 아무 효과가 없었고, 현재 버전에서는 Home/End 문제도 재현되지 않음)
  # 원인: gemini-cli, claude-code 모두 시작 시 kitty keyboard protocol 쿼리(\x1b[?u)를 보내고,
  # kitty/alacritty 등 최신 Wayland 터미널이 이를 지원한다고 응답하면 프로토콜을 활성화(\x1b[>1u).
  # 이 모드에서 Home/End 키가 앱 자체의 키 파서가 처리하지 못하는 확장 시퀀스로 전송됨.
  # kmscon(TTY)은 해당 프로토콜을 지원하지 않아 정상 동작.
  # gemini-cli: enableKittyKeyboardProtocol() 함수 본문을 no-op으로 교체
  # chunk 파일명은 빌드마다 해시가 바뀌므로 grep으로 동적 탐색
  # gemini = unstable.gemini-cli.overrideAttrs (old: {
  #   postInstall =
  #     (old.postInstall or "")
  #     + ''
  #       target=$(grep -rl 'enableKittyKeyboardProtocol' $out/share/gemini-cli/ || true)
  #       if [ -n "$target" ]; then
  #         sed -i 's/writeToStdout("\\x1B\[>1u")//g' $target
  #         echo "patched: kitty keyboard protocol disabled in $target"
  #       else
  #         echo "WARNING: enableKittyKeyboardProtocol not found in gemini-cli bundle, skipping patch"
  #       fi
  #     '';
  # });
  #
  # (목적: claude 래퍼가 노출하는 LD_LIBRARY_PATH 의 alsa-lib 가 다른 프로그램을 깨뜨리는 문제 수정)
  # nixpkgs claude-code 는 /voice(음성 입력) 네이티브 모듈이 libasound 를 dlopen 하도록 래퍼에
  # `--prefix LD_LIBRARY_PATH : alsa-lib` 를 붙임(nixpkgs PR #518983). unstable 의 alsa-lib 는 더 새 glibc(2.44)로
  # 빌드돼 있어, 이 변수를 물려받는 glibc 2.42 프로그램(ONLYOFFICE 등)이 `GLIBC_2.43 not found` 로 죽음.
  # → alsa-lib 만 stable 것으로 교체. 새 glibc 는 옛 glibc 로 빌드된 라이브러리를 그대로 로드할 수 있어 양쪽 모두 안전함
  #   (claude 바이너리는 libc/libm/libpthread/librt 를 미리 로드하고 stable libasound 의 의존도 같은 목록).
  claudeBase = unstable.claude-code.override {inherit (pkgs) alsa-lib;};

  # (목적: /usage 와 같은 사용량(토큰·비용·하위 에이전트 구분)을 로컬 파일로 남겨 대조·분석)
  # claude 가 OTLP 로 보내는 메트릭·이벤트를 아래 user 서비스(로컬 수집기)가 받아 ~/.local/share/claude-otel/*.jsonl 에 저장한다.
  # 외부로 전송하지 않는다(127.0.0.1 만). 프롬프트 내용은 수집하지 않는다(OTEL_LOG_USER_PROMPTS 미설정).
  # 끄려면: 셸에서 CLAUDE_CODE_ENABLE_TELEMETRY=0 claude  (set-default 라서 덮어쓸 수 있다)
  # 주의: 메트릭 속성에 user.email·account id 가 포함된다 — 파일을 외부에 공유하지 말 것.
  claude = pkgs.symlinkJoin {
    name = "claude-code-otel";
    paths = [claudeBase];
    nativeBuildInputs = [pkgs.makeWrapper];
    postBuild = ''
      wrapProgram $out/bin/claude \
        --set-default CLAUDE_CODE_ENABLE_TELEMETRY 1 \
        --set-default OTEL_METRICS_EXPORTER otlp \
        --set-default OTEL_LOGS_EXPORTER otlp \
        --set-default OTEL_EXPORTER_OTLP_PROTOCOL grpc \
        --set-default OTEL_EXPORTER_OTLP_ENDPOINT http://127.0.0.1:4317
    '';
    inherit (claudeBase) meta;
  };

  # (목적: 여러 머신·프로젝트의 대화·사용량을 공유 저장소(Postgres, mods.sys.services.claude-ctx)에 이벤트 시점에 적재)
  # 클라이언트 CLI `donghans`: `donghans ctx hook|ingest|search|recent|session|usage|sql` / `donghans handoff put|get`.
  # 접속 문자열은 ~/.config/claude-ctx/dsn (nix 밖, 권한 600 — 비밀번호가 스토어에 남지 않게). 서버 위치는 거기서만 바꾼다.
  claudeCtx = pkgs.writers.writePython3Bin "donghans" {
    libraries = [pkgs.python3Packages.psycopg];
    doCheck = false;
  } (builtins.readFile ../../_data/claude-ctx/claude_ctx.py);
  # 훅은 비동기(입력을 막지 않음)이고 실패해도 조용히 끝난다. 놓친 것은 ingest 타이머가 따라잡는다.
  ctxHook = event: [
    {
      hooks = [
        {
          type = "command";
          command = "${claudeCtx}/bin/donghans ctx hook ${event}";
          async = true;
          timeout = 30;
        }
      ];
    }
  ];
  hooksSettings = {
    # 상태 표시줄(5시간·주간 한도 % 표시 + limits.jsonl 기록)도 훅과 같은 --settings 로 주입해, 이 모듈을 쓰는 모든 호스트에 적용한다(스크립트는 스토어 경로).
    statusLine = {
      type = "command";
      command = "${../../_data/claude-usage/claude-usage-statusline}";
    };
    hooks = lib.genAttrs ["UserPromptSubmit" "Stop" "SubagentStop" "SessionStart" "SessionEnd" "PreCompact"] ctxHook;
  };
  hooksFile = pkgs.writeText "claude-ctx-hooks.json" (builtins.toJSON hooksSettings);
  hooksReducedFile = pkgs.writeText "claude-ctx-hooks-reduced.json" (builtins.toJSON (hooksSettings // {prefersReducedMotion = true;}));

  otelCollectorConfig = pkgs.writeText "claude-otel-collector.yaml" ''
    receivers:
      otlp:
        protocols:
          grpc: { endpoint: 127.0.0.1:4317 }
          http: { endpoint: 127.0.0.1:4318 }
    exporters:
      file/metrics:
        path: ''${env:HOME}/.local/share/claude-otel/metrics.jsonl
        rotation: { max_megabytes: 50, max_backups: 5 }
      file/logs:
        path: ''${env:HOME}/.local/share/claude-otel/events.jsonl
        rotation: { max_megabytes: 100, max_backups: 5 }
    service:
      telemetry: { metrics: { level: none } }
      pipelines:
        metrics: { receivers: [otlp], exporters: [file/metrics] }
        logs: { receivers: [otlp], exporters: [file/logs] }
  '';
in {
  hm = {
    home.packages = [claude unstable.antigravity-cli claudeCtx];

    # 훅이 놓친 대화·사용량을 따라잡는 안전망(오프셋 기반, 여러 번 돌아도 안전). 서버에 못 붙으면 다음 주기에 재시도.
    systemd.user.services.claude-ctx-ingest = {
      Unit.Description = "claude-ctx 백필(최근 2일)";
      Service = {
        Type = "oneshot";
        ExecStart = "${claudeCtx}/bin/donghans ctx ingest --days 2";
      };
    };
    systemd.user.timers.claude-ctx-ingest = {
      Unit.Description = "claude-ctx 백필 주기";
      Timer = {
        OnBootSec = "2min";
        OnUnitActiveSec = "10min";
        Persistent = true;
      };
      Install.WantedBy = ["timers.target"];
    };

    systemd.user.services.claude-otel-collector = {
      Unit.Description = "Claude Code 사용량(OTLP) 로컬 수집기 — 파일로만 저장";
      Service = {
        ExecStartPre = "${pkgs.coreutils}/bin/mkdir -p %h/.local/share/claude-otel";
        ExecStart = "${pkgs.opentelemetry-collector-contrib}/bin/otelcol-contrib --config ${otelCollectorConfig}";
        Restart = "on-failure";
        RestartSec = 5;
      };
      Install.WantedBy = ["default.target"];
    };

    # Gemini CLI 지침 (기존 메모리 동기화 및 전역 원칙 강제)
    # home.file.".gemini/GEMINI.md" = {
    #   text = ''
    #     # Gemini Added Memories
    #     - Answer in korean.
    #     - 코드 수정은 최소한으로, git diff 확인을 통해 잘못 수정된것은 정정할 것
    #     - md 등의 문서가 길어진다면 분리해서 작성할 것
    #   '';
    #   force = true; # 기존 파일이 있더라도 Nix 관리 하에 둠
    # };

    # Claude Code 전역 지침
    # 소스가 nix에 있으므로 git으로 diff 추적이 되고, 생성물은 store로 심볼릭링크되어 읽기 전용.
    # -> ~/.claude/CLAUDE.md 를 직접 수정하지 말고 이 블록을 수정할 것.
    home.file.".claude/CLAUDE.md" = {
      text =
        ''
          # 환경 정보
          - 이 시스템은 NixOS이며, 스왑 영역의 일부는 ZRAM으로 구성되어 있을 수 있습니다.
            메모리/스왑 관련 작업(OOM 대응, 스왑 크기 조정 등) 전에 실제 스왑이 디스크인지 ZRAM인지 먼저 확인하세요.
          - 하드웨어/OS 상세 스펙(디스크, 파일시스템, 부트로더, 커널 파라미터 등)은 추측하지 말고
            `~/nixos/hosts/(현재 호스트명).nix`, `~/nixos/hosts/(현재 호스트명).toml`, 있다면 `~/nixos/hosts/(현재 호스트명)/` 디렉토리를 직접 읽어 확인하세요.
            현재 호스트명은 `hostname` 명령으로 확인합니다.
          - 이 프레임워크(`nixup`, mods/hosts 구조 등)에 대한 전반적인 설명은 `~/nixos/README.md`를 먼저 읽어보세요.
          - 명령어 실행 중 시스템에 없는 패키지가 필요하다면, 임의로 설치하지 말고 `nix shell nixpkgs#<패키지명>`으로 일회성 실행하세요.
          - 이 시스템에는 `unzip`이 없습니다. zip 등의 압축 해제는 `7z x <파일> -o<대상디렉토리>`를 사용하세요
            (`unzip`을 위해 `nix shell nixpkgs#unzip`을 쓰지 마세요).
          - playwright/puppeteer 등 브라우저 자동화·E2E 테스트는 호스트에서 설치·실행하지 말고 Docker 컨테이너 안에서 실행하세요
            (예: `mcr.microsoft.com/playwright` 이미지). 호스트에는 브라우저 바이너리를 받지 않도록
            `PUPPETEER_SKIP_DOWNLOAD`/`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`가 설정되어 있으니 해제하지 마세요.
          - `/tmp` 는 tmpfs 라 재부팅하면 지워집니다. 나중에 필요한 데이터(측정 결과, 작업 중간 산출물 등)는
            재부팅이 필요한 작업(`nixup` 의 재부팅, `reboot` 등)을 사용자에게 요청하기 전에 먼저 디스크(저장소 문서나 `~/` 아래)로 백업해 두세요.

          # 기록 원칙
          - 진행한 작업, 원인 파악 결과, 삽질 기록 등 project/domain 성격의 정보는
            Claude Code의 자동 메모리 시스템(`~/.claude/projects/.../memory/`)에 남기지 마세요.
            대신 작업 중인 프로젝트 저장소 내 git 추적 가능한 문서(`_docs/`, README 등)로 남기세요.

          # 세션 사용량
          - 하위 에이전트(Agent)를 띄우거나 큰 작업을 시작하기 전에 예상 비용(에이전트 수·모델)을 먼저 말하세요.
            에이전트당 시작 비용이 큽니다(컨텍스트 3~4만 토큰). 합칠 수 있으면 합치고,
            정답이 명확한 읽기·치환은 `model: 'haiku'`, 판단이 중요한 구현·검증은 sonnet 으로 지정하세요.
          - **기계적 작업과 병행하는 하위 에이전트는 haiku 를 적극적으로 쓰세요.** 기계적 작업 = 판단 없이 절차대로 되는 일
            (스택·서비스 기동과 상태 확인, 스크립트·테스트 실행과 결과 수집, 파일 검색·목록화·치환, 로그·값 대조, 증거 파일 복사·정리).
            여러 개를 병렬로 돌릴 때도 같다. 결과의 **판정·해석**, 되돌릴 수 없는 동작(삭제·환불·결제·푸시·DB 초기화 등)의 실행 결정,
            설계·구현·검증 판단은 haiku 에 맡기지 말고 직접 하거나 sonnet 으로 하세요. haiku 의 「통과·이상 없음」 보고는
            원자료(출력·값)를 직접 한 번 확인한 뒤에만 채택하세요.
          - 기본 모델을 바꾸기 전에는 반드시 먼저 알리세요.
          - 큰 작업 직전에 한도 감시를 거세요: `echo $CLAUDE_CODE_SESSION_ID` 의 앞 8자로
            `claude-limit-watch <접두>` 를 Monitor 로 실행합니다(5시간 한도가 10분 내 +5포인트 오르거나 50/70/80/90% 도달 시 알림).
            알림이 오면 하던 일을 멈추고 사용자에게 알리세요. 70% 이상에서는 새 작업을 시작하지 말고 묻습니다.
          - 세션을 닫거나 `/clear` 하기 전에는 `/donghans-handoff`, 새 세션에서는 `/donghans-resume <고유번호>` 로 이어갑니다.
          # 공유 컨텍스트 (여러 머신·프로젝트의 대화/사용량 저장소 — Postgres, `donghans ctx` 명령)
          - 「이전 세션에서 뭘 했는지 모르겠다」「그때 사용자가 뭐라고 했나」「다른 머신에서 하던 작업」처럼 **지난 대화·결정의 근거**가 필요하면,
            추측하거나 사용자에게 되묻기 전에 먼저 조회하세요: `donghans ctx search "<키워드>" --here`(현재 저장소 한정, `--role user` 로 사용자 발언만),
            `donghans ctx recent --here`(최근 세션), `donghans ctx session <세션ID접두> [--n 20]`(한 세션의 대화), `donghans ctx usage`(모델·일별 토큰/비용),
            `donghans ctx sql "<SELECT …>"`(읽기 전용; 테이블: sessions·messages·usage_events·hook_events·handoffs). 각 행에 작업 머신(host)·작업 디렉터리(cwd)·
            저장소(repo_url)·브랜치가 있으니 **다른 프로젝트의 기록이 섞이지 않았는지 repo_url 로 확인**하고 인용하세요.
          - 조회 결과는 그 시점의 기록이다(코드의 현재 상태가 아님). 결함·완료 주장은 다시 실행해 확인하세요. 접속 실패 시(서버 `beelink-ser7-co` 꺼짐 등)
            조용히 넘어가지 말고 사용자에게 알리세요. 기록에는 고객사 데이터·시크릿이 섞여 있을 수 있으니 원문을 외부로 보내지 마세요.
        ''
        + observeInstructions;
      force = true; # 기존 파일이 있더라도 Nix 관리 하에 둠 (읽기 전용 심볼릭링크)
    };

    # 범용 인수인계/복원 스킬 (어느 저장소에서든 /donghans-handoff, /donghans-resume <고유번호>)
    # 소스: mods/_data/claude-skills/ — 고유번호 = 인수인계한 세션 ID, 기록은 ~/.claude/handoffs/<ID>.json
    home.file.".claude/skills/donghans-handoff" = {
      source = ../../_data/claude-skills/donghans-handoff;
      force = true;
    };
    home.file.".claude/skills/donghans-resume" = {
      source = ../../_data/claude-skills/donghans-resume;
      force = true;
    };

    # 사용량 도구: 상태 표시줄 기록기 + 한도 감시기(Monitor 용).
    # 상태 표시줄 연결은 위 hooksSettings.statusLine 이 --settings 로 주입한다(`claude` 셸 함수로 실행할 때). ~/.claude/settings.json 에 같은 항목이 수동으로 있어도 충돌하지 않는다.
    home.file.".local/bin/claude-usage-statusline" = {
      source = ../../_data/claude-usage/claude-usage-statusline;
      executable = true;
      force = true;
    };
    home.file.".local/bin/claude-limit-watch" = {
      source = ../../_data/claude-usage/claude-limit-watch;
      executable = true;
      force = true;
    };

    # claude 실행 전 sudo 인증을 미리 받아두고, 백그라운드에서 60초마다 타임스탬프를 갱신.
    # (목적: 세션 도중 Claude가 sudo 필요한 명령을 실행할 때마다 비밀번호/지문 프롬프트로 막히는 것 방지)
    # -> sudoers를 NOPASSWD로 여는 대신, 최초 1회 인증 후 셸이 살아있는 동안만 캐시를 유지하는 방식.
    programs.zsh.initContent = ''
      claude() {
        sudo -v || return 1
        ( while sudo -n true 2>/dev/null; do sleep 60; kill -0 "$$" 2>/dev/null || exit; done & ) 2>/dev/null
        ${settingsSnippet}
        command claude "$@"
      }
    '';
  };
})
