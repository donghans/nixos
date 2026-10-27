
# 프로세스 종료 (procctl)
- 프로세스를 종료·정리할 때 `pkill`·`killall`·`kill`(이름·패턴·PID 직접 지정)을 쓰지 말고 `donghans-procctl` 스킬의 `procctl` 을 쓰세요(plan → 사용자 확인 → apply). 자기 세션의 조상·다른 세션·시스템 프로세스를 죽이는 사고와 PID 재사용 오발송을 막고 기록을 남깁니다.
- `procctl groups`·`show`·`plan`·`log` 는 읽기 전용이라 바로 실행해도 되지만 `procctl apply`·`escalate` 는 되돌릴 수 없으니 계획 내용(대상·보호로 제외된 것·범위 밖)을 사용자에게 보여 주고 확인받은 뒤에만 실행하세요. 보호를 풀거나 우회하려 하지 마세요(보호 해제는 사람이 `procui` 에서만).
