/* Native host only. Semantic HTML/profile are the shared producer's bytes.
 * Anki owns body/head/reviewer controls; this file owns one mount subtree. */
(function (bootstrapVersion, win, doc) {
  'use strict';
  const KEY = 'StudyCompiledNative';
  const anchor = doc.querySelector('[data-study-native-owner]');
  if (!anchor) return;
  function validateDeliveryJSON(value) {
    if (value === null || typeof value === 'boolean') return;
    if (typeof value === 'number') {
      demand(Number.isSafeInteger(value), 'native Meta JSON numbers must be safe integers');
      return;
    }
    if (typeof value === 'string') {
      for (let n = 0; n < value.length; n++) {
        const unit = value.charCodeAt(n);
        if (unit >= 0xd800 && unit <= 0xdbff) {
          const following = value.charCodeAt(++n);
          demand(following >= 0xdc00 && following <= 0xdfff, 'invalid native Meta Unicode scalar text');
        } else demand(unit < 0xdc00 || unit > 0xdfff, 'invalid native Meta Unicode scalar text');
      }
      return;
    }
    if (Array.isArray(value)) { value.forEach(validateDeliveryJSON); return; }
    demand(typeof value === 'object', 'unsupported native Meta JSON value');
    for (const [key, child] of Object.entries(value)) {
      validateDeliveryJSON(key); validateDeliveryJSON(child);
    }
  }
  function deliveryText(node) {
    const sources = node.querySelectorAll('[data-study-native-source-field]');
    const legacy = node.querySelectorAll('[data-study-native-delivery]');
    if (sources.length) {
      demand(sources.length === 1 && legacy.length === 0, 'ambiguous native delivery source');
      const source = sources[0];
      demand(source.tagName === 'TEMPLATE' && source.content, 'inert native delivery source required');
      demand(Array.from(source.content.childNodes).every(child => child.nodeType === 3),
        'native Meta delivery source must contain only text');
      const text = source.content.textContent, marker = '[[study-native-delivery:',
        opening = marker + 'v3:';
      demand(text.split(marker).length === 2 && text.includes(opening) && text.endsWith(']]'),
        'one terminal native Meta delivery token required');
      const start = text.indexOf(opening), encoded = text.slice(start + opening.length, -2);
      demand(!/[<&]/.test(text.slice(0, start)) && /^[A-Za-z0-9_-]+$/.test(encoded) && encoded.length % 4 !== 1,
        'invalid native Meta base64url token');
      const binary = win.atob(encoded.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - encoded.length % 4) % 4));
      demand(win.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') === encoded,
        'noncanonical native Meta base64url token');
      const bytes = win.Uint8Array.from(binary, character => character.charCodeAt(0));
      const decoded = new win.TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes);
      const value = JSON.parse(decoded);
      demand(value && typeof value === 'object' && !Array.isArray(value), 'native Meta JSON object required');
      validateDeliveryJSON(value);
      // The existing canonical() joins UTF-16-sorted key/value strings, so
      // integer-looking keys are never reordered by object serialization.
      demand(canonical(value) === decoded, 'noncanonical native Meta JSON');
      return decoded;
    }
    demand(legacy.length <= 1, 'ambiguous legacy native delivery');
    if (!legacy.length) return null;
    demand(legacy[0].tagName === 'SCRIPT' && legacy[0].getAttribute('type') === 'application/json',
      'invalid legacy native delivery');
    return legacy[0].textContent;
  }
  let delivery = null, invalidDelivery = false;
  try { delivery = deliveryText(anchor); } catch (_) { invalidDelivery = true; }
  if (delivery === null && !invalidDelivery) {
    if (win[KEY]?.version === bootstrapVersion) win[KEY].mount(anchor);
    return;
  }
  let selectedVersion = null;
  try { selectedVersion = JSON.parse(delivery).bootstrap_version; } catch (_) {}
  // A late script from a retired card must not downgrade the current host.
  if (selectedVersion && selectedVersion !== bootstrapVersion) return;
  let priorGeneration = 0;
  const previous = win[KEY];
  if (previous) {
    if (previous.schema !== 'study-compiled-native.v1' || typeof previous.shutdown !== 'function')
      throw Error('Native compiled: unowned native host already exists');
    if (previous.version === bootstrapVersion) { previous.mount(anchor); return; }
    // The old anchor may already have detached, so snapshot() can be null.
    if (Number.isSafeInteger(previous.generation) && previous.generation >= 0) priorGeneration = previous.generation;
    previous.shutdown();
    if (win[KEY] === previous) throw Error('Native compiled: previous host did not retire');
  }
  /*__SHARED_NATIVE_ADAPTERS__*/
  const hash = /^[a-f0-9]{64}$/, basename = /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/;
  const knownPinMatches = createKnownPinVerifier(win, async bytes => {
    if (!win.crypto || !win.crypto.subtle) throw Error('Native SHA verification unavailable');
    return Array.from(new win.Uint8Array(await win.crypto.subtle.digest('SHA-256', bytes)),
      n => n.toString(16).padStart(2, '0')).join('');
  });
  let current = null, generation = priorGeneration, modulePin = null, stopped = false, api = null;
  // One authenticated, deeply frozen base only; never retain a mount's profile
  // identity, document, owner, anchors, callbacks or raw carrier text here.
  const profileCacheLimit = 64 * 1024 * 1024;
  let profileCache = null;
  const pending = new Map(), owners = new WeakMap(), verifiedProfiles = new WeakSet(), carrierSources = new WeakMap();
  const loaderGlobals = ['AnkiSlimDecode', 'AnkiResidualReviewedChunkRuntime', 'AnkiSlimPackedDecode',
    'AnkiSlimPhysicalNativeIndex', 'AnkiSlimPanelReady', 'AnkiSlimApkgDispose', 'AnkiFinalApkgDispose',
    'AnkiSlimApkgHydrate', 'AnkiFinalApkgHydrate', '__AnkiSlimStorageVersion', 'StudySlimWarm'];
  function sameDescriptor(left, right) {
    return left === right || !!left && !!right &&
      ['value', 'writable', 'get', 'set', 'enumerable', 'configurable'].every(key => left[key] === right[key]);
  }
  function captureGlobals(owner, names, action) {
    const before = new Map(names.map(name => [name, Object.getOwnPropertyDescriptor(win, name)]));
    try { return action(); } finally {
      for (const [name, previous] of before) {
        const after = Object.getOwnPropertyDescriptor(win, name);
        if (!sameDescriptor(previous, after)) owner.globals.set(name,
          {before: owner.globals.has(name) ? owner.globals.get(name).before : previous, after});
      }
    }
  }
  function immutable(value) {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
      Object.values(value).forEach(immutable); Object.freeze(value);
    }
    return value;
  }
  function canonical(value) {
    if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
    if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key =>
      JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
    return JSON.stringify(value);
  }
  function demand(value, message) { if (!value) throw Error('Native compiled: ' + message); }
  function owns(owner) {
    return !stopped && current === owner && !owner.disposed && owner.anchor.isConnected &&
      owner.anchor.ownerDocument === doc && owner.anchor.dataset.studyNativeGeneration === String(owner.generation);
  }
  function assert(owner) { demand(owns(owner), 'expired mount owner'); }
  function register(pin, value) {
    if (stopped || !hash.test(pin) || typeof value !== 'string') return;
    const task = carrierSources.get(doc.currentScript);
    // A carrier registers synchronously in its own classic script. Never let
    // an unrelated script or a retired owner populate the current cache.
    if (!task || task.done || !owns(task.owner) || !task.pins.has(pin)) return;
    if (task.texts.has(pin) && task.texts.get(pin) !== value)
      task.finish(Error('Native local asset conflicting registration'));
    else task.texts.set(pin, value);
  }
  function load(owner, asset) {
    assert(owner);
    demand(asset && hash.test(asset.sha256 || '') && basename.test(asset.src || ''), 'local asset descriptor');
    const transport = owner.value.transport[asset.src];
    demand(transport && transport.sha256 === asset.sha256 &&
      /^_study_native_[a-f0-9]{64}\.js$/.test(transport.src), 'unregistered local asset');
    const key = owner.generation + ':' + asset.sha256;
    if (owner.loaded.has(asset.sha256)) return Promise.resolve(owner.loaded.get(asset.sha256));
    if (pending.has(key)) return pending.get(key);
    let task = owner.bundles.get(transport.src);
    if (!task) {
      const pins = new Set(Object.values(owner.value.transport).filter(item =>
        item && item.src === transport.src && hash.test(item.sha256 || '')).map(item => item.sha256));
      let resolve, reject, timer;
      const promise = new Promise((a, b) => { resolve = a; reject = b; });
      const script = doc.createElement('script'); script.src = transport.src;
      task = {owner, pins, texts: new Map(), promise, done: false, finish(error) {
        if (task.done) return; task.done = true;
        win.clearTimeout(timer); carrierSources.delete(script);
        script.onload = script.onerror = null; script.remove(); owner.tasks.delete(task);
        if (error) {
          task.texts.clear();
          if (owner.bundles.get(transport.src) === task) owner.bundles.delete(transport.src);
          reject(error);
        } else resolve(task.texts);
      }};
      owner.bundles.set(transport.src, task); owner.tasks.add(task); carrierSources.set(script, task);
      timer = win.setTimeout(() => task.finish(Error('Native local asset load timed out')), 30000);
      script.onerror = () => task.finish(Error('Native local asset unavailable: ' + asset.src));
      script.onload = () => {
        if (!owns(owner)) task.finish(Error('Native mount cancelled'));
        else if (Array.from(pins).some(pin => !task.texts.has(pin)))
          task.finish(Error('Native local asset did not register: ' + asset.src));
        else task.finish(null);
      };
      try { doc.head.append(script); } catch (error) { task.finish(error); }
    }
    const promise = task.promise.then(async texts => {
      assert(owner);
      const text = texts.get(asset.sha256);
      demand(typeof text === 'string' && await knownPinMatches(text, asset.sha256), 'local asset SHA differs');
      assert(owner); owner.loaded.set(asset.sha256, text); return text;
    }).catch(error => {
      task.texts.clear();
      if (owner.bundles.get(transport.src) === task) owner.bundles.delete(transport.src);
      throw error;
    }).finally(() => { if (pending.get(key) === promise) pending.delete(key); });
    pending.set(key, promise);
    return promise;
  }
  function execute(owner, text) {
    assert(owner);
    let failure = null;
    const listener = event => { failure = event.error || Error(event.message || 'Authored script failed'); };
    const script = doc.createElement('script'); script.textContent = text;
    win.addEventListener('error', listener);
    try { doc.head.append(script); } finally { script.remove(); win.removeEventListener('error', listener); }
    if (failure) throw failure;
    assert(owner);
  }
  function captureMedia(target) {
    const owner = owners.get(target), authorized = new Set();
    const valid = () => target === doc && owner && owns(owner) && owner.state !== 'failed';
    demand(valid(), 'expired local media owner');
    return Object.freeze({current: valid, async read(name) {
      demand(valid(), 'expired local media owner');
      const asset = owner.value.local_media[name];
      demand(asset && /^_a[scf]_[a-f0-9]{24}\.js$/.test(name), 'unregistered original local media');
      const text = await load(owner, asset);
      demand(valid(), 'expired local media owner'); authorized.add(text); return text;
    }, execute(text) {
      demand(valid() && authorized.has(text), 'unverified or expired original local script');
      execute(owner, text);
    }});
  }
  function adaptNativeMediaTransport(code) {
    const storageVersion = JSON.stringify('study-compiled-native.v1:' + bootstrapVersion);
    const edits = [
      ["  if (window.AnkiSlimApkgHydrate && window.__AnkiSlimStorageVersion === 'shared-v2') return;",
       '  if (window.AnkiSlimApkgHydrate && window.__AnkiSlimStorageVersion === ' + storageVersion + ') return;'],
      ["  window.__AnkiSlimStorageVersion = 'shared-v2';",
       '  window.__AnkiSlimStorageVersion = ' + storageVersion + ';'],
      ['  function load(part) {\n    pin(part);',
       '  function load(part, resourceOwner) {\n    pin(part);\n    var localMedia = resourceOwner || window.StudyCompiledNative.captureMedia(document);\n    if (!localMedia.current()) throw Error("Expired native media owner");'],
      ["      function attempt(name, fallback) {\n        if (script) script.remove();\n        script = document.createElement('script'); script.src = name;\n        script.onload = function () { end(); };\n        script.onerror = function () {\n          // Old and new packages may share a profile. Keep the old filenames\n          // intact and use a fresh script element for an actual failed-load retry.\n          if (fallback) attempt(part.src, false);\n          else end(Error('本地片段媒体无法载入'));\n        };\n        document.head.append(script);\n      }",
       '      function attempt(name, fallback) {\n        localMedia.read(name).then(function (source) {\n          localMedia.execute(source); end();\n        }).catch(function (error) { if (fallback) attempt(part.src, false); else end(error); });\n      }'],
      ['raw = await window.AnkiSlimPackedDecode(raw, load);',
       'raw = await window.AnkiSlimPackedDecode(raw, function (info) { return load(info, localMedia); });'],
      ["if (typeof (window.AnkiFinalHistoryEvidence || {})[proof] !== 'string') await new Promise(function (resolve, reject) {\n          var script = document.createElement('script'); script.src = name;\n          script.onload = function () { script.remove(); resolve(); }; script.onerror = function () { script.remove(); reject(Error('本地证据媒体无法载入')); }; document.head.append(script);\n        });",
       "if (typeof (window.AnkiFinalHistoryEvidence || {})[proof] !== 'string') {\n          var localMedia = window.StudyCompiledNative.captureMedia(document);\n          var historySource = await localMedia.read(name); localMedia.execute(historySource);\n        }"]
    ];
    demand(edits.every(([before]) => code.split(before).length === 2), 'audited native media transport boundary differs');
    for (const [before, after] of edits) code = code.replace(before, after);
    return code;
  }
  function dispose(owner = current) {
    if (!owner || owner.disposed) return;
    owner.disposed = true;
    for (const task of Array.from(owner.tasks)) task.finish(Error('Native mount cancelled'));
    owner.loaded.clear();
    for (const task of owner.bundles.values()) task.texts.clear();
    owner.bundles.clear();
    if (owners.get(doc) === owner) owners.delete(doc);
    if (current !== owner) return;
    current = null;
    // Original Slim's disposer also uses shared generation/handle globals. A
    // later plain author already called it before installing its own loader;
    // calling it again here would cancel the new author's active card.
    const ownLoader = owner.nativeHydrate && win.AnkiSlimApkgHydrate === owner.nativeHydrate &&
      win.AnkiSlimApkgDispose === owner.nativeDispose;
    if (win[KEY] === api && ownLoader) {
      try { owner.nativeDispose(); } catch (_) {}
    }
    if (owner.countdownDispose && win.__ankiExamCountdownCleanup === owner.countdownDispose) {
      try { owner.countdownDispose(); } catch (_) {}
    }
    // If a new plain loader has taken over, shared codec definitions may have
    // been adopted through its original guards. Preserve those and its media
    // registries; only a still-owned compiled cohort can restore its baseline.
    if (ownLoader) for (const [name, binding] of owner.globals) {
      if (sameDescriptor(Object.getOwnPropertyDescriptor(win, name), binding.after)) {
        if (binding.before) Object.defineProperty(win, name, binding.before);
        else delete win[name];
      }
    }
    owner.globals.clear(); modulePin = null;
    for (const audio of owner.anchor.querySelectorAll('audio,video')) try { audio.pause(); } catch (_) {}
    for (const node of owner.headNodes) node.remove();
    owner.headNodes.length = 0;
  }
  function fail(owner, error) {
    if (!owns(owner)) return;
    profileCache = null;
    owner.state = 'failed'; owner.anchor.dataset.studyNativeState = 'failed';
    // Preserve the authenticated card if an interaction fails; a load failure
    // retains the explicit status instead of revealing an older card.
    let status = owner.anchor.querySelector('[data-study-native-status]');
    if (!status) { status = doc.createElement('p'); status.dataset.studyNativeStatus = ''; owner.anchor.prepend(status); }
    status.hidden = false; status.setAttribute('role', 'alert');
    status.textContent = '完整卡片无法校验：' + String(error.message || error);
    owners.delete(doc);
  }
  if ('StudyCompiledProfileBridge' in win) throw Error('Native compiled owner bridge already exists');
  const bridge = Object.freeze({
    get(target) { const owner = owners.get(target); return owner && owns(owner) ? owner.profile : null; },
    isCurrent(target, profile) { const owner = owners.get(target); return target === doc && !!owner && owns(owner) && owner.profile === profile; }
  });
  Object.defineProperty(win, 'StudyCompiledProfileBridge', {value: bridge, configurable: true, writable: false});
  async function prepare(owner) {
    const value = owner.value, entry = value.entry;
    const [packetRaw, policyRaw] = await Promise.all([load(owner, value.packet), load(owner, value.policy)]);
    assert(owner);
    const packet = JSON.parse(packetRaw), policy = JSON.parse(policyRaw);
    let html = null, profile = null, runtime = null;
    if (owner.answer) {
      const values = await Promise.all([load(owner, entry.html), load(owner, entry.profile), load(owner, value.runtime)]);
      assert(owner);
      [html, , runtime] = values;
      const raw = values[1], base = profileCache && profileCache.id === value.id && profileCache.pin === entry.profile.sha256 ?
        profileCache.base : JSON.parse(raw);
      demand(base.schema === 'study-compiled-card-interactions.v1' && base.version === 1 &&
        canonical(base.bindings) === canonical(entry.anchors.bindings), 'profile metadata binding');
      immutable(base);
      // Owner identity must never recur: a previously captured reader must not
      // accept an old top-level profile after returning to this same note.
      profile = Object.freeze({...base}); verifiedProfiles.add(profile);
      profileCache = raw.length <= profileCacheLimit ? {id: value.id, pin: entry.profile.sha256, base} : null;
    }
    owner.profile = profile;
    const source = owner.answer ? html : packet.front.html;
    if (!owner.answer) demand(await knownPinMatches(source, packet.front.proof.expanded_sha256), 'front source SHA');
    assert(owner);
    const parsed = new win.DOMParser().parseFromString(source, 'text/html');
    demand(!parsed.querySelector('[autoplay],noscript'), 'unsupported authored startup mode');
    const scripts = [];
    for (const node of Array.from(parsed.scripts)) {
      const type = (node.getAttribute('type') || '').trim().toLowerCase();
      if (['application/json', 'application/ld+json'].includes(type)) continue;
      demand(['', 'text/javascript', 'application/javascript'].includes(type) &&
        !['async', 'defer', 'nomodule'].some(name => node.hasAttribute(name)), 'unaudited script mode');
      let code, pin;
      const src = node.getAttribute('src');
      if (src) {
        pin = policy.external[src]; demand(hash.test(pin || ''), 'unknown authored resource');
        if (packet.modules[pin]) code = null;
        else code = await load(owner, {src, sha256: pin});
      } else {
        code = node.textContent;
        const rule = policy.inline.find(item => item.source === code);
        demand(rule || !code.trim(), 'unknown authored inline script');
        pin = rule?.sha256 || '';
        if (rule) demand(await knownPinMatches(code, pin), 'authored inline SHA');
      }
      assert(owner); node.type = 'application/x-study-inert'; scripts.push({node, code, pin});
    }
    for (const link of parsed.querySelectorAll('link[rel~="stylesheet"][href]')) {
      const src = link.getAttribute('href'), asset = value.styles?.[src];
      demand(asset, 'stylesheet has no explicit local binding');
      const css = await load(owner, asset);
      demand(!/@import\b|<\/style/i.test(css), 'unsupported stylesheet dependency');
      const style = parsed.createElement('style'); style.textContent = css; link.replaceWith(style);
    }
    const children = owner.answer ? packet.back_children : packet.front.children;
    const frames = Array.from(parsed.querySelectorAll('iframe.etymology-source-frame'));
    demand(frames.length === children.length, 'child source census');
    for (let n = 0; n < frames.length; n++) {
      const child = children[n];
      demand(await knownPinMatches(child.html, child.html_sha256), 'child source SHA');
      // The child keeps its exact authored code, with only the native media base.
      const base = '<base href="' + doc.baseURI.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '">';
      const text = /<base\b/i.test(child.html) ? child.html.replace(/<base\b[^>]*>/i, base) :
        child.html.replace(/<head(?:\s[^>]*)?>/i, match => match + base);
      frames[n].setAttribute('srcdoc', text); frames[n].removeAttribute('data-web-etymology-srcdoc');
    }
    const loader = packet.modules[entry.module.original_sha256];
    demand(loader && loader.module_sha256 === entry.module.sha256, 'native loader provenance');
    let loaderSource = await load(owner, loader);
    loaderSource = adaptNativeMediaTransport(adaptCompiledHistorySlotsOwner(loaderSource, loader.original_sha256));
    assert(owner);
    // Definition-only installation; no authored hydrate call has executed yet.
    if (modulePin !== loader.sha256) {
      captureGlobals(owner, loaderGlobals, () => {
        win.AnkiSlimApkgDispose?.();
        win.AnkiSlimApkgHydrate = null; win.__AnkiSlimStorageVersion = null;
        execute(owner, loaderSource);
      });
      modulePin = loader.sha256;
    }
    owner.nativeHydrate = win.AnkiSlimApkgHydrate; owner.nativeDispose = win.AnkiSlimApkgDispose;
    if (owner.answer) {
      const name = '__studyCompiledFrozenProfileCapture';
      const read = (target, input) => {
        const active = owners.get(target);
        return active && owns(active) && active.profile === input && verifiedProfiles.has(input) ? input : null;
      };
      const capture = () => read;
      let installed = false;
      try {
        if (!(name in win)) {
          Object.defineProperty(win, name, {value: capture, configurable: true}); installed = true;
        }
        captureGlobals(owner, ['AnkiCompiledCardRuntime'], () =>
          execute(owner, installed ? adaptCompiledFrozenProfile(runtime, value.runtime.sha256) : runtime));
      } finally {
        if (installed && Object.getOwnPropertyDescriptor(win, name)?.value === capture) delete win[name];
      }
      demand(win.AnkiCompiledCardRuntime?.schema === profile.schema &&
        win.AnkiCompiledCardRuntime?.version === profile.version, 'binder version');
    }
    assert(owner);
    const fragment = doc.createDocumentFragment();
    for (const node of Array.from(parsed.body.childNodes)) fragment.append(doc.adoptNode(node));
    // Preserve Anki head/body attributes, #qa and its scoring/bridge siblings.
    for (const node of Array.from(parsed.head.childNodes)) {
      if (node.nodeType === 1 && node.tagName === 'STYLE') {
        const adopted = doc.adoptNode(node); doc.head.append(adopted); owner.headNodes.push(adopted);
      }
    }
    owner.anchor.replaceChildren(fragment);
    owner.payload = owner.answer ? owner.anchor.querySelector('script.anki-final-reviewed-data') : null;
    owners.set(doc, owner); // Must precede every authored native hydrate call.
    captureGlobals(owner, ['__ankiSlimManualRefresh', '__ankiExamCountdownCleanup'], () => {
      for (const item of scripts) {
        assert(owner);
        if (item.code !== null) execute(owner, adaptAuthoredCompactClassScan(item.code, item.pin));
        item.node.remove();
      }
    });
    owner.countdownDispose = owner.globals.get('__ankiExamCountdownCleanup')?.after?.value;
    assert(owner);
    if (owner.answer) {
      // The original init scripts already start hydrate; awaiting the same
      // payload's state neither starts a second install nor fabricates ready.
      const payload = owner.payload;
      demand(payload, 'compiled back has no original native payload');
      const end = Date.now() + 30000;
      while (owns(owner) && payload.dataset.nativeState !== 'ready') {
        demand(payload.dataset.nativeState !== 'failed' && Date.now() < end, 'native compiled hydration failed');
        await new Promise(resolve => win.setTimeout(resolve, 1));
      }
    }
    assert(owner); owner.state = 'ready'; owner.anchor.dataset.studyNativeState = 'ready';
    return {id: value.id, generation: owner.generation, answer: owner.answer, ready: true};
  }
  function mount(node) {
    if (stopped) return Promise.resolve(null);
    if (current?.anchor === node && owns(current)) return current.ready;
    dispose();
    const owner = {anchor: node, generation: ++generation, disposed: false,
      answer: node.dataset.answer === 'true', loaded: new Map(), bundles: new Map(), tasks: new Set(), headNodes: [],
      globals: new Map(), state: 'loading'};
    current = owner; node.dataset.studyNativeGeneration = String(generation);
    owner.ready = (async () => {
      try {
        const delivery = deliveryText(node);
        demand(delivery !== null, 'missing native delivery');
        owner.value = JSON.parse(delivery);
        demand(owner.value.bootstrap_version === bootstrapVersion, 'bootstrap source version differs');
        if (profileCache && (profileCache.id !== owner.value.id ||
          profileCache.pin !== owner.value.entry?.profile?.sha256)) profileCache = null;
        return await prepare(owner);
      } catch (error) { if (owns(owner)) fail(owner, error); return null; }
    })();
    return owner.ready;
  }
  function shutdown() {
    if (stopped) return;
    profileCache = null;
    dispose(); stopped = true; observer.disconnect(); win.removeEventListener('pagehide', onPageHide);
    if (Object.getOwnPropertyDescriptor(win, 'StudyCompiledProfileBridge')?.value === bridge)
      delete win.StudyCompiledProfileBridge;
    if (Object.getOwnPropertyDescriptor(win, KEY)?.value === api) delete win[KEY];
  }
  api = Object.freeze({schema: 'study-compiled-native.v1', version: bootstrapVersion,
    get generation() { return generation; },
    register, mount, dispose, shutdown, captureMedia,
    snapshot() { return current && owns(current) ? {id: current.value?.id, generation: current.generation,
      answer: current.answer, ready: current.state === 'ready', state: current.state} : null; }});
  Object.defineProperty(win, KEY, {value: api, configurable: true, writable: false});
  const observer = new win.MutationObserver(() => {
    // A normal front/back replacement already contains the next native anchor.
    // Only an observed plain takeover retires the retained base between mounts.
    if (!doc.querySelector('[data-study-native-owner]')) profileCache = null;
    if (current && !owns(current)) dispose(current);
    else if (current?.state !== 'failed' && current?.payload?.dataset.nativeState === 'failed')
      fail(current, Error('Native compiled interaction invalidated'));
  });
  observer.observe(doc.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['data-native-state']});
  function onPageHide() { profileCache = null; dispose(); }
  win.addEventListener('pagehide', onPageHide);
  if (anchor) mount(anchor);
})
