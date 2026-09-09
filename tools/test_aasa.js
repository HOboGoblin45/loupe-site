#!/usr/bin/env node
/* eslint-disable no-console */
// ─────────────────────────────────────────────────────────────────────────────
// Loupe — the Apple App Site Association file is machine-readable
//
// WHY THIS EXISTS. /.well-known/apple-app-site-association is what tells iOS
// that useloupe.shop/product/<id> belongs to Loupe. Get it wrong and every
// share link opens Safari instead of the app — silently, with no error anywhere,
// exactly like the month of OTAs that went to a runtime nobody was on.
//
// On 2026-09-09 the file was found to start with EF BB BF, a UTF-8 byte order
// mark, almost certainly from a PowerShell `Set-Content -Encoding utf8` (the
// same trap that once put a BOM in a commit subject). RFC 8259 §8.1 says an
// implementation MUST NOT add one, and Python's json.load refuses the file
// outright. Apple's CDN happened to accept it — it echoed the BOM straight back
// — but "the strictest parser in the chain happened not to be strict today" is
// not a foundation to put a launch on.
//
// It also verifies the things that are easy to get wrong and impossible to see:
// the appID matches the shipped bundle, the paths match what the app actually
// links, and the JSON has no trailing junk.
//
// Usage:  node tools/test_aasa.js            check the file in this repo
//         node tools/test_aasa.js --remote   also check what is being SERVED,
//                                            and what Apple's CDN holds
// ─────────────────────────────────────────────────────────────────────────────

const fs = require('fs');
const path = require('path');

const AASA = path.join(__dirname, '..', '.well-known', 'apple-app-site-association');
const APP_ID = '52SKBHZK3L.com.crescicharles.loupe';
// Every path family the app declares a linking route for. Kept here rather than
// derived, so a path silently disappearing from the file is a failure and not a
// tautology.
const REQUIRED_PATHS = ['/u/*', '/product/*', '/brand/*', '/look/*'];

let failures = 0;
function check(label, ok, detail) {
  if (ok) {
    console.log(`  ok    ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function checkBytes(label, buf) {
  check(`${label}: no UTF-8 BOM`, !(buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf),
    'starts EF BB BF; strict JSON parsers reject it');
  const text = buf.toString('utf8');
  check(`${label}: first character is {`, text.trimStart().startsWith('{'),
    `starts with ${JSON.stringify(text.slice(0, 8))}`);

  let doc = null;
  try {
    doc = JSON.parse(text);
    check(`${label}: parses as strict JSON`, true);
  } catch (e) {
    check(`${label}: parses as strict JSON`, false, e.message);
    return null;
  }

  const detail = doc?.applinks?.details?.[0];
  check(`${label}: declares the shipped bundle`, detail?.appID === APP_ID,
    `got ${JSON.stringify(detail?.appID)}`);
  const paths = detail?.paths ?? [];
  for (const p of REQUIRED_PATHS) {
    check(`${label}: links ${p}`, paths.includes(p), `paths = ${JSON.stringify(paths)}`);
  }
  return doc;
}

console.log('AASA — local file');
if (!fs.existsSync(AASA)) {
  check('the file exists', false, AASA);
} else {
  checkBytes('local', fs.readFileSync(AASA));
}

async function remote() {
  console.log('\nAASA — as served, and as Apple holds it');

  // 1. What useloupe.shop actually returns. Apple requires HTTPS and NO redirect.
  const served = await fetch('https://useloupe.shop/.well-known/apple-app-site-association', {
    redirect: 'manual',
  });
  check('served: 200 with no redirect', served.status === 200, `status ${served.status}`);
  checkBytes('served', Buffer.from(await served.arrayBuffer()));

  // 2. What Apple's own CDN cached. This is the authoritative answer to "did
  //    Apple accept our file" — a file it could not use is not served here.
  //    Apple caches for up to a day, so a fresh fix can lag; that is reported,
  //    never failed, so this gate can run in CI the moment a change lands.
  const cdn = await fetch(`https://app-site-association.cdn-apple.com/a/v1/useloupe.shop`);
  if (cdn.status !== 200) {
    console.log(`  note  Apple's CDN returned ${cdn.status} — it has not cached the domain yet`);
    return;
  }
  const cdnBuf = Buffer.from(await cdn.arrayBuffer());
  if (cdnBuf[0] === 0xef && cdnBuf[1] === 0xbb && cdnBuf[2] === 0xbf) {
    console.log("  note  Apple's CDN still holds the BOM'd copy — it re-fetches within ~24h");
  } else {
    check("Apple's cached copy is clean", true);
  }
}

const run = process.argv.includes('--remote') ? remote() : Promise.resolve();
run
  .catch((e) => {
    failures += 1;
    console.log(`  FAIL  remote check threw — ${e.message}`);
  })
  .then(() => {
    console.log(failures === 0 ? '\nPASS  the association file is machine-readable.' : `\n${failures} FAILURE(S)`);
    process.exit(failures === 0 ? 0 : 1);
  });
