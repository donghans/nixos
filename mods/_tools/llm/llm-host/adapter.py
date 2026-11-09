"""백엔드 어댑터 인터페이스. 설계: ctx 문서 plan llm-trust/11-p5prime-2-session-host §4-1·§4-4.

어댑터 = 벤더(claude 등)의 날 줄 ↔ 내부 이벤트·명령(events.py) 번역기. 프로세스·상태기계·정책은 모른다(session.py 몫).
- argv(spec)/env(spec): 기동 명령행과 환경(쓰기 쪽, S3 이후)
- decode(line) -> [Event]: 백엔드가 낸 줄 하나 → 이벤트 0개 이상. **상태를 가진다**(누적 비용·턴·init 비교 등) — 세션마다 어댑터 인스턴스 하나.
- encode(Command) -> [str]: 소비자 명령 → 백엔드로 보낼 줄들(개행 없음)
- capabilities: 능력 표(불리언 또는 "unknown")

decode 가 돌려주는 이벤트의 seq·ts 는 채우지 않는다(0). session.py 가 받는 순서대로 seq·ts 를 매긴다.
번역표에 없는 줄은 버리지 않고 Raw 이벤트로 돌려준다(프로토콜 변경 탐지).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Union

from events import Command, Event

UNKNOWN = "unknown"


class Adapter(ABC):
    name: str = ""

    @abstractmethod
    def argv(self, spec: dict) -> list:
        """기동 명령행(실행 파일 포함). spec 은 events.Start.spec 과 같다."""

    @abstractmethod
    def env(self, spec: dict) -> dict:
        """자식 프로세스 환경 변수(전체, 상속하지 않는다)."""

    @abstractmethod
    def decode(self, line: Union[str, bytes, dict]) -> list:
        """백엔드 출력 줄 하나 → [Event]. 빈 줄은 []. 해석 못 하는 줄은 [Raw]."""

    @abstractmethod
    def encode(self, command: Command) -> list:
        """소비자 명령 → 백엔드 입력 줄들(개행 없는 문자열). 호스트 안에서만 쓰는 명령은 []."""

    @property
    @abstractmethod
    def capabilities(self) -> dict:
        """능력 표: {능력: True | False | "unknown"} (README 의 능력 표 참조)."""
