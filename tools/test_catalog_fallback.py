"""Offline test: the product-page builder survives a jsDelivr outage.

    python tools/test_catalog_fallback.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_product_pages as b  # noqa: E402

JSD = "https://cdn.jsdelivr.net/gh/HOboGoblin45/loupe-feed@main/loupe-feed/catalog.json"
RAW = "https://raw.githubusercontent.com/HOboGoblin45/loupe-feed/main/loupe-feed/catalog.json"
checks = 0


def ok(cond, msg):
    global checks
    checks += 1
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


ok(b.mirror_urls(JSD) == [JSD, RAW], "jsDelivr URL gets its raw GitHub twin")
ok(b.mirror_urls("https://example.com/c.json") == ["https://example.com/c.json"], "other URLs stay alone")

calls = []


def jsd_down(url):
    calls.append(url)
    if "jsdelivr" in url:
        raise OSError("HTTP Error 503: first byte timeout")
    return {"products": [1]}


ok(b.load_catalog(JSD, fetch=jsd_down) == {"products": [1]}, "falls back to raw GitHub")
ok(calls == [JSD, JSD, RAW], f"retries jsDelivr once, then raw: {calls}")

calls.clear()


def flaky(url):
    calls.append(url)
    if len(calls) == 1:
        raise OSError("reset")
    return {"ok": True}


ok(b.load_catalog(JSD, fetch=flaky) == {"ok": True}, "a single blip is retried on the same mirror")
ok(calls == [JSD, JSD], f"no fallback needed after a good retry: {calls}")


def all_down(url):
    raise OSError("down")


try:
    b.load_catalog(JSD, fetch=all_down)
    ok(False, "all mirrors down must raise")
except RuntimeError as e:
    ok("raw.githubusercontent.com" in str(e) and "jsdelivr" in str(e), "error names every mirror tried")

print(f"PASS: {checks} checks (catalog fallback)")
