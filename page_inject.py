"""Scripts injected into every shared browser tab.

The script runs in the page's own main world and is idempotent (safe to inject
on every navigation and on every client reconnect). It provides the *policy*
layer; the actual DOM mirroring is done by the vendored PhantomStream capture
(see phantom_inject.py).

1. Conversation ownership / history isolation
   - Reports the conversation id opened in THIS tab to the backend (so the
     backend can attribute it to the logged-in user).
   - Marks sidebar history entries belonging to other users with
     ``data-sg-hidden`` (and hides them). Admins see all. The PhantomStream
     capture uses ``skipElement`` to drop these subtrees from snapshots and
     diffs, so other users' conversations never leave the browser.

2. UI lockdown
   - Marks logout / settings / subscription / account entries with
     ``data-sg-lock`` (also dropped from the mirror) and intercepts
     navigation to login / auth / account pages, so a guest can't log the
     shared account out or change its settings.

The backend injects this via Page.addScriptToEvaluateOnNewDocument and also
evaluates it once for the currently loaded document. Bindings used:
__sgOwn (conversation attribution), __sgEvent (blocked-action notices).
"""
import json

# Words (zh/en) that identify lockdown-sensitive menu entries.
_LOGOUT_RE = r"log\s*out|sign\s*out|登\s*出|退出登录|注销"
_SETTINGS_RE = r"^\s*settings\s*$|^\s*设置\s*$"
_ACCOUNT_RE = (r"my\s*plan|manage\s*subscription|upgrade|switch\s*(account|workspace)|"
               r"套餐|升级|订阅|会员|开通|充值|续费|切换(账号|组织|工作区)|账号设置|管理账户")

# Hosts allowed through the resource relay (main + static/asset hosts).
RESOURCE_HOST_ALLOW = [
    "chatgpt.com", "oaistatic.com", "oaiusercontent.com", "openai.com",
    "gemini.google.com", "google.com", "gstatic.com", "googleusercontent.com",
    "googleapis.com", "accounts.google.com",
    # Kimi (Moonshot AI): main site (same-origin _next/static assets) and the
    # image/file CDN. api.moonshot.cn is intentionally NOT allowed (not a
    # renderable sub-resource).
    "kimi.com", "kimi-img.moonshot.cn",
]

JS = r"""
(function(){
  if (window.__SG_INSTALLED__) return;
  window.__SG_INSTALLED__ = true;
  var CFG = __SG_CONFIG__;
  var platform = CFG.platform || 'chatgpt';
  var isAdmin = !!CFG.isAdmin;
  var owned = new Set(CFG.owned || []);
  var lockUI = CFG.lockUI !== false;

  function post(name, data){
    try { if (typeof window[name] === 'function') window[name](JSON.stringify(data)); }
    catch(e){}
  }
  function debounce(fn, ms){
    var t=null;
    return function(){ if(t) clearTimeout(t); t=setTimeout(function(){ t=null; fn(); }, ms); };
  }

  // -------------------------------------------------------------------------
  // 1. Conversation ownership + history isolation
  // -------------------------------------------------------------------------
  var idRe = platform === 'gemini'
      ? /\/app\/([0-9A-Za-z_\-]+)/
      : platform === 'kimi'
      ? /\/chat\/([0-9A-Za-z_\-]+)/
      : /\/c\/([0-9A-Za-z_\-]+)/;
  function idFromHref(h){
    if(!h) return null;
    var m = String(h).match(idRe);
    return m ? m[1] : null;
  }
  function currentId(){
    var m = location.pathname.match(idRe);
    return m ? m[1] : null;
  }
  function reportCurrent(){
    var id = currentId();
    if(id && !owned.has(id)){
      owned.add(id);
      post('__sgOwn', {id:id, platform:platform});
    }
  }

  function historyAnchorSelector(){
    if (platform === 'gemini') return 'a[href*="/app/"]';
    if (platform === 'kimi') return 'a[href*="/chat/"]';
    return 'a[href^="/c/"]';
  }
  function hideForeignHistory(root){
    if(isAdmin) return;
    var anchors = (root || document).querySelectorAll(historyAnchorSelector());
    for(var i=0;i<anchors.length;i++){
      var a = anchors[i];
      var id = idFromHref(a.getAttribute('href'));
      if(!id) continue;
      // Prefer the real conversation row container. When the site does not
      // wrap items in <li>/listitem, fall back to the anchor itself rather
      // than its parentElement: several entries can share one parent, and
      // hiding that parent would wrongly hide other users' *and* our own
      // conversations in the same group.
      var box = a.closest('li') || a.closest('[role="listitem"]') || a;
      if(!owned.has(id)){
        if(box.getAttribute('data-sg-hidden') !== '1'){
          box.setAttribute('data-sg-hidden','1');
        }
        box.style.setProperty('display','none','important');
      } else if(box.getAttribute('data-sg-hidden')){
        box.removeAttribute('data-sg-hidden');
        box.style.removeProperty('display');
      }
    }
  }
  window.__sgSetOwned = function(arr){
    owned = new Set(arr || []);
    hideForeignHistory();
  };

  // -------------------------------------------------------------------------
  // 2. UI lockdown
  // -------------------------------------------------------------------------
  var logoutRe = /__LOGOUT_RE__/i;
  var settingsRe = /__SETTINGS_RE__/i;
  var accountRe = /__ACCOUNT_RE__/i;
  function menuLike(el){
    return !!(el && el.closest && el.closest(
      '[role="menu"],[role="dialog"],[role="navigation"],dialog,[data-testid*="menu"],[class*="menu"]'));
  }
  function scanLockdown(root){
    if(!lockUI) return;
    var nodes = (root || document).querySelectorAll(
      'a,button,[role="menuitem"],[role="link"]');
    for(var i=0;i<nodes.length;i++){
      var el = nodes[i];
      var text = (el.innerText || el.textContent || '').trim();
      var href = el.getAttribute('href') || '';
      var label = (el.getAttribute('aria-label') || '') + ' ' +
                  (el.getAttribute('data-testid') || '');
      var bad = false;
      if(/logout|signout|auth\/log/i.test(href)) bad = true;
      if(logoutRe.test(text) || logoutRe.test(label)) bad = true;
      if(menuLike(el) && (settingsRe.test(text) || accountRe.test(text))) bad = true;
      // The settings cog in the sidebar / chat header.
      if(/settings|设置/i.test(label) && el.closest('button,a,[role="button"]')) bad = true;
      if(bad){
        if(el.getAttribute('data-sg-lock') !== '1'){
          el.setAttribute('data-sg-lock','1');
        }
        el.style.setProperty('display','none','important');
      }
    }
  }
  // Block clicks on logout/auth links (capture phase, before navigation).
  document.addEventListener('click', function(e){
    if(!lockUI) return;
    var el = e.target && e.target.closest ? e.target.closest('a,button,[role="menuitem"]') : null;
    if(!el) return;
    var href = el.getAttribute('href') || '';
    var text = (el.innerText || el.textContent || '');
    if(/logout|signout|\/auth\/log/i.test(href) || logoutRe.test(text)){
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation && e.stopImmediatePropagation();
      post('__sgEvent', {kind:'blocked', what:'logout'});
    }
  }, true);

  // URL guard: stop SPA navigations / redirects to login/account pages.
  var BAD_PATH = /\/auth\/(login|logout)|\/account|\/settings|\/accounts|signin|signup/i;
  function guardNav(){
    if(lockUI && BAD_PATH.test(location.pathname)){
      post('__sgEvent', {kind:'blocked', what:'nav', to:location.pathname});
      // Back to the safe root for this platform.
      var safe = platform === 'gemini' ? '/app' : '/';
      try{ history.replaceState(null,'',safe); }catch(e){}
      location.replace(safe);
    }
  }
  ['pushState','replaceState'].forEach(function(fn){
    var orig = history[fn];
    history[fn] = function(){
      var r = orig.apply(this, arguments);
      setTimeout(function(){ guardNav(); reportCurrent(); }, 30);
      return r;
    };
  });
  window.addEventListener('popstate', guardNav);

  // Static lockdown CSS (hard-coded fast path). At document_start the
  // document element may not exist yet, so mount with retry.
  if(lockUI){
    var st = document.createElement('style');
    st.setAttribute('data-sg','lock');
    st.textContent =
      'a[href*="logout"],a[href*="signout"],a[href*="/auth/logout"]{display:none !important;}';
    (function mountStyle(){
      var host = document.head || document.documentElement;
      if (host) { host.appendChild(st); }
      else { setTimeout(mountStyle, 10); }
    })();
  }

  // -------------------------------------------------------------------------
  // Keep isolation/lockdown markers fresh as the SPA re-renders. A light
  // observer (no serialization) re-runs the two policies; the vendored
  // PhantomStream capture reads the resulting data-sg-* markers.
  // -------------------------------------------------------------------------
  var scanLockdownDebounced = debounce(function(){ scanLockdown(); }, 200);
  var hideHistoryDebounced = debounce(function(){ hideForeignHistory(); }, 200);
  function refreshPolicies(){
    scanLockdownDebounced();
    hideHistoryDebounced();
  }
  (function observe(){
    function attach(){
      if(!document.documentElement){ setTimeout(attach, 10); return; }
      new MutationObserver(refreshPolicies).observe(document.documentElement,
        {subtree:true, childList:true, attributes:true, characterData:true});
    }
    attach();
  })();

  // -------------------------------------------------------------------------
  // Boot
  // -------------------------------------------------------------------------
  function applyGuards(){
    reportCurrent();
    hideForeignHistory();
    scanLockdown();
    guardNav();
  }
  function boot(){
    try{ applyGuards(); }
    catch(e){ window.__sgErr = String(e && e.stack || e); }
    // Periodic safety net for SPA re-renders.
    setInterval(function(){
      try{ applyGuards(); }catch(e){ window.__sgErr = String(e && e.stack || e); }
    }, 1500);
  }
  // Diagnostics hook (also used by the host to re-run guards).
  window.__sgRunGuards = function(){
    try{ applyGuards(); return 'ok'; }
    catch(e){ return 'ERR:' + String(e && e.stack || e); }
  };
  window.__sgCfg = CFG;
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
"""


def build_inject_script(platform, owned_ids, is_admin=False, lock_ui=True,
                        mode="dom"):
    # `mode` is accepted for call-site compatibility; the policy layer runs in
    # both mirror modes.
    cfg = {
        "platform": platform,
        "owned": list(owned_ids or []),
        "isAdmin": bool(is_admin),
        "lockUI": bool(lock_ui),
    }
    js = JS.replace("__SG_CONFIG__", json.dumps(cfg))
    js = js.replace("__LOGOUT_RE__", _LOGOUT_RE)
    js = js.replace("__SETTINGS_RE__", _SETTINGS_RE)
    js = js.replace("__ACCOUNT_RE__", _ACCOUNT_RE)
    return js
