// DriftSync UI: theme switch and depth effects. Nothing here changes the timer or the blocking.
//   Themes: "studio-night" (default since 2026-11-22: dark, flat, professional), "studio" (its light twin),
//   "bloom" (magenta / marigold / teal from Kiran's wallpaper), "matte" (Bloom toned down, no glow), "nocturne" (navy + soft gradient)
//   and "graphite" (quiet charcoal).
//   The choice is saved in prefs.json through the app (get_pref / set_pref "theme"), with a localStorage copy
//   so pages paint in the right theme straight away. Any .theme-switch [data-theme-set] button switches it.
(function () {
    const THEMES = ["studio", "studio-night", "bloom", "matte", "nocturne", "graphite"];
    const root = document.documentElement;

    // Lite mode for low-power laptops: 4 or fewer CPU threads, 4 GB RAM or less, or reduced motion asked for.
    // localStorage "ds-lite" = "on" / "off" overrides the guess.
    let liteSetting = null;
    try { liteSetting = localStorage.getItem('ds-lite'); } catch (e) {}
    const weak = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory && navigator.deviceMemory <= 4)
        || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    window.DS_LITE = liteSetting === "on" || (liteSetting !== "off" && !!weak);
    root.classList.toggle('ds-lite', window.DS_LITE);

    // Nothing animates while the window is hidden or minimised
    const onVisibility = () => root.classList.toggle('ds-paused', document.hidden);
    document.addEventListener('visibilitychange', onVisibility);
    onVisibility();
    const valid = t => THEMES.includes(t) ? t : null;
    function stored() { try { return valid(localStorage.getItem('ds-theme')); } catch (e) { return null; } }
    function apply(t) {
        t = valid(t) || "studio-night";
        if (t === "nocturne") root.removeAttribute('data-theme'); else root.setAttribute('data-theme', t);
        try { localStorage.setItem('ds-theme', t); } catch (e) {}
        document.querySelectorAll('[data-theme-set]').forEach(b => {
            const on = b.dataset.themeSet === t;
            b.classList.toggle('is-on', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        return t;
    }
    // Insights opens in the browser: Python writes the saved theme into <html data-theme> there
    const preset = valid(root.getAttribute('data-theme'));
    // Studio Night became the default on 2026-11-22: switch everyone to it once, after that their own choice sticks
    const THEME_VERSION = "5";
    let fresh = false;
    try { fresh = localStorage.getItem('ds-theme-v') !== THEME_VERSION; localStorage.setItem('ds-theme-v', THEME_VERSION); } catch (e) {}
    apply(preset || (fresh ? "studio-night" : stored()) || "studio-night");

    window.dsSetTheme = function (t) {
        if ((valid(t) || "studio-night") === (root.getAttribute('data-theme') || "nocturne")) return;
        // Crossfade the whole window between themes where the WebView supports it, otherwise ease the colours
        if (document.startViewTransition && !window.DS_LITE) {
            document.startViewTransition(() => { t = apply(t); });
        } else {
            root.classList.add('ds-theme-anim');
            t = apply(t);
            setTimeout(() => root.classList.remove('ds-theme-anim'), 500);
        }
        try { window.pywebview.api.set_pref("theme", valid(t) || "studio-night"); } catch (e) {}
    };
    let synced = false;
    async function syncFromApp() {
        if (synced) return;
        try {
            const api = window.pywebview.api;
            const version = await api.get_pref("themeVersion");
            synced = true;
            if (String(version) !== THEME_VERSION) {          // first run with Studio: switch to it once
                api.set_pref("themeVersion", THEME_VERSION);
                api.set_pref("theme", "studio-night");
                apply("studio-night");
                return;
            }
            const t = valid(await api.get_pref("theme"));
            if (t) apply(t);
        } catch (e) {}
    }
    window.addEventListener('pywebviewready', syncFromApp);
    setTimeout(syncFromApp, 300);
    document.addEventListener('click', e => {
        const b = e.target.closest('[data-theme-set]');
        if (b) window.dsSetTheme(b.dataset.themeSet);
    });
    document.addEventListener('DOMContentLoaded', () => apply(root.getAttribute('data-theme') || "nocturne"));
})();

// Depth effects. Purely visual.
//   [data-tilt]       the card leans a few degrees toward the pointer (sets --rx / --ry)
//   [data-tilt="6"]   custom maximum angle in degrees
//   #timerWrap        the 3D timer leans toward the pointer anywhere on the page
// Turned off in lite mode (see above).
(function () {
    if (window.DS_LITE) return;   // lite mode: no pointer tracking at all

    function bindTilt(el) {
        if (el.__tilt) return;
        el.__tilt = true;
        const max = parseFloat(el.dataset.tilt) || 3;
        let raf = 0;
        el.addEventListener('pointermove', e => {
            const r = el.getBoundingClientRect();
            const x = (e.clientX - r.left) / r.width - 0.5;
            const y = (e.clientY - r.top) / r.height - 0.5;
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                el.classList.add('is-tilting');
                el.style.setProperty('--rx', (-y * max).toFixed(2) + 'deg');
                el.style.setProperty('--ry', (x * max).toFixed(2) + 'deg');
            });
        });
        el.addEventListener('pointerleave', () => {
            cancelAnimationFrame(raf);
            el.classList.remove('is-tilting');
            el.style.setProperty('--rx', '0deg');
            el.style.setProperty('--ry', '0deg');
        });
    }

    function init() {
        document.querySelectorAll('[data-tilt]').forEach(bindTilt);

        const timer = document.getElementById('timerWrap');
        if (timer) {
            let raf = 0;
            document.addEventListener('pointermove', e => {
                const r = timer.getBoundingClientRect();
                const x = (e.clientX - (r.left + r.width / 2)) / window.innerWidth;
                const y = (e.clientY - (r.top + r.height / 2)) / window.innerHeight;
                cancelAnimationFrame(raf);
                raf = requestAnimationFrame(() => {
                    timer.style.setProperty('--rx', (-y * 14).toFixed(2) + 'deg');
                    timer.style.setProperty('--ry', (x * 14).toFixed(2) + 'deg');
                });
            });
            document.addEventListener('pointerleave', () => {
                timer.style.setProperty('--rx', '0deg');
                timer.style.setProperty('--ry', '0deg');
            });
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();


// Page transitions. DriftSync is several pages, so moving between them is a real page load; this makes it feel like
// one app: the sidebar stays still and only the page content animates out (about 0.2 s) and in (about 0.45 s).
//   Styles (picked in Setup > Appearance, saved as pref "transition"):
//     fade   plain crossfade            slide  slides sideways, direction follows the sidebar order
//     depth  zooms in from behind (3D)  rise   rises up out of a soft blur (no blur in lite mode)
//   dsGo("page.html") navigates with the transition; plain <a href="x.html"> links get it automatically.
(function () {
    const STYLES = ["fade", "slide", "depth", "rise"];
    const ORDER = ["login.html", "index.html", "setup.html", "timetable.html"];
    const LEAVE_MS = 190;
    const root = document.documentElement;
    const valid = t => STYLES.includes(t) ? t : null;
    const page = () => (location.pathname.split('/').pop() || "").toLowerCase();

    function setStyle(t) {
        t = valid(t) || "depth";
        root.dataset.transition = t;
        try { localStorage.setItem('ds-transition', t); } catch (e) {}
        document.querySelectorAll('[data-transition-set]').forEach(b => {
            const on = b.dataset.transitionSet === t;
            b.classList.toggle('is-on', on);
            b.classList.toggle('is-selected', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        return t;
    }
    let saved = null;
    try { saved = valid(localStorage.getItem('ds-transition')); } catch (e) {}
    setStyle(saved);

    // Entering: which way did we come from? (slide uses it)
    let dir = "fwd";
    try { dir = sessionStorage.getItem('ds-dir') || "fwd"; sessionStorage.removeItem('ds-dir'); } catch (e) {}
    root.dataset.dir = dir;
    function playEnter() {
        root.classList.remove('ds-entering');
        void root.offsetWidth;            // restart the animation
        root.classList.add('ds-entering');
        clearTimeout(playEnter.t);
        // remove the class once done, so the page has no leftover transform (fixed popups need that)
        playEnter.t = setTimeout(() => root.classList.remove('ds-entering'), 750);
    }
    playEnter();

    let leaving = false;
    window.dsGo = function (url) {
        if (leaving) return;
        leaving = true;
        const from = ORDER.indexOf(page()), to = ORDER.indexOf(String(url).split(/[?#]/)[0].toLowerCase());
        try { sessionStorage.setItem('ds-dir', from >= 0 && to >= 0 && to < from ? "back" : "fwd"); } catch (e) {}
        root.dataset.dir = from >= 0 && to >= 0 && to < from ? "back" : "fwd";
        root.classList.remove('ds-entering');
        root.classList.add('ds-leaving');
        setTimeout(() => { window.location.href = url; }, LEAVE_MS);
        setTimeout(() => { leaving = false; root.classList.remove('ds-leaving'); }, 3000);   // navigation was cancelled
    };
    window.dsSetTransition = function (t) {
        t = setStyle(t);
        playEnter();                       // preview it on the current page
        try { window.pywebview.api.set_pref("transition", t); } catch (e) {}
    };
    window.addEventListener('pageshow', () => { root.classList.remove('ds-leaving'); leaving = false; });

    // Ordinary links between pages (bubbling, so Level 3's lock on the timer page still wins: it stops these clicks)
    document.addEventListener('click', e => {
        const pick = e.target.closest('[data-transition-set]');
        if (pick) { window.dsSetTransition(pick.dataset.transitionSet); return; }
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        const a = e.target.closest('a[href]');
        if (!a || a.target) return;
        const href = a.getAttribute('href');
        if (!/^[\w-]+\.html$/i.test(href)) return;
        e.preventDefault();
        if (href.toLowerCase() === page()) { playEnter(); return; }
        window.dsGo(href);
    });

    let synced = false;
    async function syncFromApp() {
        if (synced) return;
        try {
            const t = valid(await window.pywebview.api.get_pref("transition"));
            synced = true;
            if (t && t !== root.dataset.transition) setStyle(t);
        } catch (e) {}
    }
    window.addEventListener('pywebviewready', syncFromApp);
    setTimeout(syncFromApp, 300);
    document.addEventListener('DOMContentLoaded', () => setStyle(root.dataset.transition));
})();

// Smooth scrolling. A mouse wheel scrolls in steps; here each step glides with a little inertia, in whichever
// panel is under the pointer (the page, the coach chat, the schedule...). Trackpads already scroll smoothly with
// their own momentum, so they are left alone. Off when the system asks for reduced motion.
(function () {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const EASE = 0.16;          // share of the remaining distance covered each frame (higher = snappier)
    const STEP = 1.0;           // multiplier on the wheel's own distance
    const glides = new WeakMap();

    function isTrackpad(e) {
        if (e.deltaMode !== 0) return false;                       // lines / pages: a wheel
        if (typeof e.wheelDeltaY === "number" && e.wheelDeltaY !== 0) return e.wheelDeltaY === -3 * e.deltaY ||
            Math.abs(e.wheelDeltaY) % 120 !== 0;
        return !Number.isInteger(e.deltaY) || Math.abs(e.deltaY) < 40;
    }
    function canScroll(el, dy) {
        if (el.scrollHeight <= el.clientHeight + 1) return false;
        return dy > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 1 : el.scrollTop > 0;
    }
    function scroller(start, dy) {
        for (let el = start; el && el !== document.documentElement; el = el.parentElement) {
            if (el === document.body) break;
            const oy = getComputedStyle(el).overflowY;
            if ((oy === "auto" || oy === "scroll") && canScroll(el, dy)) return el;
        }
        const se = document.scrollingElement || document.documentElement;
        return canScroll(se, dy) ? se : null;
    }
    function run(el, g) {
        const max = el.scrollHeight - el.clientHeight;
        g.target = Math.max(0, Math.min(max, g.target));
        if (Math.abs(el.scrollTop - Math.round(g.pos)) > 3) { g.active = false; return; }   // moved by something else
        g.pos += (g.target - g.pos) * EASE;
        if (Math.abs(g.target - g.pos) < 0.5) g.pos = g.target;
        el.scrollTop = g.pos;
        if (g.pos !== g.target) requestAnimationFrame(() => run(el, g));
        else g.active = false;
    }
    window.addEventListener('wheel', e => {
        if (e.ctrlKey || Math.abs(e.deltaX) > Math.abs(e.deltaY) || isTrackpad(e)) return;
        if (e.target.closest && e.target.closest('select, input[type="number"], [data-native-scroll]')) return;
        const dy = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaMode === 2 ? e.deltaY * window.innerHeight : e.deltaY;
        const el = scroller(e.target, dy);
        if (!el) return;
        e.preventDefault();
        let g = glides.get(el);
        if (!g || !g.active) {
            g = { pos: el.scrollTop, target: el.scrollTop, active: false };
            glides.set(el, g);
        }
        g.target += dy * STEP;
        if (!g.active) { g.active = true; requestAnimationFrame(() => run(el, g)); }
    }, { passive: false });
})();


// ---------- Terminal: a small button on every page (Ctrl/Cmd + ` too) that shows what the app prints, live ----------
(function () {
    const skip = /(friction|grace|alarm)\.html$/.test(location.pathname);
    if (skip) return;
    const api = () => (window.pywebview && window.pywebview.api) || null;
    let panel, box, btn, timer = null, seen = 0, open = false;

    function build() {
        if (btn) return;
        const css = document.createElement('style');
        css.textContent = `
        #ds-term-btn{position:fixed;right:14px;bottom:14px;z-index:9990;width:34px;height:34px;border-radius:10px;border:1px solid var(--line-2,rgba(128,128,128,.3));
            background:var(--surface-2,#222);color:var(--text,#eee);font:600 13px ui-monospace,Menlo,Consolas,monospace;cursor:pointer;opacity:.75}
        #ds-term-btn:hover,#ds-term-btn.on{opacity:1}
        #ds-term{position:fixed;left:14px;right:56px;bottom:14px;height:230px;z-index:9991;display:none;flex-direction:column;border-radius:12px;overflow:hidden;
            background:#0b0d12;color:#cfe3d4;border:1px solid rgba(255,255,255,.12);box-shadow:0 10px 30px rgba(0,0,0,.35)}
        #ds-term.on{display:flex}
        #ds-term header{display:flex;align-items:center;gap:8px;padding:6px 10px;font:600 12px system-ui,sans-serif;background:rgba(255,255,255,.06)}
        #ds-term header span{flex:1}
        #ds-term header button{border:0;background:rgba(255,255,255,.1);color:inherit;border-radius:6px;padding:3px 9px;font:12px system-ui,sans-serif;cursor:pointer}
        #ds-term pre{flex:1;margin:0;padding:10px 12px;overflow:auto;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word}`;
        document.head.appendChild(css);
        btn = document.createElement('button');
        btn.id = 'ds-term-btn'; btn.type = 'button'; btn.textContent = '>_';
        btn.title = 'Show or hide the terminal (Ctrl/Cmd + `)';
        btn.onclick = () => toggle();
        panel = document.createElement('div');
        panel.id = 'ds-term';
        panel.innerHTML = '<header><span>Terminal: what DriftSync is doing</span><button type="button" data-clear>Clear</button><button type="button" data-close>Hide</button></header><pre></pre>';
        box = panel.querySelector('pre');
        panel.querySelector('[data-clear]').onclick = () => { box.textContent = ''; };
        panel.querySelector('[data-close]').onclick = () => toggle(false);
        document.body.appendChild(panel);
        document.body.appendChild(btn);
    }

    async function poll() {
        const a = api(); if (!a || !a.get_log) return;
        let r = null;
        try { r = await a.get_log(seen); } catch (e) {}
        if (!r) return;
        if (r.lines.length) {
            const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
            box.textContent += r.lines.join('\n') + '\n';
            if (box.textContent.length > 60000) box.textContent = box.textContent.slice(-40000);
            if (atEnd) box.scrollTop = box.scrollHeight;
        }
        seen = r.total;
    }

    function toggle(force, save) {
        open = typeof force === 'boolean' ? force : !open;
        build();
        panel.classList.toggle('on', open);
        btn.classList.toggle('on', open);
        clearInterval(timer); timer = null;
        if (open) { seen = 0; box.textContent = ''; poll(); timer = setInterval(poll, 1000); }
        if (save !== false) { try { api().set_pref('showTerminal', open); } catch (e) {} }
    }

    async function init() {
        if (!api() || !api().get_log) return;   // only inside the app (not the browser Insights copy)
        build();
        let on = false;
        try { on = !!(await api().get_pref('showTerminal')); } catch (e) {}
        if (on) toggle(true, false);
    }
    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key === '`' && api() && api().get_log) { e.preventDefault(); toggle(); }
    });
    window.addEventListener('pywebviewready', init);
    if (window.pywebview) init();
})();
