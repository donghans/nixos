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

  # 상세 절차는 CLAUDE.md 를 비대하게 만들지 않도록 스킬(mods/_data/claude-skills/)로 두고, 여기에는 「언제 그 스킬을 읽나」와 어겨선 안 되는 안전 규칙만 남긴다.
  # 스킬 설명이 색인 역할을 한다(설명은 항상 보이고 본문은 불렀을 때만 읽힌다).
  #
  # observectl(관측 시스템)이 설치된 호스트에서만 지침에 넣는다(호스트 toml 의 observe = true; workstation 프리셋은 기본 켬). 조회 방법 본문: donghans-observe 스킬. 지침 본문은 llm-cli/*.md (README.md 참고).
  # 호스트 종류별 목표가 다르다: 노트북 = 배터리 사용량 관리·개선, 데스크톱 = 비효율 프로세스 관리·집중할 곳에 자원 쓰기.
  observeInstructions = lib.optionalString config.mods.sys.services.observe.enable (builtins.readFile ./llm-cli/observe.md);

  # 프로세스 정리: pkill·kill·killall 대신 procctl(plan → 사용자 확인 → apply, 보호 규칙·PID 재사용 방어·기록). observe 모듈이 procctl 을 설치하므로 같은 조건. 절차 본문: donghans-procctl 스킬.
  procctlInstructions = lib.optionalString config.mods.sys.services.observe.enable (builtins.readFile ./llm-cli/procctl.md);

  # incus VM `qa-desktop`(화면 확인용 QA 데스크톱)이 있는 호스트에서만 지침에 넣는다(호스트 toml 의 qa-desktop = true; 프리셋 기본 꺼짐).
  # 여러 프로젝트의 QA 세션이 VM 하나를 공유한다. 절차 본문: donghans-qa-desktop 스킬, 설명·검증 기록: mods/_tools/qa-desktop/README.md.
  qaDesktopInstructions = lib.optionalString config.mods.sys.services.qa-desktop.enable (builtins.readFile ./llm-cli/qa-desktop.md);
  # 훅(llm-ctx)은 항상 --settings 로 주입한다 — ~/.claude/settings.json 은 Claude 가 직접 쓰는 가변 파일이라 nix 로 소유하지 않는다.
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

  # (목적: 여러 머신·프로젝트의 대화·사용량을 공유 저장소(Postgres, mods.sys.services.llm-ctx)에 이벤트 시점에 적재)
  # 클라이언트 CLI `donghans`: `donghans ctx hook|ingest|search|recent|session|usage|sql` / `donghans handoff put|get`.
  # 접속 문자열은 ~/.config/claude-ctx/dsn (nix 밖, 권한 600 — 비밀번호가 스토어에 남지 않게). 서버 위치는 거기서만 바꾼다.
  # 여러 파일(llm_ctx: 명령, ctx_secrets: 비밀 등록표·치환·주입·후보 탐지·로컬 치환, ctx_instr: 프로젝트별 지침 공유 동기화, ctx_docs: 계획·QA 기록 같은 프로젝트 문서 정본, agents/: 에이전트별(Claude Code 등) 대화 형식 어댑터, ctxdata/ctxui: 관리 TUI, uikit: TUI 공통 틀)을 한 디렉터리에 모아 실행한다
  # (observe 의 usageui 와 같은 방식). 훅·타이머·사용자가 부르는 `donghans` 는 모두 이 래퍼다.
  ctxSrc = pkgs.runCommand "llm-ctx-src" {} ''
    mkdir -p $out
    ${lib.concatMapStringsSep "\n" (f: "cp ${../../_tools/llm-ctx + "/${f}"} $out/${f}") ["llm_ctx.py" "ctx_secrets.py" "ctx_instr.py" "ctx_docs.py" "ctxdata.py" "ctxchart.py" "ctxui.py"]}
    cp ${../../_tools/_lib/_uikit/uikit.py} $out/uikit.py
    mkdir -p $out/agents
    ${lib.concatMapStringsSep "\n" (f: "cp ${../../_tools/llm-ctx/agents + "/${f}"} $out/agents/${f}") ["__init__.py" "claude.py"]}
  '';
  claudeCtx = pkgs.writeShellScriptBin "donghans" ''exec ${pkgs.python3.withPackages (ps: [ps.psycopg])}/bin/python3 ${ctxSrc}/llm_ctx.py "$@"'';
  # ctx 관리 TUI(Textual): 저장소별 용량·검색·발언 대조·비밀 등록표·후보 탐지. 사람이 터미널에서 쓰는 도구(`ctxui`).
  ctxui = pkgs.writeShellScriptBin "ctxui" ''exec ${pkgs.python3.withPackages (ps: [ps.psycopg ps.textual])}/bin/python3 ${ctxSrc}/ctxui.py "$@"'';

  # (목적: ssh 와 kitty 에서 같은 claude 세션을 이어 쓰기) claude 를 전용 tmux 서버(`tmux -L claude`, 일반 tmux 와 분리) 안에서 돌리고,
  # `llm-sessions`(목록 UI)로 어디서든 붙는다. 한 세션에 여러 곳이 동시에 붙으면 화면이 서로 비친다(tmux 기본 동작).
  # 대화형 `claude` 셸 함수만 이 경로를 타고(아래 initContent), `claude -p`·서브커맨드·스크립트가 부르는 claude 는 그대로다. 끄기: CLAUDE_TMUX=0 claude.
  # 설계·시험 기록: mods/_tools/llm-sessions/README.md
  sessionsSrc = pkgs.runCommand "llm-sessions-src" {} ''
    mkdir -p $out
    ${lib.concatMapStringsSep "\n" (f: "cp ${../../_tools/llm-sessions + "/${f}"} $out/${f}") ["llm_sessions.py" "tmuxsess.py" "claude-tmux" "claude-tmux.conf"]}
    chmod +x $out/claude-tmux
    cp ${../../_tools/_lib/_uikit/uikit.py} $out/uikit.py
  '';
  tmuxEnv = ''
    export CLAUDE_TMUX_BIN=${pkgs.tmux}/bin/tmux CLAUDE_TMUX_CONF=${sessionsSrc}/claude-tmux.conf CLAUDE_RUN_BIN=${claudeRun}
  '';
  # tmux 안에서 실제로 claude 를 실행하는 쪽. sudo 인증 캐시는 tty 별이라(셸 함수의 `sudo -v` 는 pane 의 tty 에 효과가 없다) 여기서 다시 받고,
  # 이 프로세스(=claude 부모)가 살아 있는 동안만 60초마다 갱신한다. exec 하지 않는 이유: 끝난 뒤 갱신 루프도 같이 끝나게 하려고.
  claudeRun = pkgs.writeShellScript "claude-run" ''
    if [ -t 0 ]; then
      sudo -v || exit 1
      ( while sudo -n true 2>/dev/null; do sleep 60; kill -0 "$$" 2>/dev/null || exit; done & ) 2>/dev/null
    fi
    ${settingsSnippet}
    ${claude}/bin/claude "$@"
  '';
  claudeTmux = pkgs.writeShellScriptBin "claude-tmux" ''${tmuxEnv}exec ${pkgs.bash}/bin/bash ${sessionsSrc}/claude-tmux "$@"'';
  claudeSessions = pkgs.writeShellScriptBin "llm-sessions" ''${tmuxEnv}exec ${pkgs.python3.withPackages (ps: [ps.textual])}/bin/python3 ${sessionsSrc}/llm_sessions.py "$@"'';
  # 옛 이름 호환(2026-10-27 개명 llm-sessions) — 습관·옛 문서가 쓰는 `claude-sessions` 가 그대로 열리게 하는 별칭. 필요 없어지면 이 줄과 packages 항목을 지운다.
  claudeSessionsAlias = pkgs.writeShellScriptBin "claude-sessions" ''exec ${claudeSessions}/bin/llm-sessions "$@"'';
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
  hooksSettings =
    {
      # 상태 표시줄(5시간·주간 한도 % 표시 + limits.jsonl 기록)도 훅과 같은 --settings 로 주입해, 이 모듈을 쓰는 모든 호스트에 적용한다(스크립트는 스토어 경로).
      statusLine = {
        type = "command";
        command = "${../../_tools/llm-usage/claude-usage-statusline}";
      };
      hooks = lib.genAttrs ["UserPromptSubmit" "Stop" "SubagentStop" "SessionStart" "SessionEnd" "PreCompact"] ctxHook;
    }
    // lib.optionalAttrs config.mods.sys.services.observe.enable {
      # procctl(observe 모듈이 설치): 조회·계획은 자동 허용, 적용(되돌릴 수 없음)은 항상 사용자 확인 — 하네스가 강제한다. 문법은 Claude Code 권한 규칙(Bash 접두 일치).
      permissions = {
        allow = ["Bash(procctl groups:*)" "Bash(procctl show:*)" "Bash(procctl plan:*)" "Bash(procctl log:*)"];
        ask = ["Bash(procctl apply:*)" "Bash(procctl escalate:*)"];
      };
    };
  hooksFile = pkgs.writeText "llm-ctx-hooks.json" (builtins.toJSON hooksSettings);
  hooksReducedFile = pkgs.writeText "llm-ctx-hooks-reduced.json" (builtins.toJSON (hooksSettings
    // {
      prefersReducedMotion = true;
      # 창 제목 갱신(스피너)도 끈다 — 화면 갱신 3→2/s·PSR 유지 57→69%·psys 약 −0.5 W(power-evidence.md #101). 제목 정보는 쓰지 않는다(사용자 결정 2026-10-25). `CLAUDE_MOTION=normal claude` 로 함께 풀린다.
      env.CLAUDE_CODE_DISABLE_TERMINAL_TITLE = "1";
    }));

  # 수집기 설정은 순수 데이터라 llm-cli/otel-collector.yaml 로 뺐다(`${env:HOME}` 는 수집기가 푸는 것이므로 Nix 보간이 아니다).
  otelCollectorConfig = pkgs.writeText "claude-otel-collector.yaml" (builtins.readFile ./llm-cli/otel-collector.yaml);
in {
  hm = {
    home.packages = [claude unstable.antigravity-cli claudeCtx ctxui claudeTmux claudeSessions claudeSessionsAlias];

    # 앱 런처(SUPER+Space)에서도 열리도록 등록(터미널 앱이라 uwsm 이 xdg-terminal-exec 로 kitty 에 띄움; usageui 와 같은 방식).
    # (런처에 보이는 이름은 다른 앱들처럼 영어로 통일)
    xdg.desktopEntries.ctxui = {
      name = "LLM Context Manager";
      genericName = "LLM conversation store";
      comment = "Storage per project, search, cross-check what I said, manage protected secrets — from the shared ctx database";
      exec = "${ctxui}/bin/ctxui";
      terminal = true;
      categories = ["Utility"];
      icon = "utilities-terminal";
    };

    xdg.desktopEntries.llm-sessions = {
      name = "Claude Sessions";
      genericName = "claude tmux sessions";
      comment = "List claude sessions running in tmux, attach from this terminal, or start a new one";
      exec = "${claudeSessions}/bin/llm-sessions";
      terminal = true;
      categories = ["Utility"];
      icon = "utilities-terminal";
    };

    # 훅이 놓친 대화·사용량을 따라잡는 안전망(오프셋 기반, 여러 번 돌아도 안전). 서버에 못 붙으면 다음 주기에 재시도.
    systemd.user.services.claude-ctx-ingest = {
      Unit.Description = "llm-ctx 백필(최근 2일)";
      Service = {
        Type = "oneshot";
        ExecStart = "${claudeCtx}/bin/donghans ctx ingest --days 2";
        # 등록된 비밀(`donghans secret add`)이 있으면, 3시간 넘게 한가한 로컬 트랜스크립트에서 그 값을 [protected] 로 바꾼다(원문은 DB 에 보존, 적재가 끝난 파일만,
        # 바뀐 것이 없으면 조용함, 안 바뀐 파일은 캐시로 건너뜀). 등록표가 비어 있으면 아무 일도 하지 않는다. 끄려면 이 줄을 지운다. 앞의 `-` 는 실패해도 유닛을 실패로 보지 않는다는 뜻.
        ExecStartPost = "-${claudeCtx}/bin/donghans secret scrub --apply --quiet --idle-min 180";
      };
    };
    systemd.user.timers.claude-ctx-ingest = {
      Unit.Description = "llm-ctx 백필 주기";
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
      # 본문은 llm-cli/claude-md.md (끝 개행 포함), 호스트 기능별 절은 아래 *Instructions (llm-cli/*.md).
      text =
        builtins.readFile ./llm-cli/claude-md.md
        + observeInstructions
        + procctlInstructions
        + qaDesktopInstructions;
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

    # 상세 절차 스킬 — CLAUDE.md 에는 호출 조건과 안전 규칙만 두고 본문은 불렀을 때만 읽히게 한다(위 observeInstructions·qaDesktopInstructions 참고).
    # donghans-ctx·donghans-qa 는 항상, observe·qa-desktop 은 해당 기능이 켜진 호스트에서만 등록한다.
    home.file.".claude/skills/donghans-ctx" = {
      source = ../../_data/claude-skills/donghans-ctx;
      force = true;
    };
    home.file.".claude/skills/donghans-qa" = {
      source = ../../_data/claude-skills/donghans-qa;
      force = true;
    };
    home.file.".claude/skills/donghans-limit-watch" = {
      source = ../../_data/claude-skills/donghans-limit-watch;
      force = true;
    };
    home.file.".claude/skills/donghans-host-resources" = {
      source = ../../_data/claude-skills/donghans-host-resources;
      force = true;
    };
    home.file.".claude/skills/donghans-doc-rigor" = {
      source = ../../_data/claude-skills/donghans-doc-rigor;
      force = true;
    };
    home.file.".claude/skills/donghans-observe" = lib.mkIf config.mods.sys.services.observe.enable {
      source = ../../_data/claude-skills/donghans-observe;
      force = true;
    };
    home.file.".claude/skills/donghans-procctl" = lib.mkIf config.mods.sys.services.observe.enable {
      source = ../../_data/claude-skills/donghans-procctl;
      force = true;
    };
    home.file.".claude/skills/donghans-ctl" = {
      source = ../../_data/claude-skills/donghans-ctl;
      force = true;
    };
    home.file.".claude/skills/donghans-qa-desktop" = lib.mkIf config.mods.sys.services.qa-desktop.enable {
      source = ../../_data/claude-skills/donghans-qa-desktop;
      force = true;
    };

    # 사용량 도구: 상태 표시줄 기록기(한도 감시기는 donghans-limit-watch 스킬).
    # 상태 표시줄 연결은 위 hooksSettings.statusLine 이 --settings 로 주입한다(`claude` 셸 함수로 실행할 때). ~/.claude/settings.json 에 같은 항목이 수동으로 있어도 충돌하지 않는다.
    home.file.".local/bin/claude-usage-statusline" = {
      source = ../../_tools/llm-usage/claude-usage-statusline;
      executable = true;
      force = true;
    };

    # claude 실행 전 sudo 인증을 미리 받아두고, 백그라운드에서 60초마다 타임스탬프를 갱신.
    # (목적: 세션 도중 Claude가 sudo 필요한 명령을 실행할 때마다 비밀번호/지문 프롬프트로 막히는 것 방지)
    # -> sudoers를 NOPASSWD로 여는 대신, 최초 1회 인증 후 셸이 살아있는 동안만 캐시를 유지하는 방식.
    programs.zsh.initContent = ''
      claude() {
        # 대화형 호출은 전용 tmux 세션 안에서 실행한다(ssh·다른 kitty 에서 llm-sessions 로 이어 붙기). sudo 인증은 세션 안(claude-run)에서 받는다.
        if claude-tmux --wants "$@"; then
          claude-tmux "$@"
          return
        fi
        sudo -v || return 1
        ( while sudo -n true 2>/dev/null; do sleep 60; kill -0 "$$" 2>/dev/null || exit; done & ) 2>/dev/null
        ${settingsSnippet}
        command claude "$@"
      }
    '';
  };
})
