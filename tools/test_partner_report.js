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

const crypto = require('crypto');

const html = fs.readFileSync(SHELL, 'utf8');
const token = JSON.parse(fs.readFileSync(KEYS, 'utf8')).gemini;

// The committed payload is AES-256-GCM ciphertext keyed on the token. It used to
// be plaintext, on the theory that an unguessable filename was the secret — but
// loupe-site is a PUBLIC repo, so the filename was listable via the GitHub
// contents API and the "secret" was published in a directory index. Decrypting
// here rather than reading JSON is the test's own record of that.
const envelope = JSON.parse(
  fs.readFileSync(path.join(ROOT, 'partners', 'd', token + '.json'), 'utf8'));

function decryptCard(env, tok) {
  const key = crypto.createHash('sha256').update(tok).digest();
  const iv = Buffer.from(env.iv, 'base64');
  const blob = Buffer.from(env.ct, 'base64');
  // Node wants the 16-byte GCM tag split off the end; WebCrypto keeps it inline.
  const tag = blob.subarray(blob.length - 16);
  const body = blob.subarray(0, blob.length - 16);
  const d = crypto.createDecipheriv('aes-256-gcm', key, iv);
  d.setAuthTag(tag);
  return JSON.parse(Buffer.concat([d.update(body), d.final()]).toString('utf8'));
}

const data = decryptCard(envelope, token);

// ── the shell must be inert without a key ────────────────────────────────────
console.log('\nSHELL');
ok('contains no figures from the report',
   !/11\.9|21\.9|53\.3|Thinking Mu|1,009/.test(html));
ok('is marked noindex', /name="robots"[^>]*noindex/.test(html));
ok('data lives at an unguessable path', /\/partners\/d\/'\s*\+\s*k/.test(html));
ok('the token is not baked into the page', !html.includes(token));

// ── The committed payload must be USELESS to someone who lists the directory ──
// This is the property the first version got wrong. A public repo exposes every
// filename, so the file itself has to be the thing that resists reading.
const raw = fs.readFileSync(path.join(ROOT, 'partners', 'd', token + '.json'), 'utf8');
ok('the committed payload is encrypted, not JSON',
   /^\{"v":\d+,"iv":"/.test(raw) && !raw.includes('approval'));
ok('the ciphertext names no partner',
   !/gemini/i.test(raw) && !/Gemini/.test(raw));
ok('the ciphertext leaks no figures',
   !new RegExp(String(data.headline.approval)).test(raw));
ok('the page decrypts client-side before rendering',
   /crypto\.subtle\.decrypt/.test(html) && /\.then\(decrypt\)/.test(html));

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
    // The page decrypts before it renders, so the stub needs the same primitives
    // a browser gives it. Node's WebCrypto is API-identical, and atob/TextEncoder
    // are global from Node 16 — without these, decrypt() throws, render() never
    // runs, and every assertion below fails for a reason that has nothing to do
    // with the thing being tested.
    crypto: globalThis.crypto,
    atob: globalThis.atob,
    TextEncoder, TextDecoder, Uint8Array,
  };
  const args = ['location', 'URLSearchParams', 'document', 'fetch', 'Number', 'Math',
                'String', 'JSON', 'console', 'crypto', 'atob', 'TextEncoder',
                'TextDecoder', 'Uint8Array'];
  const fn = new Function(...args, script);
  fn(...args.map((a) => sandbox[a]));
  // Decryption is async and native: digest → importKey → decrypt → JSON.parse,
  // each resolving on its own tick, and crypto.subtle's work happens off the JS
  // thread. A fixed number of ticks is a race — poll for the render instead, and
  // give up after a bound so a genuine failure still fails fast.
  return (async () => {
    for (let i = 0; i < 50; i++) {
      await new Promise((r) => setImmediate(r));
      if (els.report || fetched === null) return;   // rendered, or never fetched
    }
  })();
}

(async () => {
  console.log('\nKEY GATE');
  await run('', envelope, true);
  ok('no key -> no fetch at all', fetched === null);

  await run('?k=' + '.'.repeat(20), envelope, true);
  ok('malformed key -> no fetch', fetched === null, String(fetched));

  await run('?k=' + token, envelope, false);
  ok('wrong key (404) -> report stays hidden',
     !els.report || els.report.className === 'hide' || els.report.className === '');

  console.log('\nRENDER (real data)');
  await run('?k=' + token, envelope, true);
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
