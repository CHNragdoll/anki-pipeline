/* Decorate original DOM; original viewer remains the disclosure authority. */
(() => {
  let memorySequence = 0;
  function highlightMemory(line, word) {
    if (!word) return;
    const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp('\\b' + escaped + '\\b', 'gi');
    const walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) if (!walker.currentNode.parentElement.closest('.key,a')) nodes.push(walker.currentNode);
    for (const node of nodes) {
      let rest = node, match;
      while ((match = pattern.exec(rest.data))) {
        const keyText = rest.splitText(match.index);
        rest = keyText.splitText(match[0].length);
        const key = document.createElement('span');
        key.className = 'cigen-memory-key';
        keyText.replaceWith(key); key.append(keyText);
        pattern.lastIndex = 0;
      }
      pattern.lastIndex = 0;
    }
  }
  function decorateMemoryEntry(entry, index) {
    const lines = [...entry.children], groups = [];
    const heading = entry.querySelector('.cigen-memory-headword');
    const word = heading?.textContent.trim() || document.title;
    for (let i = 0; i < lines.length; i++) {
      const item = lines[i], next = lines[i + 1];
      if (item.classList.contains('cigen-memory-pos') && next &&
          !next.matches('.cigen-memory-headword,.cigen-memory-pos,.cigen-memory-english,.cigen-memory-translation,.cigen-memory-gap')) {
        const definition = document.createElement('div');
        definition.className = 'cigen-memory-definition';
        item.before(definition); definition.append(item, next); i++;
      } else if (item.classList.contains('cigen-memory-english')) {
        const sentence = document.createElement('div');
        sentence.className = 'cigen-memory-sentence';
        sentence.id = 'cigen-memory-sentence-' + (++memorySequence);
        item.before(sentence); sentence.append(item);
        if (next?.classList.contains('cigen-memory-translation')) { sentence.append(next); i++; }
        highlightMemory(item, word); groups.push(sentence);
      }
    }
    const toggle = heading || document.createElement('div');
    toggle.classList.add('cigen-memory-toggle');
    if (!heading) { toggle.classList.add('cigen-memory-icon-only'); entry.prepend(toggle); }
    if (!groups.length) return;
    toggle.setAttribute('role', 'button'); toggle.setAttribute('tabindex', '0');
    toggle.setAttribute('aria-label', (word || '词根记忆') + '例句');
    toggle.setAttribute('aria-controls', groups.map(group => group.id).join(' '));
    const setOpen = open => {
      toggle.setAttribute('aria-expanded', String(open));
      for (const group of groups) group.hidden = !open;
    };
    setOpen(index === 0);
    toggle.addEventListener('click', event => {
      if (!event.target.closest('a')) setOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });
    toggle.addEventListener('keydown', event => {
      if (event.target === toggle && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault(); setOpen(toggle.getAttribute('aria-expanded') !== 'true');
      }
    });
  }
  // Older memory entries use inline font nodes and BRs instead of sentenceInfo.
  // Move their original nodes into display wrappers; keep text, links and order.
  function decorateMemory(section) {
    if (section.querySelector('.sectionHead')?.textContent.trim() !== '词根记忆') return;
    section.classList.add('cigen-memory-section');
    for (const row of section.querySelectorAll(':scope > .sectionCont > .sameRoot')) {
      if (row.dataset.cigenMemory === 'styled' || row.querySelector('.nameBox,.sentenceInfo')) continue;
      if ([...row.querySelectorAll('*')].some(node => !['FONT','BR','SPAN','A','B','STRONG','EM','I'].includes(node.tagName))) continue;
      const lines = [];
      let line = document.createElement('div');
      line.className = 'cigen-memory-line';
      for (const node of [...row.childNodes]) {
        line.append(node);
        if (node.nodeName === 'BR') {
          lines.push(line);
          line = document.createElement('div');
          line.className = 'cigen-memory-line';
        }
      }
      if (line.childNodes.length) lines.push(line);
      let entry, previousEnglish = false;
      for (const item of lines) {
        const text = item.textContent.trim();
        const name = item.querySelector('font.redbook-source-color,font[color]');
        const isName = name && name.textContent.trim() === text && /^[A-Za-z][A-Za-z '\-/()]*$/.test(text);
        if (!entry || isName) {
          entry = document.createElement('div');
          entry.className = 'cigen-memory-entry';
          row.append(entry);
        }
        if (isName) item.classList.add('cigen-memory-headword');
        else if (/^(?:n|v|vi|vt|adj|adv|a|ad|pron|prep|conj|interj|num|art|aux|modal)\.$/i.test(text)) item.classList.add('cigen-memory-pos');
        else if (previousEnglish && /[\u3400-\u9fff]/.test(text)) item.classList.add('cigen-memory-translation');
        else if (!/[\u3400-\u9fff]/.test(text) && /[.!?]$/.test(text) && (text.match(/[A-Za-z]+/g) || []).length >= 4) item.classList.add('cigen-memory-english');
        if (!text) item.classList.add('cigen-memory-gap');
        previousEnglish = item.classList.contains('cigen-memory-english');
        entry.append(item);
      }
      row.dataset.cigenMemory = 'styled';
      [...row.children].forEach(decorateMemoryEntry);
    }
  }
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.data?.type !== 'cigen:theme') return;
    for (const [name, value] of Object.entries(event.data.metrics || {})) {
      if (!/^--ety-[a-z-]+$/.test(name) || typeof value !== 'string' || value.length > 160) continue;
      if (document.documentElement.style.getPropertyValue(name) !== value) document.documentElement.style.setProperty(name, value);
    }
  });
  for (const root of document.querySelectorAll('.etymology')) {
    for (const section of root.querySelectorAll('.wordSection')) decorateMemory(section);
    const header = document.createElement('header');
    header.className = 'cigen-card-ety-header';
    const title = document.createElement('h3');
    title.textContent = '词根与词源';
    header.append(title);
    const disclosures = [...root.querySelectorAll('.nameBox[role="button"],.cigen-memory-toggle[role="button"]')];
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
