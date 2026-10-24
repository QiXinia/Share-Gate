"""Build the PhantomStream capture script injected into shared browser tabs.

This vendors the prebuilt, self-contained *classic* capture artifact from
PhantomStream (MIT, https://github.com/fullselfbrowsing/PhantomStream), located
at ``vendor/phantom-stream/playwright-inject.js``. It performs:

  * one style-inlined DOM snapshot, then only incremental MutationObserver
    diffs (stable node ids in a sidecar), so the viewer receives small frames
    instead of the whole page on every change;
  * sandboxed reconstruction on the viewer (an ``allow-same-origin`` iframe
    with no scripts) plus a remote-control channel.

We adapt it to Share-Gate by text-replacing two placeholders:

  * ``PHANTOM_STREAM_BRIDGE_TOKEN`` — a shared secret echoed in every
    ``__phantomStreamBridge`` binding call so the backend can trust frames;
  * ``PHANTOM_STREAM_CAPTURE_OPTIONS`` — capture options, expressed as real
    JavaScript (functions, not JSON, because the two seams we need are
    predicates/redactors):

      - ``skipElement`` excludes conversation history belonging to other
        users and the locked logout/settings UI (marked ``data-sg-hidden`` /
        ``data-sg-lock`` by page_inject.py) from BOTH snapshots and diffs.

    Sub-resource URL rewriting (img/video/css/font/... -> the same-origin
    ``/resource`` relay, so the cookie-less viewer loads media through the
    shared logged-in browser) is NOT done here: the checked-in artifact
    predates the upstream ``maskAssetUrlFn`` seam. It is performed on the
    backend (see ``PhantomSession._rewrite_asset_urls``) over every static-CDN
    URL in snapshots and diffs, which is field-agnostic and therefore more
    robust than the capture-side hook.

The relay origin is read live from ``window.__SG_RELAY_ORIGIN__`` (set by the
backend from the viewer's Origin header) so the same script works regardless
of the LAN host / domain the visitor uses.
"""
import os

_VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "vendor", "phantom-stream")
_INJECT_PATH = os.path.join(_VENDOR_DIR, "playwright-inject.js")

_TOKEN_PLACEHOLDER = 'var PHANTOM_STREAM_BRIDGE_TOKEN = "";'
_OPTIONS_PLACEHOLDER = 'var PHANTOM_STREAM_CAPTURE_OPTIONS = {};'

# The capture artifact calls ``window.__phantomStreamBridge(messageObject)``
# with a structured object. The native CDP ``Runtime.addBinding`` only forwards
# a *single string* argument to the host (an object argument is silently
# dropped), so we register the binding under this raw name and install a tiny
# page-side shim (see build_origin_prefix) that JSON-stringifies before the
# crossing.
RAW_BRIDGE = "__phantomStreamBridgeRaw"

with open(_INJECT_PATH, "r", encoding="utf-8") as _f:
    _TEMPLATE = _f.read()


def build_phantom_script(platform, token):
    """Return the capture source for *platform*, authenticated with *token*.

    The returned string is passed to both
    ``Page.addScriptToEvaluateOnNewDocument`` and a one-shot
    ``Runtime.evaluate``. The relay origin prefix is prepended (it runs before
    the vendored IIFE's injection guard) so it is refreshed even when the
    capture core itself is already installed on the document.
    """
    # NOTE: the checked-in playwright-inject.js artifact (v0.2.1, built from
    # an earlier capture snapshot) exposes `skipElement`, `styleMode`, masking
    # and selector options but does NOT bundle the newer `maskAssetUrlFn` seam
    # present in src/capture/index.js. Sub-resource URL rewriting is therefore
    # performed on the backend (PhantomSession._rewrite_asset_urls), which
    # rewrites every static-CDN URL carried in snapshots and diffs to the
    # same-origin /resource relay regardless of which wire field it sits in.
    options = """{
  styleMode: 'computed',
  skipElement: function (el) {
    try {
      return !!(el && el.closest && el.closest('[data-sg-hidden],[data-sg-lock]'));
    } catch (e) { return false; }
  }
}"""

    src = _TEMPLATE.replace(_TOKEN_PLACEHOLDER,
                            'var PHANTOM_STREAM_BRIDGE_TOKEN = "%s";' % token, 1)
    if _OPTIONS_PLACEHOLDER not in src:
        raise RuntimeError("PhantomStream capture-options placeholder not found")
    src = src.replace(_OPTIONS_PLACEHOLDER,
                      'var PHANTOM_STREAM_CAPTURE_OPTIONS = %s;' % options, 1)
    return src


def build_origin_prefix(origin):
    """A prelude that runs before the vendored capture IIFE.

    It publishes the viewer's same-origin relay base and installs the
    object->string bridge shim expected by the capture artifact.
    """
    return (
        "window.__SG_RELAY_ORIGIN = %s;"
        "window.__phantomStreamBridge = function (m){"
        "try{window.%s(JSON.stringify(m));}catch(e){}};"
        % (_js_string(origin or ""), RAW_BRIDGE)
    )


def _js_string(s):
    # json.dumps produces a safe, quoted JS string literal.
    import json
    return json.dumps(s)
