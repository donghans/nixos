"""observe_stats — A/B(번갈아 재기) 결과를 **추정이 아니라 통계로** 판정한다. 표준 라이브러리만.

입력: 조건별 표본 목록(예: 구간 평균 전력) 또는 A→B 쌍 목록.
판정 규칙(문서 power-evidence.md 와 같음; 2026-10-21 강화):
  - 효과 = 평균(B) − 평균(A), 쌍별 차이 d_i = B_i − A_i.
  - 쌍이 **3개 이상**이고 모두 같은 부호이며 |평균 효과| ≥ 임계값 → "확인(측정)".
  - 쌍이 2개뿐이면(같은 부호·임계 이상이어도) → "일치(약함, 2쌍)" — 2쌍으로는 부호검정 p 가 0.5 라 우연과 구분되지 않는다.
  - 부호가 섞이거나 임계값 미만 → "불확실" (효과가 있어도 작다고 보고 코드를 바꾸지 않음).
"""
import math, random, statistics as st


def mean(x):
    return st.fmean(x) if x else float("nan")


def sd(x):
    return st.stdev(x) if len(x) > 1 else 0.0


def pair_diffs(a, b):
    """a, b 는 같은 길이의 구간 평균(시간순 교대: A1 B1 A2 B2 …)에서 뽑은 목록. 쌍별 B−A."""
    n = min(len(a), len(b))
    return [b[i] - a[i] for i in range(n)]


def bootstrap_ci(d, iters=2000, alpha=0.05, seed=12345):
    """쌍별 차이 평균의 부트스트랩 신뢰구간(시드 고정 → 재현 가능). 쌍이 3개 미만이면 의미가 없어 None."""
    if len(d) < 3:
        return None
    rng = random.Random(seed)
    means = sorted(mean([rng.choice(d) for _ in d]) for _ in range(iters))
    return means[int(alpha / 2 * iters)], means[int((1 - alpha / 2) * iters) - 1]


def sign_test_p(d):
    """부호 검정 양측 p 값(0 차이 제외). 쌍이 적으면 p 가 크게 나오는 게 정상."""
    nz = [x for x in d if x != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    k = max(sum(1 for x in nz if x > 0), sum(1 for x in nz if x < 0))
    p = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return min(1.0, 2 * p)


def verdict(a, b, threshold):
    """A/B 구간 평균 목록 → 요약 dict. threshold 는 효과로 인정할 최소 크기(예: 전력 0.3 W)."""
    d = pair_diffs(a, b)
    eff = mean(d) if d else float("nan")
    same_sign = bool(d) and (all(x < 0 for x in d) or all(x > 0 for x in d))
    big = (not math.isnan(eff)) and abs(eff) >= threshold
    if len(d) < 2:
        label = "표본 부족"
    elif same_sign and big and len(d) >= 3:
        label = "확인(측정)"
    elif same_sign and big:
        label = "일치(약함, 2쌍)"
    else:
        label = "불확실"
    return {"n_pairs": len(d), "mean_a": mean(a), "mean_b": mean(b), "effect": eff, "diffs": d, "sd_a": sd(a), "sd_b": sd(b),
            "same_sign": same_sign, "ci95": bootstrap_ci(d), "sign_p": sign_test_p(d), "threshold": threshold, "verdict": label}
