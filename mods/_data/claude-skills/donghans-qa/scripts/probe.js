// 부재·미동작 주장용 다중 로케이터 탐침 (Playwright). donghans-qa §1 항목 3-1(부재 주장은 서로 다른 로케이터 3가지 이상 + 직접 지표)의 선택 도구.
// 사용: const { probe, probeAbsent, toMarkdown } = require('./probe.js');
//   const r = await probe(page, { name: '저장' }, { reset: async () => {...}, net: responseLogArray });
//   console.log(toMarkdown(r));   // 보고서에 그대로 붙인다
// 옵션: reset(효과가 난 뒤 상태 복원) · net(응답 로그 배열 — 주면 네트워크 응답 수 변화도 직접 지표에 포함, 안 주면 주소·제목·노드 집합 3개 지표만)
//       dryRun:true(쓰기 버튼용 — 누르지 않고 로케이터가 대상에 닿는지(count)만 확인한다. 이 경우 판정은 REACHED(종류 3개 이상 닿음)/INCONCLUSIVE/ABSENT 만 나온다)
// 판정: r.verdict ∈ 'EFFECT'(어느 방식이든 직접 지표가 변함) | 'NO_EFFECT'(서로 다른 **종류**의 로케이터 3개 이상 — 역할·텍스트·aria-label·조상 — 이 닿았으나 변화 없음)
//        | 'ABSENT'(전 방식 0건) | 'INCONCLUSIVE'(로케이터 종류 3개 미만만 닿음 — 확정 못 함: 사용자를 막는 것으로 보이면 결함 후보(미확정)로 올리고, 아니면 관찰로 둔다. 심각도는 낮추지 않는다)
// 직접 지표: 주소·제목·의미 노드(텍스트) 집합·네트워크 응답 수 — 「특정 텍스트 유무」 하나로 판정하지 않는다.
const STRATEGIES = ['role', 'textExact', 'textPartial', 'ariaLabel', 'ancestor', 'boxCenter', 'keyboard'];
const LOCATOR_NAMES = ['role', 'textExact', 'textPartial', 'ariaLabel', 'ancestor']; // 로케이터(동작 변형 boxCenter·keyboard 제외)
const KIND = { role: 'role', textExact: 'text', textPartial: 'text', ariaLabel: 'aria', ancestor: 'ancestor' }; // 텍스트 정확/부분은 한 종류로 센다(문서의 4종 정의와 일치)

const esc = (s) => s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
// XPath 문자열 리터럴 — 작은따옴표가 있으면 concat() 으로 이어 붙인다(백슬래시 이스케이프는 XPath 에서 무효)
const xp = (s) => (s.includes("'") ? 'concat(' + s.split("'").map((p) => "'" + p + "'").join(', "\'", ') + ')' : "'" + s + "'");

function locatorFor(page, strategy, spec) {
  const name = spec.name;
  switch (strategy) {
    case 'role': return page.getByRole(spec.role || 'button', { name, exact: false });
    case 'textExact': return page.getByText(name, { exact: true });
    case 'textPartial': return page.getByText(name, { exact: false });
    case 'ariaLabel': return page.locator(`[aria-label*="${esc(name)}"]`);
    case 'ancestor':
      return page.locator(
        `xpath=//*[contains(normalize-space(.), ${xp(name)})]/ancestor-or-self::*[@role='button' or self::button or self::a or @tabindex][1]`,
      );
    case 'boxCenter': // 동작 변형 — 호출부(probe)가 닿은 첫 로케이터로 대체한다
    case 'keyboard':
      return null;
    default: throw new Error('알 수 없는 방식 ' + strategy);
  }
}

async function snapshot(page, net) {
  const nodes = await page
    .evaluate(() =>
      [...document.querySelectorAll('[role], button, a, h1, h2, h3, flt-semantics')] // flt-semantics = Flutter 웹 접근성 노드(없으면 무시)
        .map((e) => (e.getAttribute('aria-label') || e.innerText || '').trim())
        .filter(Boolean)
        .slice(0, 2000),
    )
    .catch(() => []);
  return { url: page.url(), title: await page.title().catch(() => ''), nodes: new Set(nodes), net: net ? net.length : 0 };
}

function diff(a, b) {
  const added = [...b.nodes].filter((x) => !a.nodes.has(x));
  const removed = [...a.nodes].filter((x) => !b.nodes.has(x));
  return {
    urlChanged: a.url !== b.url,
    titleChanged: a.title !== b.title,
    nodesAdded: added.length,
    nodesRemoved: removed.length,
    netDelta: b.net - a.net,
    sample: { added: added.slice(0, 3), removed: removed.slice(0, 3) },
  };
}
const changed = (d) => d.urlChanged || d.titleChanged || d.nodesAdded > 0 || d.nodesRemoved > 0 || d.netDelta > 0;

/** opts: { reset?: async () => void, net?: string[] (응답 로그 배열), wait?: ms, strategies?: string[] } */
async function probe(page, spec, opts = {}) {
  const wait = opts.wait ?? 1500;
  const rows = [];
  for (const s of opts.strategies || STRATEGIES) {
    let loc = locatorFor(page, s, spec);
    if (!loc) {
      // 동작 변형(boxCenter·keyboard) — 앞에서 닿은 첫 로케이터를 같은 대상으로 쓴다(textPartial 하나에 매이지 않는다)
      const hit = rows.find((r) => LOCATOR_NAMES.includes(r.strategy) && r.matches > 0);
      loc = hit ? locatorFor(page, hit.strategy, spec) : null;
    }
    const n = loc ? await loc.count().catch(() => 0) : 0;
    if (n === 0) { rows.push({ strategy: s, matches: 0, outcome: 'miss' }); continue; }
    if (opts.dryRun) {
      if (LOCATOR_NAMES.includes(s)) rows.push({ strategy: s, matches: n, how: 'dryRun(누르지 않음)', outcome: 'reached' });
      continue;
    }
    const nodeKey = await loc.first().evaluate((e) => (e.tagName + '|' + (e.getAttribute('aria-label') || e.innerText || '').trim().slice(0, 40)), null, { timeout: 1500 }).catch(() => '?');
    const before = await snapshot(page, opts.net);
    let how = 'click';
    try {
      const first = loc.first();
      if (s === 'boxCenter') {
        const box = await first.boundingBox();
        if (!box) throw new Error('boundingBox 없음(화면 밖)');
        await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
        how = `center(${Math.round(box.x + box.width / 2)},${Math.round(box.y + box.height / 2)})`;
      } else if (s === 'keyboard') {
        await first.focus({ timeout: 3000 });
        await page.keyboard.press('Enter');
        how = 'focus+Enter';
      } else {
        await first.click({ timeout: 3000 }); // force 없이 — 가려져 있으면 그 사실도 결과다
      }
    } catch (e) {
      rows.push({ strategy: s, matches: n, outcome: 'error', note: String(e.message || e).split('\n')[0].slice(0, 120) });
      continue;
    }
    await page.waitForTimeout(wait);
    const after = await snapshot(page, opts.net);
    const d = diff(before, after);
    rows.push({ strategy: s, matches: n, how, node: nodeKey, outcome: changed(d) ? 'effect' : 'no-effect', delta: d });
    if (changed(d) && opts.reset) await opts.reset();
    else if (changed(d)) break; // 상태가 바뀌었으니 같은 전제로 다음 방식을 못 쓴다 — reset 이 없으면 여기서 끝
  }
  // 「닿았다」 는 **서로 다른 로케이터** 기준이다 — boxCenter·keyboard 는 textPartial 과 같은 대상을 다른 동작으로 누를 뿐이라 센다
  const reached = rows.filter((r) => LOCATOR_NAMES.includes(r.strategy) && r.matches > 0 && r.outcome !== 'error');
  const reachedKinds = new Set(reached.map((r) => KIND[r.strategy]));
  const effect = rows.some((r) => r.outcome === 'effect');
  const verdict = effect ? 'EFFECT' : rows.every((r) => r.matches === 0) ? 'ABSENT' : opts.dryRun ? (reachedKinds.size >= 3 ? 'REACHED' : 'INCONCLUSIVE') : reachedKinds.size >= 3 ? 'NO_EFFECT' : 'INCONCLUSIVE';
  return { spec, verdict, rows };
}

/** 「없다」 주장 전용 — 모든 방식이 0건일 때만 absent */
async function probeAbsent(page, spec) {
  const r = await probe(page, spec, { strategies: STRATEGIES.filter((s) => s !== 'boxCenter' && s !== 'keyboard') });
  return { ...r, absent: r.verdict === 'ABSENT' };
}

function toMarkdown(r) {
  const head = `| 방식 | 일치 수 | 동작 | 대상 노드 | 결과 | 주소 | 노드 +/− | 네트워크 Δ |\n|---|---|---|---|---|---|---|---|`;
  const lines = r.rows.map((x) => {
    const d = x.delta;
    return `| ${x.strategy} | ${x.matches} | ${x.how || '-'} | ${x.node || '-'} | ${x.outcome}${x.note ? ' (' + x.note + ')' : ''} | ${d ? (d.urlChanged ? '변함' : '같음') : '-'} | ${d ? d.nodesAdded + '/' + d.nodesRemoved : '-'} | ${d ? d.netDelta : '-'} |`;
  });
  return `**탐침 「${r.spec.name}」 판정 ${r.verdict}** (방식 ${r.rows.length}개 시도)\n\n${head}\n${lines.join('\n')}\n`;
}

module.exports = { probe, probeAbsent, toMarkdown, STRATEGIES };
