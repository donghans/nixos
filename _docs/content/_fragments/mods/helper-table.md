## 헬퍼 선택 기준

| 상황 | 헬퍼 | 예시 |
|------|------|------|
| 독립적으로 켜고 끌 수 있는 기능 | `mkMod` | docker, bluetooth |
| 부모 도메인이 켜지면 같이 켜지는 기능 | `mkModOf` | vivaldi (gui의 자식) |
| 부모와 항상 같이 움직이는 서브파트 | `mkPartOf` | fuzzel (gui의 일부) |

상세 비교:

| | `mkMod` | `mkModOf` | `mkPartOf` |
|---|---|---|---|
| **enable 옵션** | 자동 생성 | 자동 생성 | 없음 |
| **활성화 조건** | preset/host.toml에서 명시 | 부모 enable 시 `mkDefault true` | 부모 enable에 종속 |
| **cfg 바인딩** | 자기 경로의 config | 자기 경로의 config | **부모** 경로의 config |
| **preset TOML 등록** | 필요 | 필요 | 불필요 |
| **Coverage Check 대상** | 예 | 예 | 아니오 |

의사결정 트리:

```
사용자가 직접 끄고 켤 수 있어야 하는가?
├── 아니오 → mkPartOf (부모와 항상 같이)
└── 예
    ├── 부모 도메인 활성화 시 기본 켜짐? → mkModOf
    └── 완전히 독립? → mkMod
```

**`mkMod`**: 서비스(docker, bluetooth), 도메인 마스터 스위치(gui.nix, devel.nix)  
**`mkModOf`**: GUI 앱(vivaldi, slack), 개발 도구(node, python) — 부모 도메인에 기본 포함  
**`mkPartOf`**: 설정 파편(키바인딩, 테마, 커서) — 옵션으로 노출할 필요 없는 서브파트
