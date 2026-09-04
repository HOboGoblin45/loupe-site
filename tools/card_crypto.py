"""Loupe — how a private card is named and how it is opened. ONE place.

Used by build_loupe_index.py (the per-brand Index cards in /index/d/),
build_partner_report.py (the partner reports in /partners/d/) and
build_index_outreach.py (which reads cards back to write emails). The browser
half of the same scheme is CARD_JS below, spliced verbatim into both shells, so
the Python that writes a card and the JavaScript that opens it cannot drift.

THE HOLE THIS CLOSES — reported twice, "fixed" once

  loupe-site is a PUBLIC GitHub repository. Anyone can list /index/d/ and
  /partners/d/ through the contents API and read every filename.

  2026-08-01: the files were named after the access token and held plaintext.
  The directory listing was the password. Fix: encrypt each file with
  AES-256-GCM under SHA-256(token). The tests decrypted every card and passed.

  2026-09-04: the files were STILL named after the token, and the token was
  still the key. A directory listing was now a key ring, each key labelled with
  the file it opens. The audit decrypted Gemini's report and three brand cards
  from filenames alone; the attack in tools/test_token_leak.js opens 155 of 155.
  "Encrypted at rest" was true and meant nothing, because the thing at rest
  next to the ciphertext was its key.

THE FIX — domain separation between the path and the key

  The token stays secret and stays in the URL (?k=<token>). Two DIFFERENT
  one-way functions of it are used for two different jobs:

      path = base64url(SHA-256("loupe-card-path:" + token))[:22]   the file's name
      key  =           SHA-256("loupe-card-key:"  + token)         what opens it

  Listing the directory now yields path-hashes. Turning a path-hash back into
  the token is a SHA-256 preimage; turning it into the key is the same preimage
  followed by a different hash. Neither is a computation, both are 2^128 work.
  The two prefixes are what make the two hashes unrelated: without them
  path == base64url(key), which is the hole with one extra step.

  The browser derives the path from the token before it fetches, then derives
  the key separately to decrypt. Nothing on disk, in git, in a directory
  listing or in a CDN log is the token or the key.

WHAT DID NOT CHANGE

  The envelope is the same {"v","iv","ct"} AES-256-GCM object, same
  deterministic nonce (HMAC(key, plaintext)[:12], so an unchanged card is a
  byte-identical file and the diff before a commit is honest). Only "v" moved
  from 1 to 2, so a v1 envelope in git history announces which scheme it is.

  The token is still 128 bits from secrets.token_urlsafe(16) and still not
  stretched: there is nothing to brute-force in 128 real bits, and a slow hash
  only helps secrets a human chose.

WHAT CANNOT BE FIXED HERE

  Every ciphertext committed before 2026-09-04 sits in git history under its
  token-as-filename, and two 2026-07-31 commits hold the Gemini report in
  plaintext. Re-minting burns the tokens so those files decrypt to STALE data
  only — but they still decrypt. See the 2026-09-04 report for the options.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import sys

# Domain-separation prefixes. They must be DISTINCT and neither may be a prefix
# of the other; test_loupe_index.js and test_partner_report.js pin both facts,
# reading these literals out of this file AND out of the shipped shells.
PATH_DOMAIN = "loupe-card-path:"
KEY_DOMAIN = "loupe-card-key:"

# 22 base64url characters of the path hash = 132 bits. Same length as a token,
# which is deliberate: a listing of the old scheme and a listing of the new one
# look alike, and only one of them is worth anything.
PATH_CHARS = 22

# Envelope version. 1 = keyed on SHA-256(token) and named after the token
# (2026-08-01 to 2026-09-04, do not accept). 2 = domain-separated (this file).
VERSION = 2

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")


def mint_token():
    """128 bits, URL-safe, 22 characters. This is the whole secret."""
    return secrets.token_urlsafe(16)


def card_path(token):
    """The name of the file on disk, derived from the token by a hash that is
    NOT the key. This is the only string that reaches the public repository."""
    digest = hashlib.sha256((PATH_DOMAIN + token).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:PATH_CHARS]


def card_key(token):
    """The AES-256 key, derived from the token by a hash that is NOT the path."""
    return hashlib.sha256((KEY_DOMAIN + token).encode("utf-8")).digest()


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        sys.exit("Private cards need `cryptography` (pip install cryptography).\n"
                 "  It is what keeps 150+ labels' and every partner's private figures\n"
                 "  out of a PUBLIC repo. There is no unencrypted fallback on purpose.")
    return AESGCM


def encrypt(payload, token):
    """The envelope text for `payload`, openable only with `token`.

    Refuses to proceed if the derived path could be confused with the token —
    which cannot happen with SHA-256, and is asserted anyway because this file
    exists to make one specific mistake impossible rather than merely unlikely.
    """
    p = card_path(token)
    if token in p or p in token or p == token:
        raise RuntimeError("card path collides with its token — refusing to write")
    key = card_key(token)
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # DETERMINISTIC nonce, derived from the key and the plaintext, so an
    # unchanged card is a byte-identical file. Key+nonce reuse is only unsafe
    # when the PLAINTEXT differs; here an identical nonce implies an identical
    # plaintext by construction, so there is nothing to leak.
    iv = hmac.new(key, plain, hashlib.sha256).digest()[:12]
    ct = _aesgcm()(key).encrypt(iv, plain, None)
    # No brand, no slug, no plaintext-length hint beyond the ciphertext's own.
    return json.dumps({"v": VERSION,
                       "iv": base64.b64encode(iv).decode("ascii"),
                       "ct": base64.b64encode(ct).decode("ascii")}, separators=(",", ":"))


def decrypt(envelope_text, token):
    """The payload inside `envelope_text`, or a raised error. A v1 envelope is
    refused outright rather than tried under the old derivation: the old
    derivation is the hole, and nothing in this codebase may still speak it."""
    env = json.loads(envelope_text)
    if env.get("v") != VERSION:
        raise ValueError(f"envelope v{env.get('v')} is not v{VERSION}")
    pt = _aesgcm()(card_key(token)).decrypt(base64.b64decode(env["iv"]),
                                            base64.b64decode(env["ct"]), None)
    return json.loads(pt)


# The browser side. Spliced verbatim into /index/brand/index.html and
# /partners/<slug>/index.html by their builders, inside an IIFE that has already
# validated `k` (the token from ?k=). Defines:
#   cardPath(k)  -> Promise<string>     the file name, never the token
#   cardKey(k)   -> Promise<CryptoKey>  the AES-GCM key, never the path
#   decrypt(env) -> Promise<object>     refuses anything that is not a v2 envelope
# Plain ES5 on purpose: these pages have no build step and no polyfill.
CARD_JS = r"""
  // The file on the server is AES-256-GCM ciphertext. Its NAME is one hash of
  // the token in this URL and its KEY is a different hash of the same token,
  // with distinct prefixes so neither can be turned into the other. loupe-site
  // is a public repository, so the file list is public; until 2026-09-04 the
  // file was named after the token itself and the list was a key ring. Now a
  // listing yields path-hashes that derive nothing. Requires a secure context.
  var PATH_DOMAIN = '""" + PATH_DOMAIN + r"""', KEY_DOMAIN = '""" + KEY_DOMAIN + r"""';
  function sha256(s){ return crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)); }
  function b64url(buf){
    var a = new Uint8Array(buf), s = '';
    for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function bytes(b64){
    var s = atob(b64), a = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
    return a;
  }
  function cardPath(k){
    return sha256(PATH_DOMAIN + k).then(function(d){ return b64url(d).slice(0, """ + str(PATH_CHARS) + r"""); });
  }
  function cardKey(k){
    return sha256(KEY_DOMAIN + k)
      .then(function(d){ return crypto.subtle.importKey('raw', d, 'AES-GCM', false, ['decrypt']); });
  }
  function decrypt(env){
    if (!env || env.v !== """ + str(VERSION) + r""") return Promise.reject(0);   // v1 = the old scheme; never open it
    return cardKey(k)
      .then(function(key){ return crypto.subtle.decrypt({name:'AES-GCM', iv: bytes(env.iv)}, key, bytes(env.ct)); })
      .then(function(buf){ return JSON.parse(new TextDecoder().decode(buf)); });
  }
"""
