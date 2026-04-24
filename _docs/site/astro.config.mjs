import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { remarkMermaid } from './src/plugins/remark-mermaid.mjs';

export default defineConfig({
  base: '/nixos',
  markdown: {
    remarkPlugins: [remarkMermaid],
  },
  integrations: [
    starlight({
      title: 'NixOS 모듈형 설정 프레임워크',
      social: {
        github: 'https://github.com/donghans/nixos',
      },
      customCss: ['./src/styles/custom.css'],
      head: [
        {
          tag: 'script',
          attrs: { type: 'module' },
          content: `
            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';

            const isDark = () => document.documentElement.dataset.theme === 'dark';
            const mermaidTheme = () => isDark() ? 'dark' : 'neutral';
            const modalBg = () => isDark() ? '#24273a' : '#ffffff';

            const PALETTES = {
              dark: {
                blue:      'fill:#1e2a3a,stroke:#4a9eff,color:#cdd6f4',
                blueDim:   'fill:#152030,stroke:#2a6acc,color:#cdd6f4',
                green:     'fill:#1a2a1a,stroke:#4aff7a,color:#cdd6f4',
                greenDim:  'fill:#112211,stroke:#2acc44,color:#cdd6f4',
                purple:    'fill:#2a1e2a,stroke:#c97bff,color:#cdd6f4',
                purpleDim: 'fill:#201222,stroke:#9955cc,color:#cdd6f4',
                red:       'fill:#2a1a1a,stroke:#ff7b7b,color:#cdd6f4',
                redDim:    'fill:#201212,stroke:#cc4444,color:#cdd6f4',
                yellow:    'fill:#2a2a1a,stroke:#ffcc4a,color:#cdd6f4',
                yellowDim: 'fill:#2d2d20,stroke:#f9e2af,color:#cdd6f4',
                teal:      'fill:#1e3a2a,stroke:#a6e3a1,color:#cdd6f4',
                neutral:   'fill:#313244,stroke:#89b4fa,color:#cdd6f4',
              },
              light: {
                blue:      'fill:#dbeafe,stroke:#1d4ed8,color:#1e3a5f',
                blueDim:   'fill:#bfdbfe,stroke:#1e40af,color:#1e3a5f',
                green:     'fill:#dcfce7,stroke:#16a34a,color:#14532d',
                greenDim:  'fill:#bbf7d0,stroke:#15803d,color:#14532d',
                purple:    'fill:#f3e8ff,stroke:#7c3aed,color:#3b0764',
                purpleDim: 'fill:#e9d5ff,stroke:#6d28d9,color:#3b0764',
                red:       'fill:#fee2e2,stroke:#dc2626,color:#7f1d1d',
                redDim:    'fill:#fecaca,stroke:#b91c1c,color:#7f1d1d',
                yellow:    'fill:#fef9c3,stroke:#ca8a04,color:#713f12',
                yellowDim: 'fill:#fefce8,stroke:#b45309,color:#451a03',
                teal:      'fill:#d1fae5,stroke:#059669,color:#064e3b',
                neutral:   'fill:#e0e7ff,stroke:#4338ca,color:#1e1b4b',
              }
            };

            const NODE_ROLES = {
              L1:'blue', L2:'purple', L3:'green', L4:'red',
              SCAN:'blue', DUAL:'purple', HELPER:'green', ENABLE:'yellow', APPLY:'red',
              ORC:'blue', ORC_A:'blueDim', ORC_B:'blueDim',
              EVL:'green', EVL_A:'greenDim', EVL_B:'greenDim',
              EXP:'purple', EXP_A:'purpleDim', EXP_B:'purpleDim',
              APP:'red', APP_A:'redDim', APP_B:'redDim',
              P1:'blue', P1A:'blueDim', P1B:'blueDim', P1C:'blueDim',
              P2:'red', P2A:'redDim', P2B:'redDim', P2C:'redDim',
              Out:'teal', Done:'teal',
              User:'neutral', Entry:'neutral',
              LoadParams:'yellowDim', RepoCheck:'yellowDim', AskParts:'yellowDim',
            };

            function injectStyles(source, theme) {
              const p = PALETTES[theme];
              const words = new Set(source.split(/[^\\w]+/));
              const lines = Object.entries(NODE_ROLES)
                .filter(([node]) => words.has(node))
                .map(([node, role]) => '  style ' + node + ' ' + p[role]);
              return lines.length ? source + '\\n' + lines.join('\\n') : source;
            }

            async function renderInto(wrapper, source) {
              const theme = mermaidTheme();
              mermaid.initialize({ startOnLoad: false, theme, flowchart: { curve: 'basis' } });
              const id = 'mmd-' + Math.random().toString(36).slice(2);
              const palette = isDark() ? 'dark' : 'light';
              const { svg } = await mermaid.render(id, injectStyles(source, palette));
              wrapper.innerHTML = svg;
            }

            function attachZoom(wrapper) {
              wrapper.style.cursor = 'zoom-in';
              wrapper.addEventListener('click', () => {
                const svg = wrapper.querySelector('svg');
                if (!svg) return;
                const overlay = document.createElement('div');
                overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;overflow:auto;padding:2rem';
                const clone = svg.cloneNode(true);
                clone.style.cssText = \`max-width:90vw;max-height:90vh;background:\${modalBg()};border-radius:8px;padding:1.5rem;cursor:zoom-out\`;
                clone.removeAttribute('width');
                clone.removeAttribute('height');
                overlay.appendChild(clone);
                overlay.addEventListener('click', () => overlay.remove());
                document.body.appendChild(overlay);
              });
            }

            // 초기 렌더링
            for (const pre of document.querySelectorAll('pre.mermaid')) {
              try {
                const source = pre.textContent.trim();
                const wrapper = document.createElement('div');
                wrapper.dataset.mermaidSrc = source;
                wrapper.style.textAlign = 'center';
                pre.replaceWith(wrapper);
                await renderInto(wrapper, source);
                attachZoom(wrapper);
              } catch(e) { console.error('mermaid error', e); }
            }

            // 테마 변경 시 재렌더링
            new MutationObserver(async () => {
              for (const wrapper of document.querySelectorAll('[data-mermaid-src]')) {
                try {
                  await renderInto(wrapper, wrapper.dataset.mermaidSrc);
                } catch(e) { console.error('mermaid re-render error', e); }
              }
            }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
          `,
        },
      ],
      sidebar: [
        {
          label: '튜토리얼',
          items: [
            { label: '첫 번째 호스트 설정', link: 'tutorials/first-install' },
          ],
        },
        {
          label: '작업 가이드',
          items: [
            { label: '시스템 관리', link: 'how-to/manage-system' },
            { label: 'Mod 만들기', link: 'how-to/create-mod' },
          ],
        },
        {
          label: '레퍼런스',
          items: [
            { label: 'nixup 명령어', link: 'reference/nixup-commands' },
            { label: 'Mod API', link: 'reference/mod-api' },
          ],
        },
        {
          label: '이해하기',
          items: [
            { label: '아키텍처와 설계 결정', link: 'explanation/architecture' },
            { label: '내부 원리', link: 'explanation/internals' },
            { label: '실행 라이프사이클', link: 'explanation/lifecycle' },
          ],
        },
      ],
    }),
  ],
});
