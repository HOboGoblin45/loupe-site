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
const allKeys = JSON.parse(fs.readFileSync(KEYS, 'utf8'));
const token = allKeys.gemini;
const CARDS = path.join(ROOT, 'partners', 'd');
const INDEX_CARDS = path.join(ROOT, 'index', 'd');
const CRYPTO_PY = path.join(ROOT, 'tools', 'card_crypto.py');

// ── the scheme, restated independently of the code under test ───────────────
// path = base64url(SHA-256("loupe-card-path:" + token))[:22]   the file's name
// key  =           SHA-256("loupe-card-key:"  + token)         what opens it
// Two DIFFERENT hashes of the token. The 2026-08-01 fix used one hash for the
// key and the token itself for the name, so a public listing of /partners/d/
// was the key, labelled. These literals are the spec; they are compared below
// against card_crypto.py and against what the shell actually ships.
const PATH_DOMAIN = 'loupe-card-path:';
const KEY_DOMAIN = 'loupe-card-key:';
const PATH_CHARS = 22;
const ENVELOPE_V = 2;
const pathOf = (tok) => crypto.createHash('sha256').update(PATH_DOMAIN + tok)
  .digest('base64url').slice(0, PATH_CHARS);
const keyOf = (tok) => crypto.createHash('sha256').update(KEY_DOMAIN + tok).digest();

// The committed payload is AES-256-GCM ciphertext. It used to be plaintext, on
// the theory that an unguessable filename was the secret — but loupe-site is a
// PUBLIC repo, so the filename was listable via the GitHub contents API and the
// "secret" was published in a directory index. Then it was ciphertext under
// SHA-256(filename), which published the key instead. Deriving the path and
// the key here, separately, from the token, is the test's own record of both.
const cardFile = path.join(CARDS, pathOf(token) + '.json');
const envelope = JSON.parse(fs.readFileSync(cardFile, 'utf8'));

function openWith(env, rawKey) {
  try {
    const iv = Buffer.from(env.iv, 'base64');
    const blob = Buffer.from(env.ct, 'base64');
    // Node wants the 16-byte GCM tag split off the end; WebCrypto keeps it inline.
    const tag = blob.subarray(blob.length - 16);
    const body = blob.subarray(0, blob.length - 16);
    const d = crypto.createDecipheriv('aes-256-gcm', rawKey, iv);
    d.setAuthTag(tag);
    return JSON.parse(Buffer.concat([d.update(body), d.final()]).toString('utf8'));
  } catch (e) { return null; }
}
function decryptCard(env, tok) {
  if (env.v !== ENVELOPE_V) throw new Error('envelope v' + env.v + ', expected v' + ENVELOPE_V);
  const out = openWith(env, keyOf(tok));
  if (!out) throw new Error('the report does not open with its own token');
  return out;
}

const data = decryptCard(envelope, token);

// ── the shell must be inert without a key ────────────────────────────────────
console.log('\nSHELL');
ok('contains no figures from the report',
   !/11\.9|21\.9|53\.3|Thinking Mu|1,009/.test(html));
ok('is marked noindex', /name="robots"[^>]*noindex/.test(html));
// The token is in the URL, so the URL must never travel: the top pieces link
// out to the partner's own store, and that click must not carry ?k=.
ok('sends no referrer (the token is in its URL)',
   /<meta name="referrer" content="no-referrer">/.test(html));
ok('the shell fetches a DERIVED path, never the token itself',
   /\/partners\/d\/'\s*\+\s*p\b/.test(html) && !/\/partners\/d\/'\s*\+\s*k\b/.test(html));
ok('the token is not baked into the page', !html.includes(token));
ok('the path-hash is not baked into the page either', !html.includes(pathOf(token)));

// ── The committed payload must be USELESS to someone who lists the directory ──
// This is the property the first version got wrong. A public repo exposes every
// filename, so the file itself has to be the thing that resists reading.
const raw = fs.readFileSync(cardFile, 'utf8');
ok('the committed payload is a v' + ENVELOPE_V + ' envelope, not JSON',
   new RegExp('^\\{"v":' + ENVELOPE_V + ',"iv":"').test(raw) && !raw.includes('approval'));
ok('the ciphertext names no partner',
   !/gemini/i.test(raw) && !/Gemini/.test(raw));
// Matched the bare number against base64 until 2026-09-04, which is a coin
// toss once the number is two digits ("12" appears in most ciphertexts). The
// leak this guards against is the JSON itself, so look for the JSON.
ok('the ciphertext leaks no figures',
   !raw.includes('"approval":' + data.headline.approval) &&
   !raw.includes('"pieces":' + data.pieces) && !raw.includes('"name":"'));
ok('the page decrypts client-side before rendering',
   /crypto\.subtle\.decrypt/.test(html) && /\.then\(decrypt\)/.test(html));

// ── THE FILENAME IS NOT THE KEY (2026-09-04) ─────────────────────────────────
// The first fix passed every check above and was still open: the file was
// named after the token and keyed on SHA-256(token). This is the audit's
// attack, against the shipped bytes of BOTH private directories.
console.log('\nTHE FILENAME IS NOT THE KEY (2026-09-04)');
const listing = [];
for (const dir of [CARDS, INDEX_CARDS]) {
  if (!fs.existsSync(dir)) continue;
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.json'))) {
    listing.push({ rel: path.relative(ROOT, path.join(dir, f)).replace(/\\/g, '/'),
                   stem: f.replace(/\.json$/, ''), body: fs.readFileSync(path.join(dir, f), 'utf8') });
  }
}
ok('both private directories were enumerated', listing.length >= 2, listing.length + ' files');
const opened = [];
for (const f of listing) {
  let env; try { env = JSON.parse(f.body); } catch (e) { env = null; }
  if (!env) continue;
  if (env.brand || env.name || env.partner) { opened.push(f.rel + ' (plaintext)'); continue; }
  const candidates = [
    crypto.createHash('sha256').update(f.stem).digest(),               // the 2026-08-01 scheme
    crypto.createHash('sha256').update(KEY_DOMAIN + f.stem).digest(),  // new derivation, fed the name
    crypto.createHash('sha256').update(PATH_DOMAIN + f.stem).digest(), // the other prefix, fed the name
    Buffer.concat([Buffer.from(f.stem), Buffer.alloc(32)]).subarray(0, 32), // the name as raw bytes
  ];
  for (const key of candidates) {
    const pt = openWith(env, key);
    if (pt) { opened.push(f.rel + ' -> ' + (pt.brand || pt.name)); break; }
  }
}
ok('(a) no filename, hashed with SHA-256 alone or any way at all, decrypts any file',
   opened.length === 0, opened.slice(0, 3).join('; '));

const pyText = fs.readFileSync(CRYPTO_PY, 'utf8');
const pyPath = (pyText.match(/^PATH_DOMAIN\s*=\s*"([^"]+)"/m) || [])[1];
const pyKey = (pyText.match(/^KEY_DOMAIN\s*=\s*"([^"]+)"/m) || [])[1];
const shellPath = (html.match(/PATH_DOMAIN\s*=\s*'([^']+)'/) || [])[1];
const shellKey = (html.match(/KEY_DOMAIN\s*=\s*'([^']+)'/) || [])[1];
ok('(b) card_crypto.py and the shell agree on the path prefix "' + PATH_DOMAIN + '"',
   pyPath === PATH_DOMAIN && shellPath === PATH_DOMAIN, pyPath + ' / ' + shellPath);
ok('(b) card_crypto.py and the shell agree on the key prefix "' + KEY_DOMAIN + '"',
   pyKey === KEY_DOMAIN && shellKey === KEY_DOMAIN, pyKey + ' / ' + shellKey);
ok('(b) the two prefixes are distinct and neither is a prefix of the other',
   PATH_DOMAIN !== KEY_DOMAIN && !PATH_DOMAIN.startsWith(KEY_DOMAIN) && !KEY_DOMAIN.startsWith(PATH_DOMAIN));
ok('(b) the shell hashes PATH_DOMAIN for the fetch path and KEY_DOMAIN for the AES key',
   /sha256\(PATH_DOMAIN \+ k\)[\s\S]*?b64url/.test(html) && /sha256\(KEY_DOMAIN \+ k\)[\s\S]*?importKey/.test(html));
ok('(b) the shell never hashes the bare token',
   !/digest\('SHA-256',\s*new TextEncoder\(\)\.encode\(k\)\)/.test(html) && !/sha256\(k\)/.test(html));

const tokens = Object.values(allKeys);
const partnerFiles = fs.readdirSync(CARDS).filter((x) => x.endsWith('.json')).map((x) => x.replace(/\.json$/, ''));
ok('(c) no committed file name equals or contains a token from keys.json',
   partnerFiles.every((s) => tokens.every((t) => s !== t && !s.includes(t) && !t.includes(s))));
ok('(c) every file in partners/d is the path-hash of exactly one token in keys.json',
   partnerFiles.length === tokens.length &&
   partnerFiles.every((s) => tokens.filter((t) => pathOf(t) === s).length === 1),
   partnerFiles.length + ' files vs ' + tokens.length + ' tokens');
ok('(c) the old token-named file is gone', !fs.existsSync(path.join(CARDS, token + '.json')));
ok('(c) SHA-256(token) — the old key — does not open the report', openWith(envelope, crypto.createHash('sha256').update(token).digest()) === null);

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
    btoa: globalThis.btoa,          // the path derivation base64url-encodes a digest
    TextEncoder, TextDecoder, Uint8Array,
  };
  const args = ['location', 'URLSearchParams', 'document', 'fetch', 'Number', 'Math',
                'String', 'JSON', 'console', 'crypto', 'atob', 'btoa', 'TextEncoder',
                'TextDecoder', 'Uint8Array'];
  const fn = new Function(...args, script);
  fn(...args.map((a) => sandbox[a]));
  // Everything after the key check is async and native: derive the path
  // (digest) → fetch → derive the key (digest → importKey) → decrypt →
  // JSON.parse, each resolving on its own tick, with crypto.subtle's work off
  // the JS thread. A fixed number of ticks is a race — poll for the render, and
  // give up after a wall-clock bound so a genuine failure still fails fast.
  // Since 2026-09-04 the fetch itself is one await deep (the path is derived
  // first), so "fetched is still null" only means "never fetched" once the
  // derivation has had time to run.
  return (async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 600) {
      await new Promise((r) => setTimeout(r, 5));
      if (els.report) return;                                   // rendered
      if (fetched === null && Date.now() - t0 > 60) return;     // never fetched
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

  // The link Gemini was sent before 2026-09-04 — a well-formed token that no
  // longer maps to a file. It must derive a path (never fetch the token as a
  // filename), meet a 404, and stop with the gate up. Dead, not broken.
  const legacy = crypto.randomBytes(16).toString('base64url');
  await run('?k=' + legacy, envelope, false);
  ok('a pre-rotation token derives a path and 404s cleanly',
     fetched === '/partners/d/' + pathOf(legacy) + '.json' && !els.report, String(fetched));
  ok('a pre-rotation token is never fetched as a filename', !String(fetched).includes(legacy));

  // The old derivation must be dead in the client, not merely unused. Serve the
  // right payload sealed the 2026-08-01 way (SHA-256(token), v1), and as a v2
  // envelope under SHA-256(token): the shell must open neither.
  const sealOld = (v) => {
    const key = crypto.createHash('sha256').update(token).digest();
    const plain = Buffer.from(JSON.stringify(data));
    const iv = crypto.createHmac('sha256', key).update(plain).digest().subarray(0, 12);
    const c = crypto.createCipheriv('aes-256-gcm', key, iv);
    const ct = Buffer.concat([c.update(plain), c.final(), c.getAuthTag()]);
    return { v, iv: iv.toString('base64'), ct: ct.toString('base64') };
  };
  await run('?k=' + token, sealOld(1), true);
  ok('a v1 envelope (the old scheme) is refused even with the right token', !els.report);
  await run('?k=' + token, sealOld(2), true);
  ok('a report keyed on the bare token does not open — the client no longer speaks that derivation',
     !els.report);

  console.log('\nRENDER (real data)');
  await run('?k=' + token, envelope, true);
  ok('fetches the DERIVED path', fetched === '/partners/d/' + pathOf(token) + '.json', String(fetched));
  ok('the token itself never appears in the request', !String(fetched).includes(token));
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
