# git 히스토리 정리 계획

## 목표

1. 시도/WIP 커밋들을 최종 결과 커밋에 squash
2. 포괄적인 커밋 메시지를 구체적으로 reword
3. `stable` 브랜치를 `main`으로 rename

---

## 브랜치 rename: stable → main

rolling/stable 구분 용도로 잡아뒀던 브랜치명이지만 이제 그 구분은 lock 파일과 stateVersion으로 처리하므로 불필요함.

```bash
# 로컬 브랜치 rename
git branch -m stable main

# remote 기본 브랜치 변경 (GitHub 웹 → Settings → Branches → Default branch 먼저 변경 권장)
git push origin -u main
git push origin --delete stable
```

GitHub에서 default branch를 `main`으로 바꾸기 전에 `stable`을 삭제하면 push가 실패할 수 있으므로,
**순서**: GitHub Settings에서 default branch 변경 → 위 명령 실행.

---

## interactive rebase

```bash
git rebase -i da1c625
```

`da1c625`는 최초 커밋. 에디터에서 아래 그룹별로 처리.

---

## squash 대상 그룹

### Group 1 — nixos-setup 명령 경로 문제 (3 → 1)

| 액션 | 해시 | 현재 메시지 |
|------|------|------------|
| pick | `98537c2` | nixos-setup 명령어 문제 해결 시도 |
| fixup | `bb154e9` | nixos-setup 명령어 문제 해결 시도 2 |
| reword | `3c38a8b` | nixup이 제대로 실행되지 않는 문제 해결 |

→ 새 메시지: `nixup 실행 경로 문제 해결 (SCRIPT_DIR 누락)`

> 참고: `f4974e0 nixup-install로 네이밍 변경 및 이것저것 기능 구현`과 `7025d74 nixup-install 관련 문제 해결`도
> 같은 맥락이므로 세 커밋을 한 번에 squash해도 무방.

---

### Group 2 — nhw → nixup 전면 변경 (4 → 1)

| 액션 | 해시 | 현재 메시지 |
|------|------|------------|
| pick | `5709130` | nhw->nixup 명령어 변경 |
| fixup | `11b47c4` | nhw->nixup 수정하면서 누락된 부분 반영 |
| fixup | `518301d` | 문서 최신화 |
| fixup | `a6ae0bf` | 문서 최신화 |

→ 새 메시지: `nhw → nixup 명령어 및 문서 전면 변경`

---

### Group 3 — incus 네트워크 문제 (2 → 1)

| 액션 | 해시 | 현재 메시지 |
|------|------|------------|
| pick | `2aa95e2` | incus 내부 패킷 문제 해결 시도 |
| fixup | `7c0efcf` | 네트워크 설정 수정 |

→ 새 메시지: `incus 내부 네트워크 라우팅 문제 해결 (nftables forward 정책)`

---

### Group 4 — ISO setup 경고·계정 (2 → 1)

| 액션 | 해시 | 현재 메시지 |
|------|------|------------|
| pick | `5487db8` | iso setup중 경고 해결 시도 |
| fixup | `3417d86` | iso setup 시 계정설정 부분 변경 |

→ 새 메시지: `iso setup 경고 및 계정 설정 수정`

---

### Group 5 — WIP 업로드 커밋 흡수

| 액션 | 해시 | 현재 메시지 |
|------|------|------------|
| fixup | `4764eff` | 작업 진행상황 업로드 (iso-vm에서의 클립보드 문제...) |

바로 위 또는 아래의 관련 커밋(`5177a87 Incus+viewer 및 tailscale 문제 해결` 또는
`6148276 XWayland->Wayland 빈 문자열 클립보드 문제 해결`)에 fixup.

---

### reword 후보 (squash 없이 메시지만 수정)

| 해시 | 현재 메시지 | 제안 |
|------|------------|------|
| `c3aee63` | 추가 정리 | nixstrap Phase 1 입력 흐름 정리 |
| `9546d75` | 기타 정리 및 문서 최신화 | (내용 확인 후 구체화) |
| `54bd00b` | 미흡한 부분 개선 | (내용 확인 후 구체화) |

---

## 주의사항

- rebase 완료 후 remote에 force push 필요: `git push --force-with-lease origin main`
- `--force-with-lease`는 remote에 자신이 모르는 커밋이 있으면 거부함 → 안전한 force push
- rebase 중 conflict가 나면 `git rebase --abort`로 취소 후 재시도
- 단독 작업 레포이므로 히스토리 재작성에 따른 협업 충돌 위험 없음

---

## 실행 순서 요약

```bash
# 1. rebase
git rebase -i da1c625

# 2. 에디터에서 위 그룹별로 pick/fixup/reword 지정

# 3. reword 시 에디터에서 새 메시지 입력

# 4. 완료 후 remote push
git push --force-with-lease origin main

# 5. GitHub Settings → Branches → stable 삭제 (이미 main으로 전환 후)
```
