## 로그 확인

모든 `nixup` 실행 결과는 `/var/log/nixup/`에 자동으로 기록됩니다.

- 파일명 형식: `YYYYMMDDTHHMMSS.log` (예: `20260405T120000.log`)
- 빌드 실패 시에만 `YYYYMMDDTHHMMSS.nom-build.log`가 추가로 생성됩니다. 성공 시에는 자동으로 삭제됩니다.
- 터미널에는 nom 색상 출력이 표시되지만, 저장된 로그 파일은 ANSI 색상 코드가 제거된 순수 텍스트로 저장됩니다.
- 로그는 최근 30개까지 자동으로 보관됩니다.

```bash
# 최근 로그 확인
tail -f /var/log/nixup/$(ls -t /var/log/nixup/*.log | head -n 1)

# 빌드 실패 시 빌드 로그 확인
cat /var/log/nixup/*.nom-build.log
```
