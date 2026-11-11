#!/usr/bin/env node
/* eslint-disable no-console */
// ─────────────────────────────────────────────────────────────────────────────
// Loupe — the Android Digital Asset Links file is machine-readable
//
// /.well-known/assetlinks.json is the Android twin of the AASA: it proves to
// Android that useloupe.shop/u/, /product/ and /brand/ links belong to the app
// signed with Loupe's key, so those links open the app instead of Chrome. Get
// it wrong and verification fails SILENTLY: links just keep opening the browser.
//
// The fingerprint is the SHA-256 of the Loupe Android upload key
// (loupe-upload.keystore). If the app is later distributed through Google Play
// with Play App Signing, Play re-signs with ITS key: add that fingerprint (Play
// Console → Test and release → App integrity → App signing) as a SECOND entry;
// never replace the first while sideloaded installs exist.
//
// Usage:  node tools/test_assetlinks.js            check the file in this repo
//         node tools/test_assetlinks.js --remote   also check what is SERVED
// ─────────────────────────────────────────────────────────────────────────────

const fs = require('fs');
const path = require('path');
const https = require('https');

const FILE = path.join(__dirname, '..', '.well-known', 'assetlinks.json');
const PACKAGE = 'com.crescicharles.loupe';
const UPLOAD_KEY_SHA256 =
  '4F:05:AF:E2:43:7C:60:C9:7A:79:9A:56:E8:06:06:80:08:E8:1E:F2:C6:1B:4C:38:C2:4F:32:99:1F:D2:8C:72';

let failures = 0;
function check(label, ok, detail) {
  if (ok) console.log(`  ok    ${label}`);
  else {
    failures += 1;
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function checkBody(label, buf) {
  check(`${label}: no UTF-8 BOM`, !(buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf));
  let json;
  try {
    json = JSON.parse(buf.toString('utf8'));
  } catch (e) {
    check(`${label}: parses as JSON`, false, e.message);
    return;
  }
  check(`${label}: parses as JSON`, true);
  check(`${label}: is an array`, Array.isArray(json));
  const stmt = (Array.isArray(json) ? json : []).find(
    (s) => s && s.target && s.target.package_name === PACKAGE,
  );
  check(`${label}: has a statement for ${PACKAGE}`, Boolean(stmt));
  if (!stmt) return;
  check(
    `${label}: grants handle_all_urls`,
    Array.isArray(stmt.relation) && stmt.relation.includes('delegate_permission/common.handle_all_urls'),
  );
  check(`${label}: namespace is android_app`, stmt.target.namespace === 'android_app');
  const fps = stmt.target.sha256_cert_fingerprints || [];
  check(`${label}: lists the upload-key fingerprint`, fps.includes(UPLOAD_KEY_SHA256), fps.join(', '));
  check(
    `${label}: every fingerprint is 32 upper-case hex bytes`,
    fps.every((f) => /^([0-9A-F]{2}:){31}[0-9A-F]{2}$/.test(f)),
  );
}

function fetchServed(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => resolve({ res, body: Buffer.concat(chunks) }));
      })
      .on('error', reject);
  });
}

(async () => {
  console.log('assetlinks.json (repo)');
  checkBody('repo', fs.readFileSync(FILE));

  if (process.argv.includes('--remote')) {
    const url = 'https://useloupe.shop/.well-known/assetlinks.json';
    console.log(`assetlinks.json (served: ${url})`);
    try {
      const { res, body } = await fetchServed(url);
      check('served: HTTP 200 with no redirect', res.statusCode === 200, `status ${res.statusCode}`);
      check(
        'served: content-type is application/json',
        /application\/json/.test(String(res.headers['content-type'])),
        String(res.headers['content-type']),
      );
      checkBody('served', body);
    } catch (e) {
      check('served: reachable', false, e.message);
    }
  }

  console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
})();
