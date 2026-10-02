// A small stand-in for the browser's DOM, enough for the Settings modules that build their markup
// with createElement (provider_production.js, youtube_connections.js) to run under node --test.
// It is a helper, not a test file (npm test reads tests/*.test.js only).

class FakeNode {
  /** @param {string} tag */
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = /** @type {FakeNode[]} */ ([]);
    this.parent = /** @type {FakeNode|null} */ (null);
    this.attributes = /** @type {Record<string, string>} */ ({});
    this.dataset = /** @type {Record<string, string>} */ ({});
    this.listeners = /** @type {Record<string, Function[]>} */ ({});
    this._text = '';
    this.className = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.type = '';
    this.options = /** @type {any[]} */ ([]);
  }

  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }

  set textContent(text) {
    this._text = String(text ?? '');
    this.children = [];
  }

  get isConnected() {
    return true;
  }

  /** @param {...any} items */
  append(...items) {
    for (const item of items) {
      const child = typeof item === 'string' ? Object.assign(new FakeNode('#text'), { _text: item }) : item;
      child.parent = this;
      this.children.push(child);
    }
  }

  /** @param {...any} items */
  prepend(...items) {
    const kept = this.children;
    this.children = [];
    this.append(...items);
    this.children.push(...kept);
  }

  /** @param {...any} items */
  replaceChildren(...items) {
    this.children = [];
    this.append(...items);
  }

  /** @param {string} name @param {string} value */
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  /** @param {string} name */
  getAttribute(name) {
    return name in this.attributes ? this.attributes[name] : null;
  }

  /** @param {string} type @param {Function} fn */
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }

  removeEventListener() {}

  /** @param {string} type @param {any} [event] */
  dispatch(type, event = {}) {
    const full = { preventDefault() {}, target: this, ...event };
    return Promise.all((this.listeners[type] || []).map((fn) => fn(full)));
  }

  click() {
    return this.dispatch('click');
  }

  /** for <select>: what new Option(...) made @param {any} option */
  add(option) {
    this.options.push(option);
    if (!this.value && !option.disabled) this.value = option.value;
  }
}

/** Every node under `root` (itself included) that `test` accepts. @param {FakeNode} root @param {(n: FakeNode) => boolean} test */
export function findAll(root, test) {
  const found = [];
  const walk = (/** @type {FakeNode} */ n) => {
    if (test(n)) found.push(n);
    n.children.forEach(walk);
  };
  walk(root);
  return found;
}

/** The buttons under `root` whose words are `text`. @param {FakeNode} root @param {string} text */
export function buttons(root, text) {
  return findAll(root, (n) => n.tagName === 'BUTTON' && n.textContent === text);
}

/** Installs the fake document, window and Option on globalThis; returns a host element. */
export function installDom() {
  const opened = /** @type {any[]} */ ([]);
  globalThis.document = /** @type {any} */ ({ createElement: (/** @type {string} */ tag) => new FakeNode(tag), createTextNode: (/** @type {string} */ text) => Object.assign(new FakeNode('#text'), { _text: text }) });
  globalThis.window = /** @type {any} */ ({
    location: { origin: 'http://127.0.0.1:8000', assign() {} },
    open: () => { const tab = { opener: 1, location: '', close() {} }; opened.push(tab); return tab; },
    addEventListener() {},
    removeEventListener() {},
  });
  globalThis.Option = /** @type {any} */ (function Option(/** @type {string} */ text, /** @type {string} */ value) {
    return { text, value, disabled: false };
  });
  return { host: new FakeNode('div'), opened };
}

/** Lets the module's pending promises (its first draw, a press) settle. */
export async function settle() {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}
