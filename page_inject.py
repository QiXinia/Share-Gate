"""Scripts injected into every shared browser tab.

The script runs in the page's own main world and is idempotent (safe to inject
on every navigation and on every client reconnect). It provides three things:

1. Conversation ownership / history isolation
   - Reports the conversation id opened in THIS tab to the backend (so the
     backend can attribute it to the logged-in user).
   - Hides sidebar history entries belonging to other users. Admins see all.

2. UI lockdown
   - Hides / blocks logout, settings, subscription/account entries and
     intercepts navigation to login / auth / account pages, so a guest can't
   log the shared account out or change its settings.

3. DOM-mirror collector (traffic-saving mode)
   - Serializes the computed CSS + a cloned body (resources rewritten to a
     placeholder handled by the backend /resource endpoint), and pushes
     throttled snapshots to the backend via the CDP Runtime binding __sgPush.

The backend injects this via Page.addScriptToEvaluateOnNewDocument and also
evaluates it once for the currently loaded document. Bindings used:
__sgPush (dom snapshots), __sgOwn (conversation attribution), __sgEvent.
"""
import json

# Words (zh/en) that identify lockdown-sensitive menu entries.
_LOGOUT_RE = r"log\s*out|sign\s*out|登\s*出|退出登录|注销"
_SETTINGS_RE = r"^\s*settings\s*$|^\s*设置\s*$"
_ACCOUNT_RE = (r"my\s*plan|manage\s*subscription|upgrade|switch\s*(account|workspace)|"
               r"套餐|升级|订阅|切换(账号|组织|工作区)|账号设置|管理账户")

# Hosts allowed through the resource relay (main + static/asset hosts).
RESOURCE_HOST_ALLOW = [
    "chatgpt.com", "oaistatic.com", "oaiusercontent.com", "openai.com",
    "gemini.google.com", "google.com", "gstatic.com", "googleusercontent.com",
    "googleapis.com", "accounts.google.com",
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
    return platform === 'gemini' ? 'a[href*="/app/"]' : 'a[href^="/c/"]';
  }
  function hideForeignHistory(root){
    if(isAdmin) return;
    var anchors = (root || document).querySelectorAll(historyAnchorSelector());
    for(var i=0;i<anchors.length;i++){
      var a = anchors[i];
      var id = idFromHref(a.getAttribute('href'));
      if(!id) continue;
      var box = a.closest('li') || a.closest('[role="listitem"]') ||
                a.parentElement || a;
      if(!owned.has(id)){
        box.setAttribute('data-sg-hidden','1');
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
        el.setAttribute('data-sg-lock','1');
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
  // 3. DOM-mirror collector
  // -------------------------------------------------------------------------
  function resUrl(u){
    try{
      if(!u || /^(data:|blob:|javascript:|#|mailto:|tel:)/.test(u)) return u;
      var abs = new URL(u, location.href).href;
      return '__SG_RES__' + abs;
    }catch(e){ return u; }
  }
  function rewriteUrlsInCss(css){
    return css.replace(/url\(\s*(['"]?)([^)'"]+)\1\s*\)/g, function(m,q,u){
      if(/^(data:|blob:)/.test(u)) return m;
      return 'url(' + q + resUrl(u) + q + ')';
    });
  }
  function collectCss(){
    var out = [];
    var sheets = document.styleSheets;
    for(var i=0;i<sheets.length;i++){
      var sh = sheets[i];
      try{
        if(sh.cssRules && sh.cssRules.length){
          var css = '';
          for(var j=0;j<sh.cssRules.length;j++) css += sh.cssRules[j].cssText + '\n';
          if(css) out.push(rewriteUrlsInCss(css));
        }
      }catch(e){
        // Cross-origin stylesheet: include it as a relayed <link>.
        if(sh.href) out.push('<link rel="stylesheet" href="' + resUrl(sh.href) + '">');
      }
    }
    return out;
  }
  function cloneBody(){
    var clone = document.body.cloneNode(true);
    // The mirror is read-only: never ship or execute target scripts.
    clone.querySelectorAll('script,noscript,iframe').forEach(function(n){
      n.parentNode && n.parentNode.removeChild(n);
    });
    // Do not transmit other users' history or locked UI entries at all.
    clone.querySelectorAll('[data-sg-hidden],[data-sg-lock]').forEach(function(n){
      n.parentNode && n.parentNode.removeChild(n);
    });
    var sel = 'img,source,video,audio,use,link,input,image';
    var nodes = clone.querySelectorAll(sel);
    for(var i=0;i<nodes.length;i++){
      var el = nodes[i];
      ['src','poster','href','xlink:href'].forEach(function(attr){
        var v = el.getAttribute(attr);
        if(v && !/^(data:|blob:|javascript:|#)/.test(v)){
          el.setAttribute(attr, resUrl(v));
        }
      });
      if(el.getAttribute('srcset')){
        el.setAttribute('srcset', el.getAttribute('srcset').split(',').map(function(part){
          var bits = part.trim().split(/\s+/);
          return resUrl(bits[0]) + (bits.length>1 ? ' ' + bits.slice(1).join(' ') : '');
        }).join(', '));
      }
      if(el.getAttribute('style') && el.getAttribute('style').indexOf('url(') !== -1){
        el.setAttribute('style', rewriteUrlsInCss(el.getAttribute('style')));
      }
    }
    clone.querySelectorAll('[style*="url("]').forEach(function(el){
      el.setAttribute('style', rewriteUrlsInCss(el.getAttribute('style')));
    });
    return clone.outerHTML;
  }

  var mirrorOn = false, cssSent = false, queued = false, lastSent = 0;
  var MIN_INTERVAL = 130;
  function flush(){
    queued = false;
    if(!mirrorOn || !document.body) return;
    lastSent = performance.now();
    var payload = {
      type:'dom',
      html: cloneBody(),
      base: location.href,
      scrollTop: Math.round(window.scrollY || document.documentElement.scrollTop || 0),
      scrollHeight: document.documentElement.scrollHeight,
      vw: window.innerWidth, vh: window.innerHeight
    };
    if(!cssSent){ payload.css = collectCss(); cssSent = true; }
    post('__sgPush', payload);
  }
  function schedule(){
    if(!mirrorOn) return;
    var wait = Math.max(0, MIN_INTERVAL - (performance.now() - lastSent));
    if(!queued){ queued = true; setTimeout(flush, wait); }
  }
  window.__sgMirrorStart = function(){
    if(mirrorOn) return;
    if(!document.documentElement){ setTimeout(window.__sgMirrorStart, 50); return; }
    mirrorOn = true;
    new MutationObserver(function(){
      schedule();
      scanLockdownDebounced();
      hideHistoryDebounced();
    }).observe(document.documentElement,
      {subtree:true, childList:true, attributes:true, characterData:true});
    window.addEventListener('scroll', schedule, {passive:true});
    window.addEventListener('resize', schedule, {passive:true});
    // Start with a couple of frames to catch late-rendered SPA content.
    flush();
    setTimeout(flush, 300);
    setTimeout(flush, 1000);
  };
  window.__sgMirrorOn = function(){ return mirrorOn; };
  window.__sgMirrorRequestFrame = function(){ schedule(); };

  var scanLockdownDebounced = debounce(function(){ scanLockdown(); }, 200);
  var hideHistoryDebounced = debounce(function(){ hideForeignHistory(); }, 200);

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
    try{
      applyGuards();
      // DOM mode starts the mirror automatically on every (re)load; stream
      // mode leaves it off to save bandwidth.
      if(CFG.mode === 'dom' && window.__sgMirrorStart){ window.__sgMirrorStart(); }
    }catch(e){ window.__sgErr = String(e && e.stack || e); }
    // Periodic safety net for SPA re-renders.
    setInterval(function(){
      try{
        applyGuards();
        if(CFG.mode === 'dom' && window.__sgMirrorStart && !window.__sgMirrorOn())
          window.__sgMirrorStart();
      }catch(e){ window.__sgErr = String(e && e.stack || e); }
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
    cfg = {
        "platform": platform,
        "owned": list(owned_ids or []),
        "isAdmin": bool(is_admin),
        "lockUI": bool(lock_ui),
        "mode": mode if mode in ("dom", "stream") else "dom",
    }
    js = JS.replace("__SG_CONFIG__", json.dumps(cfg))
    js = js.replace("__LOGOUT_RE__", _LOGOUT_RE)
    js = js.replace("__SETTINGS_RE__", _SETTINGS_RE)
    js = js.replace("__ACCOUNT_RE__", _ACCOUNT_RE)
    return js
