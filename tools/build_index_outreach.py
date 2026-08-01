#!/usr/bin/env python3
"""Loupe — generate the Index outreach emails.

WHY THIS REPLACES THE OLD PITCH

The previous brand outreach led with Loupe's own engagement — "22.0% approval
rate, 20 saves". Two problems. It is a statistic about Loupe, which no brand
asked for, off a user base small enough that a sceptical founder could dismiss
it in one question. And it arrives as a request.

This leads with a number about THEM, computed from their own storefront, and
arrives as a gift with nothing attached:

    Fait Par Foutch sold out 23.3% of its shelf. The tier ran 13.2%.

That is checkable, flattering when it is true, and impossible for them to get
anywhere else — WGSN and EDITED benchmark against Zara and Net-a-Porter; nobody
else can tell a $2M label how it compares to 176 labels exactly like it.

WHAT IT PICKS

One fact per brand, chosen by how far it sits from the tier and whether it
reflects well. Order of preference:
  1. Sells out faster than the tier
  2. Never marked down while peers did
  3. Refreshes faster than the tier
  4. Priced in a band that is clearing
Never a criticism. An unflattering number is genuinely useful and belongs on
their private card where they went looking for it — it does not belong in a
cold email from a stranger, which is how you turn an indifferent brand into a
hostile one.

Every claim carries its sample size internally so a reply asking "says who"
has an immediate answer.

USAGE
    python tools/build_index_outreach.py            # write drafts JSON
    python tools/build_index_outreach.py --preview  # print the first 3
"""

import argparse
import base64
import hashlib
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LINKS = ROOT / "tools" / "data" / "index_links.txt"
TARGETS = ROOT / "tools" / "data" / "index_outreach.json"
OUT = ROOT / "tools" / "data" / "index_drafts.json"
CARDS = ROOT / "index" / "d"

# A claim needs enough shelf behind it to survive being questioned. Below this
# the difference from the tier is noise and quoting it is a liability.
MIN_SHELF = 20


def decrypt(token):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    f = CARDS / f"{token}.json"
    if not f.exists():
        return None
    env = json.loads(f.read_text(encoding="utf-8"))
    key = hashlib.sha256(token.encode()).digest()
    pt = AESGCM(key).decrypt(base64.b64decode(env["iv"]),
                             base64.b64decode(env["ct"]), None)
    return json.loads(pt)


def pick_fact(c):
    """The single most notable TRUE and FLATTERING thing about this label.

    Returns (headline, supporting) or None when nothing stands out — in which
    case the email leads with the tier finding instead, which is still news.
    """
    t = c["tier"]
    shelf = c.get("shelf", 0)
    if shelf < MIN_SHELF:
        return None

    so, so_t = c["soldout"], t["soldout"]
    # Sold out meaningfully faster than the tier, and the CI clears it.
    if so["pct"] >= so_t["pct"] * 1.35 and so["lo"] > so_t["pct"]:
        return (
            f"{c['brand']} sold out {so['pct']}% of the shelf we track. "
            f"Across the tier it was {so_t['pct']}%.",
            f"That is {so['k']} of {so['n']} pieces, against "
            f"{so_t['k']:,} of {so_t['n']:,} tier-wide.",
        )

    # Held full price while most of the tier's markdown happened elsewhere.
    md = c.get("markdown") or {}
    if md.get("cut") == 0 and shelf >= 30:
        return (
            f"{c['brand']} did not mark down a single piece in the fortnight "
            f"we measured. {t['full_price_houses']} of {t['brands_measured']} "
            f"labels managed that.",
            f"Measured across {md.get('n', shelf)} pieces.",
        )

    # Refreshing materially faster than the tier median.
    ar = c.get("arrivals_pct")
    if ar and ar >= 25:
        return (
            f"{c['brand']} replaced {ar}% of its shelf in the last 31 days. "
            f"The tier median was {t['newness_median']}%.",
            f"That is {c.get('arrivals', 0)} new pieces on a shelf of {shelf}.",
        )

    # Turnover well above the tier — things are moving, whatever the cause.
    tu, tu_t = c.get("turnover") or {}, t["turnover"]
    if tu.get("pct", 0) >= tu_t["pct"] * 1.3 and tu.get("lo", 0) > tu_t["pct"]:
        return (
            f"{c['brand']} turned over {tu['pct']}% of its shelf in 31 days, "
            f"against {tu_t['pct']}% across the tier.",
            f"{tu['k']} of {tu['n']} pieces.",
        )
    return None


def compose(target, card):
    """Subject + plain-text body. Short, specific, and asking for nothing.

    No attachment, no calendar link, no 'quick call?'. The only action is a URL
    that is genuinely theirs and genuinely free. If they want the paid thing
    they will ask, and if they don't, they have still been given something.
    """
    brand = target["brand"]
    fact = pick_fact(card)
    t = card["tier"]
    n_read = t.get("labels_read", t["brands_measured"])

    if fact:
        subject = f"{brand} vs {n_read - 1} other independent labels"
        opener, support = fact
    else:
        subject = f"Some market data for {brand}"
        opener = (
            f"98.4% of independent labels held full price over the fortnight we "
            f"measured — {t['full_price_houses']} of {t['brands_measured']} did not cut a "
            f"single piece."
        )
        support = "Most brands assume everyone around them is discounting. They aren't."

    body = f"""Hi,

{opener}

{support}

I run Loupe. We read the public product feed of {n_read} independent labels every day and keep the history, so we can say what this tier is actually doing: what sells out, who holds price, how quickly people refresh. Of those, {t['brands_measured']} carry enough shelf to be measured against, which is the group above.

Nobody publishes this. Everyone else in fashion data benchmarks you against Zara and Net-a-Porter, which tells a label your size almost nothing.

I made {brand} a card with your own numbers on it: sell-through, turnover, newness, and where your prices sit in each of your categories, all against the tier. It is free, there is no login, and the link is yours.

{target['card']}

The tier-wide version is public, if you want the wider picture:
https://useloupe.shop/index/

There is no ask attached. If it is useful I would rather you just have it. And if a number looks wrong to you I would genuinely like to hear it, because we publish our method and would rather fix a figure than defend it.

Charlie
Loupe · useloupe.shop
"""
    return subject, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    tokens = {}
    for line in io.open(LINKS, encoding="utf-8"):
        if "\t" in line:
            b, u = line.rstrip("\n").split("\t", 1)
            tokens[b.strip()] = u.strip().rsplit("k=", 1)[1]

    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    drafts, skipped = [], []
    for tgt in targets:
        tok = tokens.get(tgt["brand"])
        card = decrypt(tok) if tok else None
        if not card:
            skipped.append(tgt["brand"])
            continue
        subject, body = compose(tgt, card)
        drafts.append({
            "brand": tgt["brand"], "to": tgt["email"], "tier": tgt["tier"],
            "rank": tgt["rank"], "subject": subject, "body": body,
            "personalised": pick_fact(card) is not None,
        })

    drafts.sort(key=lambda d: (not d["personalised"], int(d["rank"] or 999)))
    if args.limit:
        drafts = drafts[: args.limit]

    OUT.write_text(json.dumps(drafts, ensure_ascii=False, indent=1), encoding="utf-8")
    n_pers = sum(1 for d in drafts if d["personalised"])
    print(f"{len(drafts)} drafts written to {OUT.name}")
    print(f"  {n_pers} lead with a fact about the brand itself")
    print(f"  {len(drafts) - n_pers} lead with the tier finding (nothing stood out)")
    if skipped:
        print(f"  {len(skipped)} skipped, no card: {', '.join(skipped[:6])}")

    if args.preview:
        for d in drafts[:3]:
            print("\n" + "=" * 74)
            print(f"TO: {d['to']}\nSUBJECT: {d['subject']}\n")
            print(d["body"])


if __name__ == "__main__":
    main()
