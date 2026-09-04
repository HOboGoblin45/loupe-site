// THE ATTACK. This script is the 2026-09-04 audit, reproduced as a test.
//
// loupe-site is a PUBLIC repository. Anyone can list /index/d/ and /partners/d/
// through the GitHub contents API and get every filename. Until 2026-09-04 the
// filename WAS the access token, and the token WAS the AES-256-GCM key
// (SHA-256(token)), so a directory listing was a list of keys, each labelled
// with the file it opens. The 2026-08-01 "encrypt at rest" fix changed what was
// in the files without changing what they were called, and passed its own tests.
//
// What this does, in order, with nothing but public inputs:
//   1. list the directory (local checkout, or the GitHub contents API with --remote)
//   2. for every file, derive every key an outsider could derive FROM THE NAME:
//        SHA-256(name)                       — the 2026-08-01 scheme, verbatim
//        SHA-256("loupe-card-key:" + name)   — the post-fix key derivation, fed
//                                              the filename as if it were a token
//        the raw name bytes, zero-padded     — the trivial one
//   3. try to open the file with each; AES-GCM authenticates, so a wrong key
//      throws and a right key yields JSON with a brand name in it
//
// It PASSES (exit 0) when it opens NOTHING. It FAILS (exit 1) when it opens
// anything, and prints what it opened — that is the hole, demonstrated.
//
//   node tools/test_token_leak.js            # against the working tree
//   node tools/test_token_leak.js --remote   # against github.com + useloupe.shop
//
// Run it against the old scheme and it opens every file. That before/after is
// the only acceptable proof for a hole that has now been reported twice.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const REPO = 'HOboGoblin45/loupe-site';
const SITE = 'https://useloupe.shop';
const DIRS = ['index/d', 'partners/d'];
const REMOTE = process.argv.includes('--remote');

// Every derivation is spelled out here rather than imported from the code under
// test: the point is what an outsider who has read the public source can do,
// and an outsider does not get to call our helpers. If the key-derivation
// prefix in card_crypto.py ever changes, change it here too — this file must
// keep describing the real scheme or the "attack" stops attacking anything.
const KEY_PREFIX = 'loupe-card-key:';

function candidateKeys(stem) {
  return [
    ['SHA-256(name)',              crypto.createHash('sha256').update(stem).digest()],
    ['SHA-256("' + KEY_PREFIX + '" + name)',
                                   crypto.createHash('sha256').update(KEY_PREFIX + stem).digest()],
    ['raw name bytes',             Buffer.concat([Buffer.from(stem), Buffer.alloc(32)]).subarray(0, 32)],
  ];
}

function tryOpen(envelope, key) {
  let env;
  try { env = JSON.parse(envelope); } catch (e) { return null; }
  if (!env || !env.iv || !env.ct) {
    // Not an envelope at all. If it parses as JSON with a name in it, it is
    // plaintext and the "attack" is just reading it.
    return env && (env.brand || env.name) ? env : null;
  }
  try {
    const iv = Buffer.from(env.iv, 'base64');
    const blob = Buffer.from(env.ct, 'base64');
    const d = crypto.createDecipheriv('aes-256-gcm', key, iv);
    d.setAuthTag(blob.subarray(blob.length - 16));
    const pt = Buffer.concat([d.update(blob.subarray(0, blob.length - 16)), d.final()]);
    return JSON.parse(pt.toString('utf8'));
  } catch (e) {
    return null;
  }
}

async function listLocal(dir) {
  const abs = path.join(ROOT, dir);
  if (!fs.existsSync(abs)) return [];
  return fs.readdirSync(abs).filter((f) => f.endsWith('.json')).map((f) => ({
    name: f,
    read: async () => fs.readFileSync(path.join(abs, f), 'utf8'),
  }));
}

async function listRemote(dir) {
  // Exactly the audit's first step. Unauthenticated; the listing is public.
  const r = await fetch('https://api.github.com/repos/' + REPO + '/contents/' + dir,
                        { headers: { 'User-Agent': 'loupe-token-leak-test' } });
  if (!r.ok) throw new Error('GitHub listing ' + dir + ' -> HTTP ' + r.status);
  const items = await r.json();
  return items.filter((it) => it.type === 'file' && it.name.endsWith('.json')).map((it) => ({
    name: it.name,
    // Read from the site the way a visitor would; falls back to the raw blob
    // GitHub already handed us a URL for.
    read: async () => {
      const s = await fetch(SITE + '/' + dir + '/' + it.name, { cache: 'no-store' });
      if (s.ok) return s.text();
      const g = await fetch(it.download_url);
      if (!g.ok) throw new Error('could not read ' + it.name);
      return g.text();
    },
  }));
}

(async () => {
  console.log('\nTOKEN-LEAK ATTACK  (' + (REMOTE ? 'live: api.github.com + ' + SITE : 'working tree: ' + ROOT) + ')');
  let files = 0, opened = 0;
  const byDir = {};
  for (const dir of DIRS) {
    const list = REMOTE ? await listRemote(dir) : await listLocal(dir);
    byDir[dir] = { files: list.length, opened: 0 };
    console.log('\n  ' + dir + ': ' + list.length + ' file(s) listed');
    for (const f of list) {
      files++;
      const stem = f.name.replace(/\.json$/, '');
      const body = await f.read();
      for (const [how, key] of candidateKeys(stem)) {
        const pt = tryOpen(body, key);
        if (pt) {
          opened++;
          byDir[dir].opened++;
          const who = pt.brand || pt.name || '?';
          // Name the victim, never the numbers: the proof is that it opened.
          console.log('    OPENED  ' + f.name + '  via ' + how + '  ->  "' + who + '"  (' +
                      Object.keys(pt).length + ' fields' + (pt.shelf ? ', shelf ' + pt.shelf : '') + ')');
          break;
        }
      }
    }
  }

  console.log('');
  for (const dir of DIRS) {
    console.log('  ' + dir.padEnd(12) + byDir[dir].opened + ' of ' + byDir[dir].files + ' opened from the filename alone');
  }
  if (opened) {
    console.log('\n  FAIL  the directory listing is a key ring: ' + opened + ' of ' + files +
                ' private file(s) decrypt with a key derived from their own name.\n');
    process.exit(1);
  }
  console.log('\n  PASS  ' + files + ' file(s) listed, 0 opened. A filename derives nothing.\n');
  process.exit(0);
})().catch((e) => {
  console.error('\n  ERROR  ' + (e && e.message ? e.message : e) + '\n');
  process.exit(2);
});
