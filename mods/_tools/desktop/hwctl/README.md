# hwctl 쉘 스크립트 본문

`mods/gui/base/core.bind.hwctl.nix`(노트북 하드웨어 키 처리)의 쉘 스크립트 중 순수 쉘로 뺄 수 있는 것의 본문.
shebang 은 없다(`writeShellScriptBin` 이 붙인다). Nix 쪽은 `builtins.replaceStrings` 로 `@이름@` 자리표시자를 스토어 경로·값으로 바꿔 넘긴다.
(`replaceVars` 는 쓰지 않는다: `@DEFAULT_AUDIO_SINK@` 같은 wpctl 예약어까지 치환 대상으로 보고 빌드가 실패한다. 목록에 없는 `@…@` 는 그대로 남는다.)

| 파일 | 스크립트 | 자리표시자 |
|---|---|---|
| `vol-control.sh` | `vol-control` | `@wpctl@`(wireplumber 의 wpctl 경로), `@notify_send@` |
| `brt-control.sh` | `brt-control` | `@brightnessctl@`(실행 파일 경로), `@notify_send@` |
| `lid-screen.sh` | `lid-screen` | `@brightnessctl@` |
| `toggle.sh` | `hypr-toggle-touchpad`, `hypr-toggle-touchscreen` (인스턴스별 치환) | `@posture@`(posture CLI 의 `posture` 경로), `@notify_send@`, `@input_policy@`(hypr-input-policy 경로), `@bin@`(스크립트 이름), `@label@`(알림 제목), `@file@`(수동 상태 파일 이름), `@field@`(`--print` 출력의 필드 번호), `@locked_msg@`(텐트/태블릿 안내) |

`@DEFAULT_AUDIO_SINK@`·`@DEFAULT_AUDIO_SOURCE@` 는 치환 대상이 아니라 wpctl 이 해석하는 값이다.

호스트 설정(`config.…`)에 따라 Nix 식이 본문을 바꾸는 `lid-policy`·`hypr-input-policy`·`hypr-device-menu` 는 Nix 에 남겨 둔다.
