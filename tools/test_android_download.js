#!/usr/bin/env node
/* eslint-disable no-console */
// ─────────────────────────────────────────────────────────────────────────────
// Loupe: the Android download is reachable from every page, and works
//
// Checks:
//   1. /android/ exists, links the APK that is actually in the repo, and the
//      SHA-256 it publishes matches that file.
//   2. Every HTML page that links the App Store also loads /android/route.js
//      (the generators add it; this catches a page that slipped through).
//   3. route.js, run in a real DOM (jsdom, if installed):
//        Android UA: App Store links (static AND added later by JS) point to
//                    /android/ and are relabelled; html gets .loupe-android.
//        iPhone UA:  nothing changes.
//   4. The homepage offers Android, and the sitemap lists /android/.
//
// Usage: node tools/test_android_download.js
//   jsdom: `npm i jsdom` anywhere on NODE_PATH; without it check 3 is skipped
//   (reported, not silently passed).
// ─────────────────────────────────────────────────────────────────────────────

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.join(__dirname, '..');
const STORE = 'https://apps.apple.com/app/id6781137336';
const ROUTE_TAG = '<script src="/android/route.js" defer></script>';

let failures = 0;
let checks = 0;
function ok(cond, msg) {
  checks += 1;
  if (!cond) {
    failures += 1;
    console.log(`  FAIL  ${msg}`);
  }
}

// ── 1. The download page and the file it serves ──────────────────────────────
const page = fs.readFileSync(path.join(ROOT, 'android', 'index.html'), 'utf8');
const apkPath = path.join(ROOT, 'android', 'Loupe-android.apk');
ok(fs.existsSync(apkPath), 'android/Loupe-android.apk is missing');
ok(page.includes('href="/android/Loupe-android.apk"'), '/android/ does not link the APK');
if (fs.existsSync(apkPath)) {
  const buf = fs.readFileSync(apkPath);
  ok(buf.length < 100 * 1024 * 1024, 'APK is over GitHub\'s 100 MB file limit');
  ok(buf.slice(0, 2).toString() === 'PK', 'APK is not a zip (bad upload?)');
  const sha = crypto.createHash('sha256').update(buf).digest('hex');
  ok(page.includes(sha), `/android/ publishes a SHA-256 that is not the APK's (${sha})`);
  const mb = Math.round(buf.length / 1048576);
  ok(page.includes(`${mb} MB`), `/android/ states a size other than ${mb} MB`);
}
ok(!page.includes('—'), '/android/ contains an em dash');
ok(page.includes('/android/route.js') === false, '/android/ should not load route.js (it IS the target)');

// ── 2. Every page that links the App Store loads route.js ────────────────────
function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    if (name === '.git' || name === 'node_modules') continue;
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (name.endsWith('.html')) out.push(p);
  }
  return out;
}
const pages = walk(ROOT, []);
let storePages = 0;
const missing = [];
for (const p of pages) {
  if (p.startsWith(path.join(ROOT, 'android'))) continue;
  const html = fs.readFileSync(p, 'utf8');
  if (!html.includes(STORE)) continue;
  storePages += 1;
  if (!html.includes(ROUTE_TAG)) missing.push(path.relative(ROOT, p));
}
ok(storePages > 100, `expected hundreds of pages linking the App Store, found ${storePages}`);
ok(missing.length === 0, `${missing.length} page(s) link the App Store without route.js: ${missing.slice(0, 5).join(', ')}`);

// ── 4. Homepage + sitemap ────────────────────────────────────────────────────
const home = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
ok(home.includes('href="/android/"'), 'homepage has no link to /android/');
ok(home.includes('html.loupe-android .android-cta{display:none;}'), 'homepage would show a duplicate Android button on Android');
ok(fs.readFileSync(path.join(ROOT, 'sitemap.xml'), 'utf8').includes('<loc>https://useloupe.shop/android/</loc>'), 'sitemap lacks /android/');

// ── 3. route.js in a DOM ─────────────────────────────────────────────────────
let JSDOM = null;
let ResourceLoader = null;
try {
  ({ JSDOM, ResourceLoader } = require('jsdom'));
} catch (_) {
  console.log('  SKIP  route.js DOM checks (jsdom not installed)');
}

const routeSrc = fs.readFileSync(path.join(ROOT, 'android', 'route.js'), 'utf8');
const ANDROID_UA = 'Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36';
const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';

function run(ua) {
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body>
      <a id="hero" href="${STORE}" target="_blank" class="btn">Get Loupe on the App Store</a>
      <a id="foot" href="${STORE}">iPhone app</a>
      <a id="other" href="https://example.com/">Elsewhere</a>
    </body></html>`,
    {
      runScripts: 'outside-only',
      url: 'https://useloupe.shop/u/?u=x',
      resources: new ResourceLoader({ userAgent: ua }),
    },
  );
  dom.window.eval(routeSrc);
  return dom;
}

(async () => {
  if (JSDOM) {
    // Android
    const a = run(ANDROID_UA);
    const d = a.window.document;
    // jsdom fires DOMContentLoaded a tick after construction (a browser runs a
    // defer script just before it); let the script's start() run first.
    await new Promise((r) => setTimeout(r, 0));
    ok(d.documentElement.className.includes('loupe-android'), 'Android: html lacks .loupe-android');
    ok(d.getElementById('hero').getAttribute('href') === '/android/', 'Android: hero link not routed');
    ok(d.getElementById('hero').textContent === 'Get Loupe for Android', `Android: hero label is "${d.getElementById('hero').textContent}"`);
    ok(!d.getElementById('hero').hasAttribute('target'), 'Android: routed link still opens a new tab');
    ok(d.getElementById('foot').textContent === 'Android app', 'Android: footer label not changed');
    ok(d.getElementById('other').getAttribute('href') === 'https://example.com/', 'Android: unrelated link was touched');

    // A button the page builds after load (as /u/ and /look/ do).
    const late = d.createElement('div');
    late.innerHTML = `<a id="late" class="btn" href="${STORE}">Keep swiping in the app</a>`;
    d.body.appendChild(late);
    await new Promise((r) => setTimeout(r, 0));
    ok(d.getElementById('late').getAttribute('href') === '/android/', 'Android: link added after load not routed');
    ok(d.getElementById('late').textContent === 'Get Loupe for Android', 'Android: late link not relabelled');

    // Loading the script twice must not double-handle anything.
    a.window.eval(routeSrc);
    ok((d.documentElement.className.match(/loupe-android/g) || []).length === 1, 'Android: script not idempotent');

    // iPhone: untouched.
    const i = run(IPHONE_UA).window.document;
    await new Promise((r) => setTimeout(r, 0));
    ok(!i.documentElement.className.includes('loupe-android'), 'iPhone: got .loupe-android');
    ok(i.getElementById('hero').getAttribute('href') === STORE, 'iPhone: hero link was changed');
    ok(i.getElementById('hero').textContent === 'Get Loupe on the App Store', 'iPhone: hero label was changed');
  }

  console.log(
    failures
      ? `\nFAIL: ${failures} of ${checks} checks (android download)`
      : `\nPASS: ${checks} checks (android download; ${storePages} App Store pages carry route.js)`,
  );
  process.exit(failures ? 1 : 0);
})();
