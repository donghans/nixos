(function () {
    'use strict';

    /* ── 오버레이 DOM 구성 ── */
    var overlay = document.createElement('div');
    overlay.id = 'mz-overlay';

    var hint = document.createElement('div');
    hint.id = 'mz-hint';
    hint.textContent = 'ESC 또는 바깥 클릭으로 닫기';
    overlay.appendChild(hint);

    var box = document.createElement('div');
    box.id = 'mz-box';
    overlay.appendChild(box);

    document.body.appendChild(overlay);

    /* ── 닫기 ── */
    function closeOverlay() {
        overlay.classList.remove('mz-open');
        box.innerHTML = '';
    }

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay || e.target === hint) closeOverlay();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeOverlay();
    });

    /* ── 클릭 핸들러 부착 ── */
    function attachHandler(el, svg) {
        el.classList.add('mz-zoomable');
        el.addEventListener('click', function () {
            var clone = svg.cloneNode(true);
            clone.removeAttribute('style');
            box.innerHTML = '';
            box.appendChild(clone);
            overlay.classList.add('mz-open');
        });
    }

    /* ── MutationObserver: Mermaid가 SVG를 삽입하는 시점을 감지 ──
       DOMContentLoaded 이후 Mermaid.js가 비동기로 SVG를 렌더링하므로
       타이밍 경합 없이 삽입 시점을 정확히 포착한다. */
    var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (node.nodeName === 'svg') {
                    var container = node.parentElement;
                    if (container &&
                        container.classList.contains('mermaid') &&
                        !container.classList.contains('mz-zoomable')) {
                        attachHandler(container, node);
                    }
                }
            });
        });
    });

    observer.observe(document.body, { childList: true, subtree: true });

    /* ── 이미 렌더된 SVG 처리 (초기 로드 시 이미 완료된 경우 대비) ── */
    function initExisting() {
        document.querySelectorAll('.mermaid').forEach(function (el) {
            var svg = el.querySelector('svg');
            if (svg && !el.classList.contains('mz-zoomable')) {
                attachHandler(el, svg);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initExisting);
    } else {
        initExisting();
    }
})();
