// Gates the Loupe Index on its honesty guarantees, not on its numbers.
//
// The Index is only worth anything if a brand can check it, so the checks here
// are the ones a sceptical reader would run: does every published rate carry a
// denominator, is every longitudinal claim confined to the stable roster, are
// the methodology artefacts actually excluded rather than merely mentioned, and
// does the private brand card really contain nothing until it is given a key.
//
// It also runs the brand card's own inline script under a DOM stub, the way
// test_partner_report.js does — that is what catches a wrong element id, a key
// that does not exist on the payload, and a gate that lets the wrong thing in.
// Here it does one more thing: the card is AES-GCM ciphertext on disk (the repo
// is public), so running the script proves the browser can actually open it.
//
//   node tools/test_loupe_index.js
//
// Exits non-zero on any failure, so it can gate a deploy.

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const PAGE = path.join(ROOT, 'index', 'index.html');
const DATA = path.join(ROOT, 'index', 'data.json');
const SHELL = path.join(ROOT, 'index', 'brand', 'index.html');
const KEYS = path.join(ROOT, 'tools', 'data', 'index_keys.json');
const CARDS = path.join(ROOT, 'index', 'd');

let failures = 0;
const ok = (name, cond, extra) => {
  if (cond) { console.log('  PASS  ' + name); }
  else { console.log('  FAIL  ' + name + (extra ? '  -> ' + extra : '')); failures++; }
};

const html = fs.readFileSync(PAGE, 'utf8');
// Prose checks run against a normalised copy. The generator wraps its source at
// 100 columns and emits &nbsp; inside statistics, so a sentence that reads as
// one line in the editor arrives here split across three with entities in it —
// and a check that fails on line wrapping is a check that gets deleted.
const prose = html.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ');
const d = JSON.parse(fs.readFileSync(DATA, 'utf8'));
const shell = fs.readFileSync(SHELL, 'utf8');
const keys = JSON.parse(fs.readFileSync(KEYS, 'utf8'));

const cardPath = (slug) => path.join(CARDS, keys[slug] + '.json');
const b64 = (s) => Uint8Array.from(Buffer.from(s, 'base64'));

// Reading a card here performs exactly what the browser performs, which makes
// the encryption path a tested one rather than a hoped-for one.
async function readCard(slug) {
  const env = JSON.parse(fs.readFileSync(cardPath(slug), 'utf8'));
  const kb = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(keys[slug]));
  const key = await crypto.subtle.importKey('raw', kb, 'AES-GCM', false, ['decrypt']);
  const buf = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(env.iv) }, key, b64(env.ct));
  return JSON.parse(new TextDecoder().decode(buf));
}

// ── the page must not have shipped a hole ────────────────────────────────────
console.log('\nPAGE INTEGRITY');
// An f-string that missed a value renders the word None into the HTML and reads
// like prose until someone notices. No type checker catches that.
['None', 'undefined', 'NaN', 'nan%', 'Infinity', '{}'].forEach((bad) =>
  ok('no "' + bad + '" leaked into the page', !html.includes(bad)));
ok('no unrendered format braces', !/\{[a-z_]+\}/.test(html.replace(/<script[\s\S]*?<\/script>/g, '')));
// Founder rule, and it is absolute: flat colours only.
ok('no gradients anywhere', !/gradient/i.test(html));
ok('canonical is set', /rel="canonical" href="https:\/\/useloupe\.shop\/index\/"/.test(html));
ok('the public page is indexable', !/noindex/.test(html));

// ── contrast, computed from the page's own variables ────────────────────────
// Measured, never eyeballed. A previous accent (#C2453F) cleared AA on paper at
// 4.70:1 and quietly failed at 4.47:1 on the pink-soft lead cards — the surface
// it appears on most. Reading the values back out of the shipped CSS is the only
// version of this check that cannot drift from what a reader actually sees.
console.log('\nCONTRAST (WCAG 2.1, from the page\'s own CSS variables)');
const V = {};
(html.match(/--[a-z-]+:#[0-9A-Fa-f]{6}/g) || []).forEach((m) => {
  const [k, v] = m.split(':'); V[k.replace('--', '')] = v;
});
const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.substr(i, 2), 16) / 255)
    .map((x) => (x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
// The three surfaces text actually sits on in this page.
[['ink', 'paper'], ['ink', 'white'], ['ink', 'pink-soft'],
 ['muted', 'paper'], ['muted', 'white'], ['muted', 'pink-soft'],
 ['accent', 'paper'], ['accent', 'white'], ['accent', 'pink-soft']].forEach(([f, b]) => {
  const r = contrast(V[f], V[b]);
  ok(f + ' on ' + b + ' clears AA (' + r.toFixed(2) + ':1)', r >= 4.5,
     V[f] + ' on ' + V[b]);
});
// Coral is below AA as text at any size and is only ever a bar fill here, next
// to a printed number. If it ever becomes text the page has a defect.
ok('coral is never used as a text colour',
   contrast(V.coral, V.paper) < 4.5 && !/color:var\(--coral\)/.test(html),
   contrast(V.coral, V.paper).toFixed(2) + ':1');

// ── every rate carries its sample ───────────────────────────────────────────
console.log('\nEVERY RATE CARRIES ITS SAMPLE');
const rates = [
  ['headline turnover', d.headline.turnover],
  ['sold out, tier', d.soldOut.tier],
  ['sold out, arrivals', d.soldOut.arrivals],
  ['sold out, standing', d.soldOut.standing],
].concat(
  d.soldOut.category.map((r) => ['sold out / ' + r.key, r]),
  d.soldOut.band.map((r) => ['sold out / ' + r.key, r]),
  d.turnover.category.map((r) => ['turnover / ' + r.key, r]),
  d.turnover.band.map((r) => ['turnover / ' + r.key, r]),
  d.turnover.colour.map((r) => ['turnover / ' + r.key, r]));

ok('every published rate has n, k and a CI',
   rates.every(([, r]) => r && r.n > 0 && r.k >= 0 && r.lo <= r.pct && r.pct <= r.hi),
   rates.filter(([, r]) => !(r && r.n > 0 && r.lo <= r.pct && r.pct <= r.hi)).map((x) => x[0]).join(', '));
ok('every published rate clears the suppression floor (n >= 150)',
   rates.every(([, r]) => r.n >= 150),
   rates.filter(([, r]) => r.n < 150).map(([nm, r]) => nm + '=' + r.n).join(', '));
ok('every rate recomputes from its own numerator/denominator',
   rates.every(([, r]) => Math.abs(r.pct - Math.round(1000 * r.k / r.n) / 10) < 0.06),
   rates.filter(([, r]) => Math.abs(r.pct - Math.round(1000 * r.k / r.n) / 10) >= 0.06)
        .map((x) => x[0]).join(', '));
ok('every rate on the page is printed next to its CI',
   (html.match(/class="ci"/g) || []).length >= rates.length - 4);

// ── longitudinal claims stay inside the stable roster ───────────────────────
console.log('\nOUR OWN DECISIONS ARE NOT THE MARKET MOVING');
ok('the roster is smaller than today\'s label count',
   d.coverage.brands_roster < d.coverage.brands_now,
   d.coverage.brands_roster + ' vs ' + d.coverage.brands_now);
ok('labels that left the roster are named on the page',
   d.coverage.left_roster.every((b) => html.includes(b)),
   d.coverage.left_roster.filter((b) => !html.includes(b)).join(', '));
ok('turnover is stated for the two-endpoint window, not as a daily rate',
   /tracked on \d{4}-\d{2}-\d{2}/.test(prose) &&
   /no longer in their brand's recent listings/.test(prose));
ok('the id-matched and title-matched turnover agree within 3 points',
   Math.abs(d.headline.turnover.pct - d.headline.turnover_by_name) < 3,
   d.headline.turnover.pct + ' vs ' + d.headline.turnover_by_name);
ok('the page publishes the title-matched cross-check too',
   html.includes(String(d.headline.turnover_by_name)));

// ── methodology steps are excluded, not just mentioned ──────────────────────
console.log('\nMETHODOLOGY CHANGES ARE EXCLUDED, NOT DESCRIBED');
const pd = d.priceDiscipline;
ok('the price window sits entirely after the epoch + settle days',
   pd.window[0] >= '2026-07-18', pd.window.join(' .. '));
ok('uniform brand-wide steps were detected at all', pd.voided_steps.length > 0);
ok('most voided steps land on an exact currency-pair ratio',
   pd.voided_fx >= Math.ceil(pd.voided_steps.length / 2),
   pd.voided_fx + ' of ' + pd.voided_steps.length);
// The one that actually burned us: Stine Goya's line moved x0.134 the day after
// its base currency was corrected from EUR to DKK. 1/7.46 is the krone peg. Any
// build reporting that as an 87% markdown is reporting our own bug as news.
const sg = pd.voided_steps.find((v) => /stine goya/i.test(v.brand));
ok('the Stine Goya krone correction is voided', !!sg && sg.ratio < 0.2,
   sg ? String(sg.ratio) : 'not found');
ok('the page names the voided days rather than hiding them',
   pd.voided_in_window.every((v) => html.includes(v.brand)),
   pd.voided_in_window.filter((v) => !html.includes(v.brand)).map((v) => v.brand).join(', '));
ok('the page admits the exclusion biases markdowns downward',
   /floor: the tier discounts at least this little/.test(prose));

// ── the caveats that make the numbers readable ──────────────────────────────
console.log('\nTHE PAGE SAYS WHAT IT CANNOT SEE');
[['the capped shelf', /up to 60 pieces per label/],
 ['"of what we track"', /of what we track/],
 ['the snapshot gap', d.gaps.length ? /did not run between/ : /window/],
 ['when stock data starts', /Stock data starts 2026-07-16/],
 ['partner listings excluded from sell-out', /Partner-boutique listings/],
 ['no units, revenue or margin', /Units, revenue, margin/],
 ['app behaviour is not used', /does not use app behaviour/],
 ['the null result is published', /r = \+0\.09/],
 ['the raw record is linked', /\/index\/data\.json/]].forEach(([name, re]) =>
   ok('discloses ' + name, re.test(prose)));

// ── nothing per-brand escapes into the public record ────────────────────────
console.log('\nTHE PUBLIC RECORD IS TIER-LEVEL ONLY');
ok('data.json carries no per-brand block', d.brands === undefined);
ok('data.json says the per-brand detail is withheld', /withheld/.test(d.brandDetail || ''));

// ── the private brand card ──────────────────────────────────────────────────
console.log('\nBRAND CARD — THE SHELL IS INERT');
const anyToken = Object.values(keys)[0];
ok('shell carries no figures', !/\d{2}\.\d%/.test(shell));
ok('shell is noindex', /name="robots"[^>]*noindex/.test(shell));
ok('data lives at an unguessable path', /\/index\/d\/'\s*\+\s*k/.test(shell));
ok('no token is baked into the shell', !shell.includes(anyToken));
ok('tokens carry real entropy',
   Object.values(keys).every((k) => k.length >= 20), 'shortest ' +
   Math.min.apply(null, Object.values(keys).map((k) => k.length)));
ok('every brand card has a distinct token',
   new Set(Object.values(keys)).size === Object.keys(keys).length);

console.log('\nBRAND CARD — THE FILE ON A PUBLIC REPO GIVES NOTHING AWAY');
const served = fs.readdirSync(CARDS).filter((f) => f.endsWith('.json'));
const raws = served.map((f) => fs.readFileSync(path.join(CARDS, f), 'utf8'));
// This is the check that matters. loupe-site is a PUBLIC repository, so every
// one of these files is browsable by anyone; unguessable filenames protect
// nothing. If a card ever ships as plaintext, a label's markdown rate is
// readable by its competitors and the card's own promise becomes a lie.
ok('every card is an AES-GCM envelope and nothing else',
   raws.every((r) => { const e = JSON.parse(r);
     return e.v === 1 && e.iv && e.ct && Object.keys(e).length === 3; }));
ok('no card file contains a brand name in the clear',
   raws.every((r) => !/[A-Za-z]{4,} [A-Za-z]{4,}/.test(r)));
ok('no card file contains a percentage in the clear', raws.every((r) => !/%/.test(r)));
ok('every envelope has its own nonce',
   new Set(raws.map((r) => JSON.parse(r).iv)).size === raws.length);

// ── run the shell's own script against a real encrypted card ────────────────
const script = shell.slice(shell.lastIndexOf('<script>') + 8, shell.lastIndexOf('</script>'));

function makeEl(id) {
  return { id, _html: '', _text: '', className: '', style: {},
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
function run(search, envelope, shouldFetch) {
  Object.keys(els).forEach((k) => delete els[k]);
  fetched = null;
  const fn = new Function(
    'location', 'URLSearchParams', 'document', 'fetch', 'crypto', 'atob',
    'TextEncoder', 'TextDecoder', 'Uint8Array', 'Number', 'Math', 'String', 'JSON', 'console',
    script);
  fn({ search }, URLSearchParams, doc, (url) => {
    fetched = url;
    return shouldFetch
      ? Promise.resolve({ ok: true, json: () => Promise.resolve(envelope) })
      : Promise.resolve({ ok: false });
  }, crypto, atob, TextEncoder, TextDecoder, Uint8Array, Number, Math, String, JSON, console);
  // Decryption is two awaits deep inside the page's promise chain, so a single
  // macrotask is not enough to see the render land.
  return new Promise((r) => setTimeout(r, 40));
}

(async () => {
  const brands = {};
  for (const slug of Object.keys(keys)) brands[slug] = await readCard(slug);

  console.log('\nBRAND CARDS — CONTENT');
  ok('a card exists for every label we measure and no other',
     served.length === Object.keys(keys).length,
     served.length + ' files vs ' + Object.keys(keys).length + ' tokens');
  ok('every card decrypted with its own token',
     Object.values(brands).every((b) => b && b.brand && b.shelf >= 20));
  ok('every card states the tier figure it is compared against',
     Object.values(brands).every((b) => b.tier && b.tier.soldout && b.tier.turnover));
  ok('every card rate carries its denominator',
     Object.values(brands).every((b) =>
       (!b.soldout || b.soldout.n >= 20) && (!b.turnover || b.turnover.n >= 20) &&
       (!b.markdown || b.markdown.n >= 20)));
  // Mackage and Marfa Stance were removed by founder decision, not by the
  // market. If either has a card, the roster filter has stopped working and 223
  // pieces of our own churn are sitting inside the headline turnover figure.
  ok('founder-removed labels have no card',
     d.coverage.founder_removed.every((b) =>
       !Object.values(brands).some((x) => x.brand.toLowerCase() === b.toLowerCase())),
     d.coverage.founder_removed.filter((b) =>
       Object.values(brands).some((x) => x.brand.toLowerCase() === b.toLowerCase())).join(', '));
  ok('a brand whose whole line was voided is not reported as 100% discounted',
     Object.values(brands).every((b) =>
       !(b.markdown && b.markdown.pct === 100 &&
         (b.voided || []).some((day) => day >= pd.window[0] && day <= pd.window[1]))));
  ok('every card that has voided days lists them',
     Object.values(brands).every((b) => !b.voided || Array.isArray(b.voided)));

  console.log('\nNOTHING UNFLATTERING IS PUBLIC');
  // The public page may name a label for holding full price, refreshing fast or
  // selling through. It must never name one for discounting hardest or for
  // publishing nothing — those live only on that label's own card.
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const worst = Object.values(brands)
    .filter((b) => b.markdown && b.markdown.cut > 0)
    .sort((a, b) => b.markdown.pct - a.markdown.pct).slice(0, 5);
  ok('the heaviest discounters are not named on the public page',
     worst.every((b) => !new RegExp('>' + esc(b.brand) + '<').test(html)),
     worst.filter((b) => new RegExp('>' + esc(b.brand) + '<').test(html))
          .map((b) => b.brand + ' ' + b.markdown.pct + '%').join(', '));
  const dormant = Object.values(brands).filter((b) => b.arrivals === 0);
  ok('labels that published nothing are not named on the public page',
     dormant.every((b) => !new RegExp('>' + esc(b.brand) + '<').test(html)),
     dormant.filter((b) => new RegExp('>' + esc(b.brand) + '<').test(html))
            .map((b) => b.brand).join(', '));
  ok('every named full-price house really cut nothing',
     pd.full_price_houses.every((name) => {
       const c = Object.values(brands).find((b) => b.brand === name);
       return !c || !c.markdown || c.markdown.cut === 0;
     }));
  ok('every label named as selling through fastest really is',
     d.sellingThrough.every((r) => {
       const c = Object.values(brands).find((b) => b.brand === r.brand);
       return !c || !c.soldout || Math.abs(c.soldout.pct - r.pct) <= 1;
     }));

  console.log('\nBRAND CARD — RUN ITS OWN SCRIPT');
  // Pick the label that exercises every optional block, so a missing key on a
  // fuller payload cannot hide behind a sparse one.
  const weight = (b) => (b.markdown ? 1 : 0) + (b.architecture.length ? 1 : 0)
    + (b.clusters.length ? 1 : 0) + (b.turnover ? 1 : 0) + (b.soldout ? 1 : 0);
  const slug = Object.keys(brands).sort((a, b) => weight(brands[b]) - weight(brands[a]))[0];
  const token = keys[slug];
  const envelope = JSON.parse(fs.readFileSync(cardPath(slug), 'utf8'));
  const payload = brands[slug];
  console.log('  using ' + payload.brand);

  await run('', envelope, true);
  ok('no key -> no fetch at all', fetched === null);

  await run('?k=' + '.'.repeat(22), envelope, true);
  ok('malformed key -> no fetch', fetched === null, String(fetched));

  await run('?k=' + token, envelope, false);
  ok('missing file (404) -> card stays hidden',
     !els.report || els.report.style.display !== '');

  // The real test of encryption at rest: a valid-looking token that is not THIS
  // card's token must fail to decrypt and leave the gate up.
  const other = Object.values(keys).find((k) => k !== token);
  await run('?k=' + other, envelope, true);
  ok('right file, wrong token -> decryption fails, card stays hidden',
     !els.report || els.report.style.display !== '');
  ok('a wrong token renders nothing at all', !els.bname || els.bname._text === '');

  await run('?k=' + token, envelope, true);
  ok('fetches the token path', fetched === '/index/d/' + token + '.json', String(fetched));
  ok('gate hidden, card shown',
     els.gate.style.display === 'none' && els.report.style.display === '');
  ok('brand name rendered', els.bname._text === payload.brand, els.bname._text);
  ok('subtitle states the tracked shelf, not the whole store',
     els.sub._text.includes(payload.shelf + ' pieces tracked'), els.sub._text);

  const cards = els.rates._html;
  console.log('\n  card values:');
  (cards.match(/class="big serif">([^<]+)</g) || []).forEach((m) =>
    console.log('     ' + m.replace(/.*>/, '').replace(/<$/, '')));
  ok('every rate card shows the tier figure beside it',
     (cards.match(/tier/gi) || []).length >= (cards.match(/class="card/g) || []).length,
     (cards.match(/tier/gi) || []).length + ' mentions for ' +
     (cards.match(/class="card/g) || []).length + ' cards');
  ok('every rate card shows its denominator',
     (cards.match(/class="card/g) || []).length ===
     (cards.match(/of (your|the) \d[\d,]* (tracked pieces|pieces)|\d[\d,]* new pieces published/g) || []).length,
     cards.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' '));
  ok('the sold-out card carries a confidence interval',
     !payload.soldout || cards.includes('95% CI on yours'));
  ok('architecture table rendered',
     (els['#arch tbody']._html.match(/<tr>/g) || []).length === payload.architecture.length);
  ok('visual-look table rendered',
     (els['#looks tbody']._html.match(/<tr>/g) || []).length === payload.clusters.length);
  ok('method explains the cap', els.method._html.includes('most recently published listings'));
  ok('method admits what we cannot see', /Units, revenue, margin or returns/.test(els.method._html));
  ok('method tells the label who else can see the card',
     /Who else can see this/.test(els.method._html) && /stored encrypted/.test(els.method._html));

  // A label whose prices we voided must be told, on its own card, why its
  // numbers look the way they do. Silence there is how a brand catches us
  // "hiding" a move they can see on their own website.
  const voidedSlug = Object.keys(brands).find((s) => brands[s].voided.length);
  if (voidedSlug) {
    await run('?k=' + keys[voidedSlug],
              JSON.parse(fs.readFileSync(cardPath(voidedSlug), 'utf8')), true);
    ok('a label with voided days is told so on its own card',
       /signature of a currency correction/.test(els.method._html), brands[voidedSlug].brand);
  }

  console.log('\nARITHMETIC (recomputed, not trusted)');
  const sd = d.soldOut;
  ok('arrivals sell out faster than standing stock, outside both CIs',
     sd.arrivals.lo > sd.standing.hi,
     sd.arrivals.pct + ' [' + sd.arrivals.lo + '-' + sd.arrivals.hi + '] vs ' +
     sd.standing.pct + ' [' + sd.standing.lo + '-' + sd.standing.hi + ']');
  ok('the page only claims that gap while it holds',
     !/New product sells out faster/.test(html) || sd.arrivals.lo > sd.standing.hi);
  const catN = d.soldOut.category.reduce((a, r) => a + r.n, 0);
  ok('category sell-out denominators sum to the tier denominator',
     Math.abs(catN - d.soldOut.tier.n) <= 5, catN + ' vs ' + d.soldOut.tier.n);
  ok('full-price share and markdown share are complements',
     Math.abs(d.headline.full_price_pct + pd.cut_pct - 100) < 0.11,
     d.headline.full_price_pct + ' + ' + pd.cut_pct);
  ok('cluster shares sum to roughly the whole shelf',
     Math.abs(d.clusters.reduce((a, c) => a + c.share, 0) - 100) < 3,
     String(d.clusters.reduce((a, c) => a + c.share, 0)));
  ok('cluster refresh indices straddle 100',
     d.clusters.some((c) => c.new_index > 100) && d.clusters.some((c) => c.new_index < 100));

  // ══ PER-BRAND POSITIONING BRIEFS (tools/build_brand_briefs.py) ═════════════
  //
  // These are the artifact a founder sends cold to twenty labels. They are
  // STAGED, not live: briefs-staging/ is gitignored, so on a clean checkout it
  // is absent and this block is skipped loudly rather than failing a deploy
  // gate for a directory that is not supposed to be in the repo.
  //
  // What is checked here is not the numbers, it is the claim boundary. A brief
  // may say three kinds of thing (flag / price-series / descriptive) and may
  // not say any of the things this project has withdrawn — turnover and
  // everything else built on a piece leaving a 60-item front, the price
  // barbell, and above all a per-piece risk score, which was fitted, tested on
  // a window it had never seen, scored 0.519 and does not exist.
  console.log('\nBRAND BRIEFS');
  const BRIEFS = path.join(ROOT, 'briefs-staging');
  const BJSON = path.join(BRIEFS, 'briefs.json');
  if (!fs.existsSync(BJSON)) {
    console.log('  SKIP  briefs-staging/ is absent (gitignored). ' +
                'Run: python tools/build_brand_briefs.py');
  } else {
    const bj = JSON.parse(fs.readFileSync(BJSON, 'utf8'));
    const BASES = ['flag', 'price-series', 'descriptive'];
    const esc2 = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    ok('the briefs declare themselves staging, not published',
       bj.staging === true && bj.published === false);
    ok('the briefs declare exactly three bases',
       JSON.stringify(bj.bases) === JSON.stringify(BASES), JSON.stringify(bj.bases));
    ok('briefs-staging is gitignored',
       /^briefs-staging\/$/m.test(fs.readFileSync(path.join(ROOT, '.gitignore'), 'utf8')));
    ok('the window does not straddle the sampling-epoch change',
       bj.tier.window_start < '2026-08-06' === bj.tier.window_end < '2026-08-06',
       bj.tier.window_start + ' .. ' + bj.tier.window_end);
    ok('the sampling depth is read off the archive, not off brands.json',
       bj.tier.observed_cap === 60,
       'archive was walked at 60/label/day; brands.json now says ' +
       (d.coverage.cap || '?'));

    const pages = {};
    bj.briefs.forEach((b) => {
      pages[b.slug] = fs.readFileSync(path.join(BRIEFS, b.file), 'utf8');
    });
    ok('every brief in the record exists on disk', Object.keys(pages).length === bj.briefs.length);
    ok('no brief file is orphaned',
       fs.readdirSync(BRIEFS).filter((f) => /^brief-.*\.html$/.test(f)).length ===
       bj.briefs.length);

    const allPages = Object.entries(pages);
    const bad = (name, pred) => {
      const hits = allPages.filter(([, h]) => pred(h)).map(([s]) => s);
      ok(name, hits.length === 0, hits.slice(0, 4).join(', ') + (hits.length > 4 ? ' …' : ''));
    };

    // The live roster walk, if the briefs were built with one. Two probe files
    // exist from 2026-08-06 twelve minutes apart and only the later one is
    // usable: the earlier got HTTP 429 from 151 of 162 stores and reports a
    // median off ten shops. A build that quoted the wrong one would look
    // completely normal, so the shape of the answer is pinned here.
    if (bj.tier.walk) {
      const w = bj.tier.walk;
      ok('the roster walk is the exhaustive one, not the rate-limited one',
         w.stores >= 100 && w.eligible > 20000, JSON.stringify(w));
      ok('the walk figures reach every brief',
         allPages.every(([, h]) => h.includes(w.eligible.toLocaleString('en-US')) &&
                                   h.includes('median store of ' + w.median)));
      ok('the share of stores fitting the cap agrees with the walk',
         (w.median > bj.tier.observed_cap) === (w.fits < 50),
         'median ' + w.median + ' vs cap ' + bj.tier.observed_cap + ', fits ' + w.fits + '%');
    } else {
      console.log('  SKIP  no roster walk in the record (build with --probe)');
    }

    // ── the bytes, read as bytes ─────────────────────────────────────────────
    // DémodéMODÉ, SIEDRÉS, Pärlemor and With Jéan are the reason. A page that
    // renders "DÃ©modÃ©MODÃ‰" to the founder it was written for is worse than
    // no page, and it passes every check that looks at the Python instead.
    bad('no replacement characters', (h) => h.includes('\uFFFD'));
    bad('no double-encoded UTF-8 (Ã©, Â…)', (h) => /[\u00C2-\u00C3][\u0080-\u00BF]/.test(h));
    bad('no entity that got escaped twice', (h) => /&amp;(nbsp|ndash|mdash|#)/.test(h));
    // "nan%" has to be anchored: a brand called Hernan Herdez percent-encodes
    // into "...Hernan%20Herdez" inside a mailto subject, and an unanchored
    // substring check fails on a page that is entirely correct.
    ['None', 'undefined', 'NaN', 'Infinity', '{}'].forEach((s) =>
      bad('no "' + s + '" leaked in', (h) => h.includes(s)));
    bad('no "nan%" leaked in', (h) => /\bnan%/i.test(h));
    bad('no unrendered format braces',
        (h) => /\{[a-z_]+\}/.test(h.replace(/<style[\s\S]*?<\/style>/g, '')));
    bad('no gradients anywhere', (h) => /gradient/i.test(h));
    bad('every brief is noindex', (h) => !/name="robots"[^>]*noindex/.test(h));
    bad('no brief claims a canonical URL it does not have', (h) => /rel="canonical"/.test(h));
    bad('every brief carries its limits section', (h) => !/<section id="limits">/.test(h));
    bad('every brief carries a real route to disputing a number',
        (h) => !/looks wrong to you/.test(h) ||
               !/mailto:tryloupeapp@gmail\.com\?subject=This%20number%20looks%20wrong/.test(h));
    bad('no brief asks for a call, a meeting or a decision',
        (h) => /book a call|schedule a|jump on a call|let's chat|limited time|act now/i.test(h));
    bj.briefs.filter((b) => /[^\x00-\x7F]/.test(b.brand)).forEach((b) =>
      ok('accented name survives to the page: ' + b.brand,
         pages[b.slug].includes(b.brand)));

    // ── the claim boundary ───────────────────────────────────────────────────
    // Everything outside <section id="limits"> is a CLAIM. Inside it is a
    // disclaimer, where naming the thing we cannot see is the whole point — so
    // the banned vocabulary is checked against the page with that block cut out
    // rather than against the page, which would make the disclaimer illegal.
    const body = (h) => h.replace(/<section id="limits">[\s\S]*?<\/section>/, ' ')
                         .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    const BANNED = [
      // withdrawn: ~48% of any absence-based figure was our own sampler
      [/turnover/i, 'turnover'], [/turned over/i, 'turned over'],
      [/sell[- ]through/i, 'sell-through'], [/sold through/i, 'sold through'],
      [/selling through/i, 'selling through'], [/refresh rate/i, 'refresh rate'],
      [/refreshing fastest/i, 'refreshing fastest'], [/clearing fastest/i, 'clearing fastest'],
      [/\bchurn/i, 'churn'], [/disappear/i, 'disappear'], [/delist/i, 'delist'],
      // withdrawn: the barbell and the dead band did not survive the correction
      [/barbell/i, 'barbell'], [/dead band/i, 'dead band'],
      // never supportable from a public catalogue
      [/units sold/i, 'units sold'], [/your revenue/i, 'your revenue'],
      [/how much you sold/i, 'how much you sold'], [/stock depth/i, 'stock depth'],
      // PER-PRODUCT RISK. AUC 0.519 out of time, 0.92x in the top decile.
      [/at risk\b/i, 'at risk'], [/risk score/i, 'risk score'],
      [/risk model/i, 'risk model'], [/most likely to sell/i, 'most likely to sell'],
      [/will sell out/i, 'will sell out'], [/we predict/i, 'we predict'],
      [/\bpredicted\b/i, 'predicted'], [/\bforecast/i, 'forecast'],
      [/this piece is/i, 'this piece is'],
    ];
    BANNED.forEach(([re, label]) => {
      const hits = allPages.filter(([, h]) => re.test(body(h))).map(([s]) => s);
      ok('no brief says "' + label + '" as a claim', hits.length === 0,
         hits.slice(0, 3).join(', '));
    });
    ok('the limits block is where the disclaimers actually live',
       allPages.every(([, h]) => /Units, revenue, margin/.test(h) === false) ||
       allPages.every(([, h]) => /not units, not revenue/.test(h)));
    ok('every brief states that a per-piece model was tried and failed',
       allPages.every(([, h]) => /0\.519/.test(h) && /coin flip/.test(h)));

    // ── every figure carries n, its basis, and actually renders ──────────────
    // The failure this guards against has happened in this codebase: a value
    // computed, threaded through a prop chain, and rendered on zero screens,
    // with tsc and a full green suite. Reading the produced bytes is the check.
    const figs = [].concat(...bj.briefs.map((b) => b.figures.map((f) => [b, f])));
    ok('every figure declares one of the three bases',
       figs.every(([, f]) => BASES.indexOf(f.basis) >= 0),
       [...new Set(figs.filter(([, f]) => BASES.indexOf(f.basis) < 0)
                       .map(([, f]) => f.basis))].join(', '));
    ok('no figure is absence-based',
       figs.every(([, f]) => f.basis !== 'absence' && !/absence/i.test(f.id)));
    ok('every figure carries a sample size', figs.every(([, f]) => f.n > 0),
       figs.filter(([, f]) => !(f.n > 0)).slice(0, 3).map(([, f]) => f.id).join(', '));
    ok('every rate carries a 95% interval that contains it',
       figs.filter(([, f]) => f.kind === 'rate')
           .every(([, f]) => f.ci && f.lo <= f.pct && f.pct <= f.hi),
       figs.filter(([, f]) => f.kind === 'rate' && !(f.lo <= f.pct && f.pct <= f.hi))
           .slice(0, 3).map(([b, f]) => b.brand + '/' + f.id).join(', '));
    ok('every rate clears the sample floor it was published under',
       figs.filter(([, f]) => f.kind === 'rate').every(([, f]) => f.n >= 8),
       figs.filter(([, f]) => f.kind === 'rate' && f.n < 8).slice(0, 3)
           .map(([b, f]) => b.brand + '/' + f.id + '=' + f.n).join(', '));
    // ANCHORED, not substring. Deleting "84%" from Paris Georgia's price table
    // left a bare-substring version of this check passing, because the headline
    // also says "above 84% of the tier". The renderer emits
    // <span data-f="price.bottoms.percentile">84%</span> so a figure that stops
    // rendering cannot be covered for by a collision somewhere else on the page.
    const anchor = (f) => '<span data-f="' + f.id + '">' + f.display + '</span>';
    const anchorCi = (f) => '<span data-c="' + f.id + '">' + f.ci + '</span>';
    const missing = figs.filter(([b, f]) => !pages[b.slug].includes(anchor(f)));
    ok('every figure renders, anchored to its own id',
       missing.length === 0,
       missing.slice(0, 4).map(([b, f]) => b.brand + '/' + f.id + '="' + f.display + '"')
              .join(', '));
    const missingCi = figs.filter(([b, f]) => f.ci && !pages[b.slug].includes(anchorCi(f)));
    ok('every interval renders beside its own figure',
       missingCi.length === 0,
       missingCi.slice(0, 4).map(([b, f]) => b.brand + '/' + f.id).join(', '));
    ok('no page carries an anchor for a figure that is not in the record',
       allPages.every(([slug, h]) => {
         const rec = new Set(bj.briefs.find((b) => b.slug === slug).figures.map((f) => f.id));
         return (h.match(/data-[fc]="([^"]+)"/g) || [])
           .every((m) => rec.has(m.replace(/data-[fc]="/, '').replace(/"$/, '')));
       }));

    // ── one label's numbers are one label's business ─────────────────────────
    const names = bj.briefs.map((b) => b.brand)
      .concat(bj.skipped.map((s) => s.brand))
      .filter((n) => n.length >= 5);
    const leaks = [];
    bj.briefs.forEach((b) => {
      const txt = body(pages[b.slug]);
      names.forEach((n) => {
        if (n === b.brand) return;
        if (new RegExp('(^|[^A-Za-z0-9])' + esc2(n) + '([^A-Za-z0-9]|$)').test(txt)) {
          leaks.push(b.brand + ' names ' + n);
        }
      });
    });
    ok('no brief names any label except the one it is for', leaks.length === 0,
       leaks.slice(0, 5).join('; '));
    ok('no brief carries a brand-card token',
       Object.values(keys).every((k) => allPages.every(([, h]) => !h.includes(k))));
    // The TLD is required: without it "wght@9..144" out of the Google Fonts
    // URL reads as an address and the check fails on every page.
    ok('the only address on a brief is the one that answers',
       allPages.every(([, h]) =>
         (h.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g) || [])
           .every((a) => a === 'tryloupeapp@gmail.com')));

    // No per-product row of any kind: not a name, not an id, not an image.
    const feed = process.env.LOUPE_FEED_REPO || 'C:\\loupe-feed';
    const catPath = path.join(feed, 'loupe-feed', 'catalog.json');
    if (fs.existsSync(catPath)) {
      const cat = JSON.parse(fs.readFileSync(catPath, 'utf8')).products || [];
      const byBrand = {};
      cat.forEach((p) => { (byBrand[p.brand] = byBrand[p.brand] || []).push(p); });
      const prod = [];
      bj.briefs.forEach((b) => {
        (byBrand[b.brand] || []).forEach((p) => {
          if (p.id && pages[b.slug].includes(p.id)) prod.push(b.brand + ' / id ' + p.id);
          if (p.name && p.name.length >= 12 && pages[b.slug].includes(p.name)) {
            prod.push(b.brand + ' / "' + p.name + '"');
          }
        });
      });
      ok('no brief names an individual product', prod.length === 0, prod.slice(0, 3).join('; '));
      ok('no brief carries a product image', allPages.every(([, h]) => !/<img/i.test(h)));
    } else {
      console.log('  SKIP  per-product check needs the feed clone at ' + catPath);
    }

    // ── contrast, from the brief's own CSS variables ─────────────────────────
    const one = allPages[0][1];
    const W = {};
    (one.match(/--[a-z-]+:#[0-9A-Fa-f]{6}/g) || []).forEach((m) => {
      const [k, v] = m.split(':'); W[k.replace('--', '')] = v;
    });
    [['ink', 'paper'], ['ink', 'white'], ['ink', 'pink-soft'],
     ['muted', 'paper'], ['muted', 'white'], ['muted', 'pink-soft'],
     ['accent', 'paper'], ['accent', 'white'], ['accent', 'pink-soft']].forEach(([f, b]) => {
      const r = contrast(W[f], W[b]);
      ok('brief: ' + f + ' on ' + b + ' clears AA (' + r.toFixed(2) + ':1)', r >= 4.5,
         W[f] + ' on ' + W[b]);
    });
    // The basis chip is muted on an explicit white fill, so it never inherits
    // the surface it happens to sit on. Pin both facts.
    ok('the basis chip sets its own background rather than inheriting one',
       /\.basis\{[^}]*background:var\(--white\)/.test(one));
    ok('basis-chip text clears AA on that fill (' +
       contrast(W.muted, W.white).toFixed(2) + ':1)', contrast(W.muted, W.white) >= 4.5);
    // The assortment pills are the only surfaces on a brief whose background is
    // a hex literal rather than a token, so they are the ones a variable sweep
    // silently misses. .pill.down is muted-on-#F1F1F1 and lands at 4.53:1 —
    // above AA, but close enough that nobody should be eyeballing it.
    const pillBg = (one.match(/\.pill\{[^}]*background:(#[0-9A-Fa-f]{6})/) || [])[1];
    const downBg = (one.match(/\.pill\.down\{[^}]*background:(#[0-9A-Fa-f]{6})/) || [])[1];
    ok('pill text clears AA on the neutral pill (' +
       contrast(W.ink, pillBg || '#FFFFFF').toFixed(2) + ':1)',
       contrast(W.ink, pillBg || '#FFFFFF') >= 4.5, String(pillBg));
    ok('muted pill text clears AA on the down pill (' +
       contrast(W.muted, downBg || '#FFFFFF').toFixed(2) + ':1)',
       contrast(W.muted, downBg || '#FFFFFF') >= 4.5, String(downBg));

    // ── the briefs and the Index must not quote two different tiers ──────────
    if (bj.tier.window_end === d.windowEnd && bj.tier.window_start === d.windowStart) {
      ok('brief and Index agree on the tier full-price rate',
         Math.abs(bj.tier.md_held[0] - d.headline.full_price_pct) < 0.11,
         bj.tier.md_held[0] + ' vs ' + d.headline.full_price_pct);
      ok('brief and Index agree on the tier sold-out rate',
         Math.abs(bj.tier.oos_now[0] - d.soldOut.tier.pct) < 0.11,
         bj.tier.oos_now[0] + ' vs ' + d.soldOut.tier.pct);
      ok('brief and Index agree on how many pieces the tier holds',
         bj.tier.pieces === d.coverage.pieces_now,
         bj.tier.pieces + ' vs ' + d.coverage.pieces_now);
      ok('brief and Index agree on how many labels are read',
         bj.tier.labels === d.coverage.brands_now,
         bj.tier.labels + ' vs ' + d.coverage.brands_now);
    } else {
      console.log('  SKIP  tier cross-check: briefs cover ' + bj.tier.window_start + '..' +
                  bj.tier.window_end + ', Index covers ' + d.windowStart + '..' + d.windowEnd);
    }

    console.log('  ' + bj.briefs.length + ' briefs, ' + figs.length +
                ' figures, ' + bj.skipped.length + ' labels with too little shelf');
  }

  console.log(failures ? '\n' + failures + ' FAILED\n' : '\nAll checks passed.\n');
  process.exit(failures ? 1 : 0);
})();
