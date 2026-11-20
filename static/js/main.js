// ═══════════════════════════════════════════
//  ZURI V3 — MAIN JS
// ═══════════════════════════════════════════

// ── Flash auto-dismiss ──
document.querySelectorAll('.flash').forEach(f => {
  setTimeout(() => { f.style.animation = 'fadeSlideDown .3s reverse forwards'; setTimeout(()=>f.remove(),300); }, 4000);
});

// ── Scroll reveal ──
const revealIO = new IntersectionObserver(entries => {
  entries.forEach(e => { if(e.isIntersecting) e.target.classList.add('visible'); });
}, { threshold: 0.1, rootMargin: '0px 0px -30px 0px' });
document.querySelectorAll('.reveal').forEach(el => revealIO.observe(el));

// ── Password toggle ──
const ICON_ATTRS = 'width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
const EYE_ICON     = `<svg ${ICON_ATTRS}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
const EYE_OFF_ICON = `<svg ${ICON_ATTRS}><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
window.togglePw = function(id, btn) {
  const inp = document.getElementById(id);
  if (!inp) return;
  inp.type = inp.type === 'password' ? 'text' : 'password';
  btn.innerHTML = inp.type === 'password' ? EYE_ICON : EYE_OFF_ICON;
};

// ── Toast ──
window.showToast = function(msg, type = 'success') {
  const existing = document.querySelector('.toast-msg');
  if(existing) existing.remove();
  const t = document.createElement('div');
  t.className = `flash flash-${type} toast-msg`;
  t.style.cssText = 'position:fixed;bottom:calc(var(--nav-h,64px) + 16px);left:50%;transform:translateX(-50%);z-index:999;min-width:260px;max-width:90vw;animation:fadeSlideIn .3s ease';
  t.innerHTML = `<span>${msg}</span><button onclick="this.parentElement.remove()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>`;
  document.body.appendChild(t);
  setTimeout(() => { t.style.animation='fadeSlideDown .3s reverse forwards'; setTimeout(()=>t.remove(),300); }, 3500);
};

// ── Number counter animation ──
window.animateCount = function(el, target, prefix='', suffix='', decimals=2) {
  const dur = 1000;
  const start = performance.now();
  const from = parseFloat(el.textContent.replace(/[^0-9.]/g,'')) || 0;
  function step(now) {
    const p = Math.min((now-start)/dur,1);
    const ease = 1-Math.pow(1-p,3);
    const val = from + (target-from)*ease;
    el.textContent = prefix + val.toFixed(decimals) + suffix;
    if(p<1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
};

// ── Bottom nav active state ──
(function() {
  const path = window.location.pathname;
  document.querySelectorAll('.bnav-item').forEach(item => {
    const href = item.getAttribute('href');
    if(href && (path === href || (href !== '/' && path.startsWith(href)))) {
      item.classList.add('active');
    }
  });
})();

// ── Admin sidebar ──
const adminMenuBtn = document.getElementById('adminMenuBtn');
const adminSidebar = document.getElementById('adminSidebar');
const adminOverlay = document.getElementById('adminOverlay');
if(adminMenuBtn) {
  adminMenuBtn.addEventListener('click', () => {
    adminSidebar.classList.toggle('open');
    if(adminOverlay) adminOverlay.classList.toggle('active');
  });
}
if(adminOverlay) {
  adminOverlay.addEventListener('click', () => {
    adminSidebar.classList.remove('open');
    adminOverlay.classList.remove('active');
  });
}

// ── Live price ticker fetch (CoinGecko free API) ──
window.fetchLivePrices = async function() {
  try {
    const ids = 'bitcoin,ethereum,tether,binancecoin,solana,ripple,dogecoin,tron,cardano,matic-network';
    const r = await fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${ids}&vs_currencies=usd&include_24hr_change=true`);
    const data = await r.json();
    const map = {
      bitcoin:'BTC', ethereum:'ETH', tether:'USDT',
      binancecoin:'BNB', solana:'SOL', ripple:'XRP',
      dogecoin:'DOGE', tron:'TRX', cardano:'ADA',
      'matic-network':'MATIC'
    };
    const prices = {};
    for(const [id, sym] of Object.entries(map)) {
      if(data[id]) {
        prices[sym] = data[id].usd;
      }
    }
    // Update price elements on page
    document.querySelectorAll('[data-price-sym]').forEach(el => {
      const sym = el.dataset.priceSym;
      if(prices[sym]) el.textContent = '$' + prices[sym].toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:6});
    });
    document.querySelectorAll('[data-change-sym]').forEach(el => {
      const sym = el.dataset.changeSym;
      const id = Object.keys(map).find(k=>map[k]===sym);
      if(id && data[id]) {
        const chg = data[id].usd_24h_change || 0;
        el.textContent = (chg>=0?'+':'')+chg.toFixed(2)+'%';
        el.className = el.className.replace(/\b(up|down)\b/g,'') + (chg>=0?' up':' down');
      }
    });
    // Send updated prices to backend
    const csrf = document.querySelector('meta[name=csrf-token]')?.content || '';
    fetch('/api/prices', {
      method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:JSON.stringify(prices)
    }).catch(()=>{});
    return prices;
  } catch(e) {
    console.warn('Price fetch failed:', e);
  }
};

// Fetch on load, then every 30s
if(document.querySelector('[data-price-sym]') || document.querySelector('[data-change-sym]')) {
  window.fetchLivePrices();
  setInterval(window.fetchLivePrices, 30000);
}

// ── Crypto converter (instant) ──
window.calcConvert = function(fromVal, fromSym, toSym, prices) {
  if(!fromVal || !prices) return 0;
  const fromP = prices[fromSym] || 1;
  const toP   = prices[toSym]   || 1;
  return ((parseFloat(fromVal) * fromP) / toP).toFixed(8);
};

// ── QR placeholder grid ──

// ── Light / dark theme ──
(function() {
  const button = document.getElementById('themeToggle');
  if (!button) return;
  const icons = {
    light: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>',
    dark: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.9 13A8.5 8.5 0 0 1 11 3.1 8.5 8.5 0 1 0 20.9 13Z"/></svg>'
  };
  function render() {
    const dark = document.documentElement.dataset.theme === 'dark';
    button.innerHTML = dark ? icons.light : icons.dark;
    button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    button.setAttribute('title', dark ? 'Switch to light theme' : 'Switch to dark theme');
  }
  render();
  button.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('zuri-theme', theme); } catch (_) {}
    render();
  });
})();
