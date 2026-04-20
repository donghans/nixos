(function () {
    'use strict';

    function init() {
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

        /* ── 각 mermaid 컨테이너에 클릭 핸들러 부착 ── */
        document.querySelectorAll('.mermaid').forEach(function (el) {
            var svg = el.querySelector('svg');
            if (!svg) return;

            el.classList.add('mz-zoomable');

            el.addEventListener('click', function () {
                var clone = svg.cloneNode(true);

                /* mdbook-mermaid가 추가하는 인라인 max-width 제거 →
                   width/height 속성 그대로 자연 크기로 렌더 */
                clone.removeAttribute('style');

                box.innerHTML = '';
                box.appendChild(clone);
                overlay.classList.add('mz-open');
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
