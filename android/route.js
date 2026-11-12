/* Loupe: send Android visitors to the Android download instead of the App Store.
 *
 * Every page on useloupe.shop links "Get the app" to the iPhone App Store. On an
 * Android phone that is a dead end. This script, included on every page, does
 * two things ON ANDROID ONLY (iPhone and desktop are untouched):
 *
 *   1. Click delegation: any tap on a link to the Loupe App Store listing goes to
 *      /android/ instead. Delegation (not rewriting hrefs once) also covers the
 *      buttons that /u/, /look/ and the 404 share page build with JS after load.
 *   2. Relabels those links ("Get Loupe on the App Store" -> "Get Loupe for
 *      Android"), including ones added later, via a MutationObserver.
 *
 * Kept dependency-free and tiny; safe to include more than once.
 */
(function () {
  "use strict";
  if (window.__loupeAndroidRoute) return;
  window.__loupeAndroidRoute = true;

  var ua = navigator.userAgent || "";
  if (!/Android/i.test(ua)) return;
  document.documentElement.className += " loupe-android";

  var ANDROID_URL = "/android/";
  var STORE_RE = /^https?:\/\/apps\.apple\.com\/[^?#]*id6781137336/i;

  function isStoreLink(a) {
    return a && a.tagName === "A" && STORE_RE.test(a.getAttribute("href") || "");
  }

  var LABELS = [
    [/Get Loupe on the App Store/g, "Get Loupe for Android"],
    [/on the App Store/g, "for Android"],
    [/App Store/g, "Android app"],
    [/iPhone app/g, "Android app"],
    [/Keep swiping in the app/g, "Get Loupe for Android"]
  ];

  function relabel(a) {
    if (a.__loupeRelabelled) return;
    a.__loupeRelabelled = true;
    a.setAttribute("href", ANDROID_URL);
    a.removeAttribute("target");
    for (var i = 0; i < a.childNodes.length; i++) {
      var n = a.childNodes[i];
      if (n.nodeType !== 3) continue;
      var t = n.nodeValue;
      for (var j = 0; j < LABELS.length; j++) t = t.replace(LABELS[j][0], LABELS[j][1]);
      n.nodeValue = t;
    }
  }

  function sweep(root) {
    if (!root || !root.querySelectorAll) return;
    if (isStoreLink(root)) relabel(root);
    var links = root.querySelectorAll('a[href*="apps.apple.com"]');
    for (var i = 0; i < links.length; i++) if (isStoreLink(links[i])) relabel(links[i]);
  }

  document.addEventListener(
    "click",
    function (e) {
      var el = e.target;
      while (el && el !== document) {
        if (isStoreLink(el)) {
          e.preventDefault();
          window.location.href = ANDROID_URL;
          return;
        }
        el = el.parentNode;
      }
    },
    true
  );

  function start() {
    sweep(document.body);
    if (window.MutationObserver) {
      new MutationObserver(function (records) {
        for (var i = 0; i < records.length; i++) {
          var added = records[i].addedNodes;
          for (var j = 0; j < added.length; j++) if (added[j].nodeType === 1) sweep(added[j]);
        }
      }).observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
