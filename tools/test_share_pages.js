// Every share link Loupe produces has to land somewhere real. Until 2026-09-05
// none of them did: /look/<payload>, /u/<name> and /product/<id> were all 404s,
// and the app's external product share sent the recipient to the brand's own
// storefront with no route back to Loupe at all.
//
// This is the test for the pages that fixed that. It checks the three things
// that would silently break the loop again:
//
//   1. THE LOOK DECODER. /look/ reads a base64url payload the APP wrote with
//      btoa(unescape(encodeURIComponent(json))). The two halves live in two
//      repositories and nothing but this contract connects them, so the test
//      lifts the decoder straight out of the shipped HTML, runs it, and feeds it
//      a payload encoded exactly the way the app encodes one — accents included.
//   2. THE ROUTER. 404.html is the only thing standing between a shared /u/,
//      /product/ or /brand/ link and a blank GitHub 404, so each route has to be
//      present and each has to say something a human can act on.
//   3. THE PRODUCT PAGES. Each one must carry its own id in the Smart App Banner
//      argument and canonical, an og:image (or it previews as a grey box in a
//      DM, which is the whole reason the page exists), and a route to the App
//      Store. Plus the standing copy rules: no "AI"/"algorithm"/"recommend"/
//      "personalised", no gradients.
//
//   node tools/test_share_pages.js
//
// Exits 0 when everything holds, 1 with the failures printed otherwise.

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const APPSTORE = 'https://apps.apple.com/app/id6781137336';
const APP_ID = '6781137336';

const failures = [];
let checks = 0;

function ok(cond, msg) {
  checks++;
  if (!cond) failures.push(msg);
}

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8');
}

// Visible copy only: attributes, <script> bodies and URLs carry brand-supplied
// strings (there is a real product photo filename with "Kive.ai" in it) and are
// not Loupe writing marketing.
function prose(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ');
}

const BANNED = /\b(a\.?i\.?|algorithms?|recommend\w*|personali[sz]\w*)\b/i;

// ── 1. the look decoder ──────────────────────────────────────────────────────

function encodeLikeTheApp(obj) {
  // src/utils/lookShareLink.ts: btoa(unescape(encodeURIComponent(json))) then
  // +/ -> -_ with '=' stripped.
  const json = JSON.stringify(obj);
  const bytes = Buffer.from(json, 'utf8').toString('binary');
  return Buffer.from(bytes, 'binary')
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function testLookPage() {
  const html = read('look/index.html');

  ok(html.includes(`<meta name="apple-itunes-app" content="app-id=${APP_ID}">`),
    'look/: missing the Smart App Banner');
  ok(/<meta name="referrer" content="no-referrer">/.test(html),
    'look/: missing the no-referrer policy');
  ok(html.includes('og:image'), 'look/: missing og:image');
  ok(html.includes(APPSTORE), 'look/: missing the App Store CTA');
  ok(!BANNED.test(prose(html)), 'look/: banned word in visible copy');
  ok(!/gradient/i.test(html), 'look/: gradient (flat colours only)');

  // Lift the decoder out of the shipped file and run it.
  const start = html.indexOf('function fromBase64Url');
  const end = html.indexOf('function readPayload');
  ok(start > 0 && end > start, 'look/: fromBase64Url is not where the test expects it');
  if (start < 0 || end < start) return;
  const src = html.slice(start, end);
  const decode = new Function('atob', 'escape', `${src}; return fromBase64Url;`)(
    globalThis.atob,
    globalThis.escape,
  );

  const payload = {
    v: 1,
    t: 'Café weather',
    items: [
      { b: 'Dôen', n: 'Éloise Dress — Rubis', p: 328, i: 'https://x/y.jpg', u: 'https://shopdoen.com/p' },
      { b: 'Pärlemor', n: 'Jämt Shirt', p: 145, i: 'https://x/z.jpg', u: 'https://parlemor.se/p' },
    ],
  };
  let round = null;
  try {
    round = JSON.parse(decode(encodeLikeTheApp(payload)));
  } catch (e) {
    failures.push(`look/: decoder threw on a well-formed payload — ${e.message}`);
  }
  checks++;
  if (round) {
    ok(round.t === payload.t, 'look/: title did not survive the round trip');
    ok(round.items[0].b === 'Dôen' && round.items[1].b === 'Pärlemor',
      'look/: accented brand names did not survive the round trip');
    ok(round.items[0].n === 'Éloise Dress — Rubis',
      'look/: an em dash / accents did not survive the round trip');
    ok(round.items[0].p === 328, 'look/: price did not survive the round trip');
  }

  // Malformed input must not throw out of the decoder's caller.
  ok(/catch\s*\(\s*e\s*\)\s*\{\s*p\s*=\s*null/.test(html) || /try\s*\{\s*p\s*=\s*readPayload/.test(html),
    'look/: a malformed payload is not caught');
  ok(html.includes('fallback'), 'look/: no fallback state for a broken link');
}

// ── 2. the router ────────────────────────────────────────────────────────────

function test404() {
  const html = read('404.html');

  ok(html.includes(`<meta name="apple-itunes-app" content="app-id=${APP_ID}">`),
    '404: missing the Smart App Banner');
  ok(/<meta name="referrer" content="no-referrer">/.test(html), '404: missing the no-referrer policy');
  ok(html.includes(APPSTORE), '404: missing the App Store CTA');

  ok(/\/\^\\\/look/.test(html) || html.includes("'/look/'"), '404: no /look route');
  ok(html.includes('/brands/'), '404: no /brand route');
  ok(/This is a Loupe profile/.test(html), '404: the /u/ route does not identify itself');
  ok(html.includes("'/u/?u='"), '404: the /u/ route does not hand off to the profile page');
  ok(/sold out or left the shelf/i.test(html), '404: the /product/ route has no sold-out copy');
  ok(!BANNED.test(prose(html)), '404: banned word in visible copy');
  ok(!/gradient/i.test(html), '404: gradient (flat colours only)');
}

// ── 2b. the profile page the router hands off to ─────────────────────────────

function testProfilePage() {
  const html = read('u/index.html');
  ok(html.includes(`app-id=${APP_ID}`), 'u/: missing the Smart App Banner');
  ok(/<meta name="referrer" content="no-referrer">/.test(html), 'u/: missing the no-referrer policy');
  ok(/This is a Loupe profile/.test(html), 'u/: no "open it in the app" state');
  ok(!/Profile not found/.test(html),
    'u/: still says "profile not found" for a real username (reads as "this person does not exist")');
  ok(html.includes(APPSTORE), 'u/: missing the App Store CTA');
  ok(!BANNED.test(prose(html)), 'u/: banned word in visible copy');
}

// ── 3. the product pages ─────────────────────────────────────────────────────

function listProductDirs() {
  const dir = path.join(ROOT, 'product');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);
}

function testProductPages() {
  const dirs = listProductDirs();
  ok(dirs.length > 1000, `product/: only ${dirs.length} pages — the catalog has thousands`);
  ok(fs.existsSync(path.join(ROOT, 'product', 'p.css')), 'product/: the shared stylesheet is missing');

  const css = read('product/p.css');
  ok(!/gradient/i.test(css), 'product/p.css: gradient (flat colours only)');

  // A deterministic spread across the alphabet rather than the first N.
  const sorted = dirs.slice().sort();
  const step = Math.max(1, Math.floor(sorted.length / 40));
  const sample = [];
  for (let i = 0; i < sorted.length && sample.length < 40; i += step) sample.push(sorted[i]);

  let bytes = 0;
  for (const id of sample) {
    const rel = path.posix.join('product', id, 'index.html');
    let html;
    try {
      html = fs.readFileSync(path.join(ROOT, 'product', id, 'index.html'), 'utf8');
    } catch (e) {
      failures.push(`${rel}: no index.html`);
      checks++;
      continue;
    }
    bytes += Buffer.byteLength(html, 'utf8');
    const enc = encodeURIComponent(id);
    ok(html.includes(`app-argument=loupe://product/${enc}`), `${rel}: wrong or missing app-argument`);
    ok(html.includes(`app-id=${APP_ID}`), `${rel}: missing the Smart App Banner`);
    ok(html.includes(`href="https://useloupe.shop/product/${enc}/"`), `${rel}: wrong canonical`);
    ok(/content=no-referrer>/.test(html), `${rel}: missing the no-referrer policy`);
    ok(/<meta property=og:image content="https?:\/\/[^"]+">/.test(html), `${rel}: no og:image`);
    ok(html.includes(APPSTORE), `${rel}: no App Store CTA`);
    ok(html.includes('/product/p.css'), `${rel}: not using the shared stylesheet`);
    ok(!BANNED.test(prose(html)), `${rel}: banned word in visible copy`);
    ok(!/gradient/i.test(html.replace(/https?:\/\/\S+/g, ' ')), `${rel}: gradient (flat colours only)`);
    ok(Buffer.byteLength(html, 'utf8') < 4096, `${rel}: over 4 KB`);
  }
  const avg = Math.round(bytes / Math.max(sample.length, 1));
  ok(avg < 3072, `product/: sampled average page is ${avg} B, over the 3 KB budget`);
  console.log(`  sampled ${sample.length} of ${dirs.length} product pages, avg ${avg} B`);
}

// ── run ──────────────────────────────────────────────────────────────────────

testLookPage();
test404();
testProfilePage();
testProductPages();

if (failures.length) {
  console.error(`\nFAIL — ${failures.length} of ${checks} checks:`);
  for (const f of failures) console.error(`  • ${f}`);
  process.exit(1);
}
console.log(`\nPASS — ${checks} checks (share pages)`);
