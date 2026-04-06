# 🎯 Vision & Purpose (의도와 방향성)

본 리팩터링은 "내가 무엇을 사용하고 있는지 100% 장악한다"는 철학 아래, 무질서한 설정을 **논리적 도메인(Mods)**으로 격리하고 **명시적 선언(Explicit Opt-in)** 체계를 구축하는 것을 목적으로 합니다. 

1.  **Dual-Context Agility**: `nhw home switch`를 통한 가벼운 사용자 환경 갱신과 `nhw os switch`를 통한 견고한 시스템 기반 갱신을 완벽히 분리하고 공존시킵니다.
2.  **Absolute SSOT**: `_info.json`의 데이터를 `config.workspace` 전역 옵션으로 승격시켜 시스템 전반의 투명성을 확보합니다.
3.  **Strict Governance**: 프리셋에 정의되지 않은 기능은 스스로 판단하지 않으며, 사용자의 명시적 결정을 강제합니다.
4.  **Zero-Leak Security**: 어떤 형태의 비밀값(Secrets)도 레포지토리에 포함하지 않으며, 철저히 외부 관리자에게 위임합니다.
