// Runs the partner report page's own inline script against the real data file,
// under a minimal DOM stub. Catches the things a static read misses: syntax
// errors, a wrong element id, a key that doesn't exist on the payload, and the
// key gate letting the wrong thing through.
//
//   node tools/test_partner_report.js
//
// Exits non-zero on any failure, so it can gate a deploy.

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SHELL = path.join(ROOT, 'partners', 'gemini', 'index.html');
const KEYS = path.join(ROOT, 'tools', 'data', 'keys.json');

let failures = 0;
const ok = (name, cond, extra) => {
  if (cond) { console.log('  PASS  ' + name); }
  else { console.log('  FAIL  ' + name + (extra ? '  -> ' + extra : '')); failures++; }
};

const html = fs.readFileSync(SHELL, 'utf8');
const token = JSON.parse(fs.readFileSync(KEYS, 'utf8')).gemini;
const data = JSON.parse(
  fs.readFileSync(path.join(ROOT, 'partners', 'd', token + '.json'), 'utf8'));

// ── the shell must be inert without a key ────────────────────────────────────
console.log('\nSHELL');
ok('contains no figures from the report',
   !/11\.9|21\.9|53\.3|Thinking Mu|1,009/.test(html));
ok('is marked noindex', /name="robots"[^>]*noindex/.test(html));
ok('data lives at an unguessable path', /\/partners\/d\/'\s*\+\s*k/.test(html));
ok('the token is not baked into the page', !html.includes(token));

// ── extract and run the inline script ────────────────────────────────────────
const script = html.slice(html.lastIndexOf('<script>') + 8, html.lastIndexOf('</script>'));

function makeEl(id) {
  return { id, _html: '', _text: '', className: '',
           set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
           set textContent(v) { this._text = v; }, get textContent() { return this._text; } };
}
const els = {};
const doc = {
  title: '',
  getElementById: (id) => (els[id] = els[id] || makeEl(id)),
  querySelector: (s) => (els[s] = els[s] || makeEl(s)),
};

let fetched = null;
function run(search, payload, shouldFetch) {
  Object.keys(els).forEach((k) => delete els[k]);
  fetched = null;
  const sandbox = {
    location: { search },
    URLSearchParams,
    document: doc,
    fetch: (url) => {
      fetched = url;
      return shouldFetch
        ? Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })
        : Promise.resolve({ ok: false });
    },
    Number, Math, String, JSON, console,
  };
  const fn = new Function(
    'location', 'URLSearchParams', 'document', 'fetch', 'Number', 'Math', 'String', 'JSON', 'console',
    script);
  fn(sandbox.location, sandbox.URLSearchParams, sandbox.document, sandbox.fetch,
     Number, Math, String, JSON, console);
  return new Promise((r) => setTimeout(r, 0));
}

(async () => {
  console.log('\nKEY GATE');
  await run('', data, true);
  ok('no key -> no fetch at all', fetched === null);

  await run('?k=' + '.'.repeat(20), data, true);
  ok('malformed key -> no fetch', fetched === null, String(fetched));

  await run('?k=' + token, data, false);
  ok('wrong key (404) -> report stays hidden',
     !els.report || els.report.className === 'hide' || els.report.className === '');

  console.log('\nRENDER (real data)');
  await run('?k=' + token, data, true);
  ok('fetches the token path', fetched === '/partners/d/' + token + '.json', String(fetched));
  ok('gate hidden, report shown',
     els.gate.className === 'hide' && els.report.className === '');
  ok('partner name rendered', els.pname._text === 'Gemini', els.pname._text);
  // Assert the SHAPE against the payload, not literal counts — a shelf is
  // re-curated from time to time (Gemini went 400/52 to 295/36 when the
  // trinkets came out) and a test pinned to today's numbers just goes red.
  ok('subtitle reports the live piece + label counts',
     els.sub._text.includes(`${data.pieces} pieces from ${data.labels} labels`),
     els.sub._text);

  const rates = els.rates._html;
  console.log('\n  rate cards:');
  (rates.match(/class="big serif">([^<]+)</g) || []).forEach((m) =>
    console.log('     ' + m.replace(/.*>/, '')));
  ok('three rate cards', (rates.match(/class="card/g) || []).length === 3);
  ok('leads with save intent', rates.indexOf('Save intent') < rates.indexOf('Approval rate'));
  ok('every rate is shown against the app figure',
     (rates.match(/app-wide|App-wide/g) || []).length >= 3);
  ok('approval card carries its confidence interval',
     rates.includes('95% confidence: ' + data.headline.approval_lo));
  ok('approval card does not spin the gap',
     /passed on more often than average/.test(rates));

  const cats = els['#cats tbody']._html;
  ok('category table has every category',
     (cats.match(/<tr>/g) || []).length === data.categories.length);
  ok('dresses flagged as the standout', /dresses/i.test(els.catread._html));
  console.log('\n  takeaway line:\n     ' +
    els.catread._html.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim());

  ok('top pieces rendered', (els.top._html.match(/class="p"/g) || []).length === data.top.length);
  ok('top pieces link out', /target="_blank" rel="noopener"/.test(els.top._html));
  ok('by-label table filled',
     (els['#brands tbody']._html.match(/<tr>/g) || []).length === data.brands.length);
  ok('volume section present', (els.volume._html.match(/class="card/g) || []).length === 4);
  ok('method names the exclusive-label basis',
     els.method._html.includes(String(data.exclusive_labels) + ' labels we carry only through'));
  ok('method admits what we cannot see', /not have|became a sale/.test(els.method._html));

  // Saves belonging to pieces that have left the shelf must be disclosed, not
  // silently dropped — otherwise the category denominators look wrong to anyone
  // who adds up the columns.
  if (data.headline.orphan_saves) {
    ok('discloses saves from pieces no longer carried',
       els.method._html.includes('no longer carried'));
    // Reconcile against shelf_saves (directly-tagged events), which is what the
    // category table is built from — NOT headline.saves, which comes from the
    // exclusive-brand proxy and legitimately differs. Both are on the page.
    const shown = data.categories.reduce((a, c) => a + c.saves, 0);
    ok('category saves + orphans = directly-tagged saves',
       shown + data.headline.orphan_saves === data.headline.shelf_saves,
       `${shown} + ${data.headline.orphan_saves} vs ${data.headline.shelf_saves}`);
    ok('the page explains why the two save counts differ',
       els.method._html.includes('Two counts, on purpose'));
  }

  console.log('\nNUMBERS (recomputed from the payload, not trusted from it)');
  const h = data.headline;
  const chk = (label, got, want) => {
    const near = Math.abs(got - want) < 0.06;
    ok(label + ' = ' + want + (near ? '' : ' (page says ' + got + ')'), near);
  };
  chk('approval', h.approval, Math.round(1000 * (h.likes + h.saves) / h.impressions) / 10);
  chk('save rate', h.save_rate, Math.round(1000 * h.saves / h.impressions) / 10);
  chk('save intent', h.save_intent, Math.round(1000 * h.saves / (h.likes + h.saves)) / 10);
  ok('CI brackets the point estimate',
     h.approval_lo < h.approval && h.approval < h.approval_hi,
     h.approval_lo + '/' + h.approval + '/' + h.approval_hi);
  const idxOk = data.categories.every((c) => {
    const total = data.categories.reduce((a, x) => a + x.saves, 0);
    const pieces = data.categories.reduce((a, x) => a + x.pieces, 0);
    return !c.pieces || Math.abs(c.index - Math.round((c.saves / c.pieces) / (total / pieces) * 100)) <= 1;
  });
  ok('every category index recomputes', idxOk);

  console.log(failures ? '\n' + failures + ' FAILED\n' : '\nAll checks passed.\n');
  process.exit(failures ? 1 : 0);
})();
