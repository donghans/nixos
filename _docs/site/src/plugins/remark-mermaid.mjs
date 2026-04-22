// Mermaid 코드 블록을 Expressive Code 처리 전에 raw HTML로 교체
export function remarkMermaid() {
  return (tree) => {
    function walk(node, parent, index) {
      if (node.type === 'code' && node.lang === 'mermaid') {
        const escaped = node.value
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
        parent.children[index] = {
          type: 'html',
          value: `<pre class="mermaid">${escaped}</pre>`,
        };
        return;
      }
      if (node.children) {
        node.children.forEach((child, i) => walk(child, node, i));
      }
    }
    tree.children.forEach((child, i) => walk(child, tree, i));
  };
}
