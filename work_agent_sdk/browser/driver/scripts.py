# Sensitive inputs such as passwords, bank cards and verification codes. autocomplete may carry a prefix, e.g. "section-x cc-number"
SENSITIVE_INPUT_SCRIPT = (
    "element => !!element && (element.type === 'password' || "
    "/(^|\\s)(cc-|one-time-code|new-password|current-password)/"
    ".test((element.getAttribute('autocomplete') || '').toLowerCase()))"
)

FOCUSED_SENSITIVE_SCRIPT = f"() => ({SENSITIVE_INPUT_SCRIPT})(document.activeElement)"

COMMON = r"""
  const SELECTOR = 'a[href],button,input:not([type=hidden]),select,textarea,summary,' +
    '[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],' +
    '[role=option],[role=switch],[role=combobox],[role=textbox],[role=searchbox],' +
    '[contenteditable=""],[contenteditable=true],[onclick]';
  const isSensitive = __SENSITIVE__;
  const isVisible = element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const clean = text => (text || '').trim().replace(/\s+/g, ' ').replace(/\[ref_/g, '［ref_');
  const labelOf = element => clean(
    element.getAttribute('aria-label') || element.innerText || element.getAttribute('placeholder') ||
    element.getAttribute('title') || element.getAttribute('alt') || element.getAttribute('name') ||
    (element.type === 'submit' ? element.value : '')
  ).slice(0, 100);
  const roleOf = element => {
    const tag = element.tagName;
    let role = element.getAttribute('role') ||
      ({A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox', SUMMARY: 'button',
        H1: 'heading', H2: 'heading', H3: 'heading', H4: 'heading', H5: 'heading', H6: 'heading',
        IMG: 'img', P: 'paragraph', LI: 'listitem', TABLE: 'table', NAV: 'navigation', FORM: 'form'})[tag];
    if (!role && tag === 'INPUT') {
      role = ['checkbox', 'radio', 'submit', 'button', 'file', 'reset', 'password'].includes(element.type)
        ? element.type : 'textbox';
    }
    if (!role) role = element.isContentEditable ? 'textbox' : tag.toLowerCase();
    return role;
  };
  const extraOf = element => {
    const tag = element.tagName;
    let extra = '';
    if (tag === 'INPUT' || tag === 'TEXTAREA') {
      if (['checkbox', 'radio'].includes(element.type)) extra = element.checked ? ' [checked]' : '';
      else if (isSensitive(element)) extra = element.value ? ' [filled]' : '';
      else if (element.type !== 'file' && element.value && !['submit', 'button'].includes(element.type))
        extra = ' value=' + JSON.stringify(clean(element.value).slice(0, 60));
    }
    if (tag === 'SELECT') {
      const options = [...element.options].slice(0, 30).map(option => clean(option.text));
      extra = ' value=' + JSON.stringify(clean((element.selectedOptions[0] || {}).text || '')) +
        ' options=' + JSON.stringify(options);
    }
    if (tag === 'A' && element.getAttribute('href')) extra += ' href=' + JSON.stringify(element.getAttribute('href').slice(0, 100));
    if (/^H[1-6]$/.test(tag)) extra += ' [level ' + tag[1] + ']';
    if (element.disabled) extra += ' [disabled]';
    return extra;
  };
  const fresh = [];
  const refOf = element => {
    let index = known.indexOf(element);
    if (index >= 0) return 'ref_' + (index + 1);
    index = fresh.indexOf(element);
    if (index < 0) { fresh.push(element); index = fresh.length - 1; }
    return 'ref_' + (known.length + index + 1);
  };
"""

READ_PAGE_SCRIPT = (
    r"""
([root, known, filter, maxDepth, maxChars]) => {
"""
    + COMMON
    + r"""
  const lines = [];
  let length = 0;
  let truncated = false;
  const push = line => {
    if (truncated) return;
    if (length + line.length > maxChars) { truncated = true; return; }
    lines.push(line);
    length += line.length + 1;
  };
  const ownText = element => clean([...element.childNodes].filter(node => node.nodeType === 3)
    .map(node => node.textContent).join(' ')).slice(0, 300);
  const walk = (element, depth) => {
    for (const child of element.children) {
      if (truncated) return;
      if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(child.tagName) || !isVisible(child)) continue;
      const interactive = child.matches(SELECTOR);
      const heading = /^H[1-6]$/.test(child.tagName);
      let printed = false;
      if (interactive) {
        push('  '.repeat(depth) + '- ' + roleOf(child) + ' ' + JSON.stringify(labelOf(child)) + extraOf(child) +
          ' [' + refOf(child) + ']');
        printed = true;
      } else if (filter !== 'interactive') {
        const text = heading ? labelOf(child) : ownText(child);
        if (text) { push('  '.repeat(depth) + '- ' + roleOf(child) + ' ' + JSON.stringify(text) + extraOf(child)); printed = true; }
      }
      if (!interactive && depth < maxDepth) walk(child, depth + (printed ? 1 : 0));
    }
  };
  walk(root || document.body, 0);
  if (truncated) lines.push('… (page content too long, truncated; read only part of it via ref, or scroll and read again)');
  return {text: lines.join('\n'), fresh};
}
"""
).replace("__SENSITIVE__", SENSITIVE_INPUT_SCRIPT)

FIND_SCRIPT = (
    r"""
([known, query]) => {
"""
    + COMMON
    + r"""
  const needle = query.trim().toLowerCase();
  const matched = [];
  const candidates = [...document.querySelectorAll(SELECTOR + ',h1,h2,h3,h4,h5,h6,label,img,p,li,td,span,div')];
  for (const element of candidates) {
    if (!needle || !isVisible(element)) continue;
    const haystack = (labelOf(element) + ' ' + (element.getAttribute('placeholder') || '') + ' ' +
      (element.getAttribute('name') || '')).toLowerCase();
    if (haystack.includes(needle)) matched.push(element);
  }
  // Exclude outer containers that contain other matching elements; keep only the innermost elements and actionable elements
  const kept = matched.filter(element => element.matches(SELECTOR) ||
    !matched.some(other => other !== element && element.contains(other)));
  const lines = kept.slice(0, 20).map(element =>
    '- ' + roleOf(element) + ' ' + JSON.stringify(labelOf(element)) + extraOf(element) + ' [' + refOf(element) + ']');
  return {text: lines.join('\n'), fresh};
}
"""
).replace("__SENSITIVE__", SENSITIVE_INPUT_SCRIPT)

PAGE_TEXT_SCRIPT = r"""
(maxChars) => {
  const text = (document.body ? document.body.innerText : '').replace(/\[ref_/g, '［ref_');
  return text.length > maxChars ? text.slice(0, maxChars) + '\n… (truncated)' : text;
}
"""

DESCRIBE_SCRIPT = r"""
(element) => {
  const absolute = url => { try { return new URL(url, location.href).href; } catch (error) { return url; } };
  const tag = element.tagName.toLowerCase();
  const type = (element.getAttribute('type') || (tag === 'button' ? 'submit' : tag === 'input' ? 'text' : '')).toLowerCase();
  const form = element.form || element.closest('form');
  const fields = form ? [...form.elements] : [];
  let submits = false;
  if (form) {
    if (tag === 'button') submits = type === 'submit';
    else if (tag === 'input') submits = ['submit', 'image'].includes(type);
  }
  const link = element.closest('a[href]');
  const text = (element.getAttribute('aria-label') || element.innerText || element.value ||
    element.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 120);
  return {
    tag,
    type,
    role: element.getAttribute('role') || '',
    text,
    href: link ? absolute(link.getAttribute('href')) : null,
    sensitive: (__SENSITIVE__)(element),
    submits,
    form: form ? {
      method: ((submits && element.getAttribute('formmethod')) || form.getAttribute('method') || 'get').toLowerCase(),
      action: absolute((submits && element.getAttribute('formaction')) || form.getAttribute('action') || location.href),
      has_password: fields.some(field => field.type === 'password'),
      has_payment: fields.some(field => /(^|\s)cc-/.test((field.getAttribute('autocomplete') || '').toLowerCase())),
    } : null,
    disabled: !!element.disabled,
  };
}
""".replace("__SENSITIVE__", SENSITIVE_INPUT_SCRIPT)

ELEMENT_AT_SCRIPT = "([x, y]) => document.elementFromPoint(x, y)"
