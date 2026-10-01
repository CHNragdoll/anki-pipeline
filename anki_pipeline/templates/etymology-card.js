/* Decorate original DOM; original viewer remains the disclosure authority. */
(() => {
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.data?.type !== 'cigen:theme') return;
    for (const [name, value] of Object.entries(event.data.metrics || {})) {
      if (!/^--ety-[a-z-]+$/.test(name) || typeof value !== 'string' || value.length > 160) continue;
      if (document.documentElement.style.getPropertyValue(name) !== value) document.documentElement.style.setProperty(name, value);
    }
  });
  for (const root of document.querySelectorAll('.etymology')) {
    const header = document.createElement('header');
    header.className = 'cigen-card-ety-header';
    const title = document.createElement('h3');
    title.textContent = '词根与词源';
    header.append(title);
    const disclosures = [...root.querySelectorAll('.nameBox[role="button"]')];
    const actions = document.createElement('div');
    actions.className = 'cigen-card-ety-actions';
    actions.setAttribute('aria-label', '词根例句控制');
    for (const [label, open] of [['展开例句', true], ['收起例句', false]]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.addEventListener('click', () => {
        for (const row of disclosures) {
          if ((row.getAttribute('aria-expanded') === 'true') !== open) row.click();
        }
      });
      actions.append(button);
    }
    if (disclosures.length) header.append(actions);
    root.prepend(header);
    for (const paragraph of root.querySelectorAll('.sentenceInfo > .trans')) {
      const labels = [...paragraph.children];
      if (labels.length && labels.every(item => item.tagName === 'SPAN' && item.textContent.trim().startsWith('#'))) {
        paragraph.classList.add('cigen-card-tags');
        for (const label of labels) label.textContent = label.textContent.replace(/^\s*#\s*/, '');
      }
    }
    for (const section of root.querySelectorAll('.sameRootWord, .derivativeSec')) {
      const count = section.querySelectorAll(':scope > .sectionCont .sameRoot').length;
      if (!count) continue;
      const label = document.createElement('span');
      label.className = 'cigen-card-count';
      label.textContent = `${count} 个词`;
      section.querySelector('.sectionHead')?.append(label);
    }
  }
})();
