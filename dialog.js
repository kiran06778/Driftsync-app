// DriftSync warning popup: askUser({...}) shows a card with OK / Cancel and resolves true or false.
//   askUser({ title, points: ["...", "..."], ok: "Turn on", cancel: "Cancel", danger: false })
// Used by Setup and the timer page so every warning looks the same.
(function () {
    const css = `
    .ds-dialog-back { position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center;
        background: rgba(4, 6, 16, .6); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); padding: 16px;
        animation: ds-fade .2s ease both; }
    .ds-dialog { width: 100%; max-width: 440px; padding: 26px 26px 22px; border-radius: 24px;
        background: linear-gradient(180deg, rgba(var(--s1-rgb, 30, 38, 72), .96), rgba(var(--s0-rgb, 14, 19, 38), .98));
        border: 1px solid var(--line-2, rgba(var(--line-rgb, 160,172,255),.15));
        box-shadow: 0 1px 0 rgba(255,255,255,.07) inset, 0 40px 100px -20px rgba(0,0,0,.8), 0 0 80px -30px rgba(var(--a1-rgb, 118,132,255),.5);
        color: var(--text, #E9ECF8); animation: ds-pop .28s cubic-bezier(.2,.7,.2,1) both; }
    .ds-dialog h3 { margin: 0 0 14px; font-family: var(--display, inherit); font-size: 18px; font-weight: 600; letter-spacing: -0.01em; display: flex; gap: 12px; align-items: center; }
    .ds-dialog h3 .ds-icon { flex: none; width: 32px; height: 32px; border-radius: 11px; display: grid; place-items: center;
        background: linear-gradient(140deg, #F6C48E, #F3A3A0); color: #2A1A08; font-size: 15px; font-weight: 800;
        box-shadow: 0 1px 0 rgba(255,255,255,.35) inset, 0 10px 22px -10px rgba(246,196,142,.8); }
    .ds-dialog.danger h3 .ds-icon { background: linear-gradient(140deg, #FF9FAE, #E79BD3); color: #3A0A18; box-shadow: 0 1px 0 rgba(255,255,255,.35) inset, 0 10px 22px -10px rgba(255,140,158,.8); }
    .ds-dialog ul { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.6; color: var(--muted, #98A1C0); }
    .ds-dialog li + li { margin-top: 6px; }
    .ds-dialog .ds-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }
    .ds-dialog button { font: inherit; font-size: 14px; font-weight: 600; padding: 10px 20px; border-radius: 999px; cursor: pointer;
        border: 1px solid var(--line-2, rgba(var(--line-rgb, 160,172,255),.15)); background: rgba(var(--s1-rgb, 26,33,64),.7); color: var(--text, #E9ECF8); transition: filter .2s, transform .2s; }
    .ds-dialog button:hover { filter: brightness(1.12); }
    .ds-dialog button.ds-ok { background: var(--grad, #8E9BFF); border-color: transparent; color: #fff;
        box-shadow: 0 1px 0 rgba(255,255,255,.28) inset, 0 12px 26px -12px rgba(var(--a1-rgb, 118,132,255),.9); }
    .ds-dialog.danger button.ds-ok { background: linear-gradient(120deg, #FF8C9E, #E79BD3); box-shadow: 0 1px 0 rgba(255,255,255,.28) inset, 0 12px 26px -12px rgba(255,140,158,.9); }
    @keyframes ds-fade { from { opacity: 0; } }
    @keyframes ds-pop { from { opacity: 0; transform: translateY(10px) scale(.97); } }`;
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    const esc = t => String(t ?? '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    window.askUser = function ({ title, points = [], ok = "OK", cancel = "Cancel", danger = false }) {
        return new Promise(resolve => {
            const back = document.createElement('div');
            back.className = 'ds-dialog-back';
            back.innerHTML = `
                <div class="ds-dialog ${danger ? 'danger' : ''}" role="alertdialog" aria-modal="true">
                    <h3><span class="ds-icon">!</span>${esc(title)}</h3>
                    <ul>${points.map(p => `<li>${esc(p)}</li>`).join('')}</ul>
                    <div class="ds-actions">
                        ${cancel ? `<button type="button" class="ds-cancel">${esc(cancel)}</button>` : ''}
                        <button type="button" class="ds-ok">${esc(ok)}</button>
                    </div>
                </div>`;
            const done = answer => { back.remove(); document.removeEventListener('keydown', onKey, true); resolve(answer); };
            const onKey = e => {
                if (e.key === 'Escape') { e.preventDefault(); done(false); }
                if (e.key === 'Enter') { e.preventDefault(); done(true); }
            };
            back.querySelector('.ds-ok').onclick = () => done(true);
            const c = back.querySelector('.ds-cancel');
            if (c) c.onclick = () => done(false);
            document.addEventListener('keydown', onKey, true);
            document.body.appendChild(back);
            back.querySelector('.ds-ok').focus();
        });
    };

    // ---------- Permissions, asked inside the app (so nobody has to go looking in Settings) ----------
    //   await dsPermissions.ensureCamera(setStatus)   -> true when the desk check can use the camera
    //   await dsPermissions.ensureNotifications()     -> true when reminders can show as notifications
    const api = () => (window.pywebview && window.pywebview.api) || null;
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let platformInfo = null;
    async function info(refresh) {
        if (!platformInfo || refresh) {
            try { platformInfo = await api().get_platform_info(); } catch (e) { platformInfo = null; }
        }
        return platformInfo || {};
    }

    async function ensureCamera(say) {
        say = say || (() => {});
        const a = api();
        if (!a) return false;
        for (let attempt = 0; attempt < 3; attempt++) {
            say("Asking for camera access…");
            let r = null;
            try { r = await a.request_camera_access(); } catch (e) {}
            if (r && r.ok) { say("Camera allowed ✓"); return true; }
            if (!r) { say("Camera not available."); return false; }
            if (r.os !== "windows") {   // macOS showed its own prompt / settings dialog already
                say(r.error || "Camera not allowed.");
                return false;
            }
            if (r.reason === "privacy") {
                const go = await askUser({
                    title: "Windows is keeping the camera off",
                    points: ["Windows doesn't let apps switch the camera on by themselves, so this one switch is yours: "
                             + "turn on “Camera access” and “Let desktop apps access your camera”.",
                             "Click Open the switch. DriftSync notices the moment it's on, you don't need to come back and click anything."],
                    ok: "Open the switch", cancel: "Not now",
                });
                if (!go) { say("Desk check stays off until the camera is allowed."); return false; }
                try { await a.open_camera_settings(); } catch (e) {}
                say("Waiting for you to turn the camera on…");
                for (let i = 0; i < 60; i++) {      // up to 2 minutes
                    await sleep(2000);
                    const p = await info(true);
                    if (p.cameraPrivacy === "ok") break;
                }
                continue;   // ask again: it opens the camera now
            }
            if (r.reason === "busy") {
                const again = await askUser({
                    title: `${r.apps.join(", ")} ${r.apps.length > 1 ? "are" : "is"} using the camera`,
                    points: ["On Windows only one app can use the camera at a time.",
                             "Close it or end its call, then click Try again."],
                    ok: "Try again", cancel: "Not now",
                });
                if (again) continue;
                say("Desk check stays off while another app has the camera.");
                return false;
            }
            if (r.reason === "admin") {
                await askUser({ title: "The camera is turned off for this whole PC",
                                points: ["Someone with an administrator account (or your school / company) has switched the camera off for every user.",
                                         "Ask them to allow it. Everything else in DriftSync works without the camera."],
                                ok: "OK", cancel: null });
                say("Camera blocked by the PC's administrator.");
                return false;
            }
            const again = await askUser({ title: "No camera found",
                                          points: ["Plug in a webcam (or check the laptop's camera shutter / camera key), then click Try again."],
                                          ok: "Try again", cancel: "Not now" });
            if (!again) { say("No camera found."); return false; }
        }
        say("Camera still not available.");
        return false;
    }

    async function ensureNotifications() {
        const a = api();
        if (!a) return true;
        const p = await info(true);
        const st = p.notifications || {};
        if (st.enabled !== false) return true;   // on, or this OS can't tell (macOS: the Test button shows it)
        const go = await askUser({
            title: "Notifications are turned off",
            points: [st.reason === "all-off"
                        ? "Windows notifications are switched off, so Level 1 reminders would be silent."
                        : "Notifications from DriftSync's reminder sender are switched off in Windows.",
                     "DriftSync can switch them back on for you right now. (If you'd rather not, reminders play a sound instead.)"],
            ok: "Turn on notifications", cancel: "Use sound only",
        });
        if (!go) return false;
        let after = null;
        try { after = await a.enable_notifications(); } catch (e) {}
        await info(true);
        return !!(after && after.enabled !== false);
    }

    window.dsPermissions = { info, ensureCamera, ensureNotifications };
})();
