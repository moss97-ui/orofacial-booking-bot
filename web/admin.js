/* OroFacial staff dashboard. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const main = $("#main");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const DAYS = ["Կիրակի", "Երկուշաբթի", "Երեքշաբթի", "Չորեքշաբթի", "Հինգշաբթի", "Ուրբաթ", "Շաբաթ"];
  const MONTHS_OF = ["հունվարի", "փետրվարի", "մարտի", "ապրիլի", "մայիսի", "հունիսի", "հուլիսի", "օգոստոսի", "սեպտեմբերի", "հոկտեմբերի", "նոյեմբերի", "դեկտեմբերի"];
  const longDay = (d) => { const o = new Date(d + "T12:00:00"); return DAYS[o.getDay()] + ", " + o.getDate() + " " + MONTHS_OF[o.getMonth()]; };
  const today = () => { const n = new Date(); return new Date(n.getTime() - n.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };
  const addDays = (d, n) => { const o = new Date(d + "T12:00:00"); o.setDate(o.getDate() + n); return o.toISOString().slice(0, 10); };
  let token = null;
  try { token = sessionStorage.getItem("of_admin"); } catch { /* blocked */ }
  let clinic = null;

  async function api(path, opts = {}) {
    const headers = {};
    if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = "Bearer " + token;
    const res = await fetch(path, { method: opts.method || (opts.body ? "POST" : "GET"), headers,
      body: opts.body instanceof FormData ? opts.body : opts.body ? JSON.stringify(opts.body) : undefined });
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    if (res.status === 401 && !path.endsWith("/login")) { setToken(null); showLogin(); }
    if (!res.ok) throw new Error(data.error || "Կապի խնդիր։");
    return data;
  }
  function setToken(t) { token = t; try { t ? sessionStorage.setItem("of_admin", t) : sessionStorage.removeItem("of_admin"); } catch { /* blocked */ } }
  function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), 3000); }
  function showLogin() { $("#shell").classList.add("hidden"); $("#login").classList.remove("hidden"); $("#pw").focus(); }

  $("#loginForm").onsubmit = async (e) => {
    e.preventDefault();
    try { const r = await api("/api/admin/login", { body: { password: $("#pw").value } }); setToken(r.token); $("#pw").value = ""; start(); }
    catch (err) { $("#loginErr").textContent = err.message; }
  };
  $("#logout").onclick = () => { setToken(null); showLogin(); };

  const docName = (k) => (clinic.doctors.find((d) => d.key === k) || {}).name || k;
  const docOptions = (sel = "", any = false) => (any ? `<option value="">Բոլոր բժիշկները</option>` : "") +
    clinic.doctors.map((d) => `<option value="${esc(d.key)}" ${d.key === sel ? "selected" : ""}>${esc(d.name)}</option>`).join("");

  function bookingRows(list, { day = true, decide = false } = {}) {
    if (!list.length) return `<p class="empty">Այստեղ դեռ ոչինչ չկա։</p>`;
    return `<table class="t"><thead><tr>${day ? "<th>Օր</th>" : ""}<th>Ժամ</th><th>Պացիենտ</th><th>Բժիշկ / ծառայություն</th><th>Կարգավիճակ</th>${decide ? "<th></th>" : ""}</tr></thead><tbody>
      ${list.map((b) => `<tr>${day ? `<td class="n">${esc(b.date)}</td>` : ""}<td class="n">${esc(b.time)}–${esc(b.end)}</td>
        <td><b>${esc(b.patient)}</b><br><a href="tel:${esc(b.phone)}">${esc(b.phone)}</a><div class="src">${b.source === "app" ? "📱 հավելված" : "✈️ Telegram"}${b.discount ? " · 🎁 " + esc(b.discount) : ""}</div></td>
        <td>${esc(b.doctor)}<br><span class="muted small">${esc(b.service)}</span></td>
        <td><span class="pill ${esc(b.status)}">${esc(b.status_text)}</span>${b.confirmed ? `<div class="src">✓ հաստատել է, որ կգա</div>` : ""}</td>
        ${decide ? `<td><div class="acts">${b.status === "pending" ? `<button class="btn small" data-ok="${esc(b.id)}">Հաստատել</button><button class="btn small danger" data-no="${esc(b.id)}">Մերժել</button>` : ""}</div></td>` : ""}</tr>`).join("")}
      </tbody></table>`;
  }
  function bindDecide(after) {
    main.querySelectorAll("[data-ok],[data-no]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.ok || b.dataset.no, ok = !!b.dataset.ok;
      if (!ok && !confirm("Մերժե՞լ հայտը։ Պացիենտը կտեղեկացվի։")) return;
      b.disabled = true;
      try { await api(`/api/admin/bookings/${encodeURIComponent(id)}/${ok ? "approve" : "reject"}`, { body: {} }); toast(ok ? "Հաստատված է․ պացիենտը տեղեկացվել է։" : "Մերժված է։"); after(); }
      catch (e) { b.disabled = false; toast(e.message); }
    });
  }

  // ---------------------------------------------------------------- sections
  async function overview() {
    const o = await api("/api/admin/overview"), s = o.stats;
    main.innerHTML = `<h1>Ամփոփում</h1>
      <div class="stats">
        <div class="stat"><b>${s.today}</b><span>այց այսօր</span></div>
        <div class="stat ${s.pending ? "hot" : ""}"><b>${s.pending}</b><span>սպասող հայտ</span></div>
        <div class="stat"><b>${s.week}</b><span>այց առաջիկա 7 օրում</span></div>
        <div class="stat"><b>${s.rating ?? "—"}</b><span>միջին գնահատական (${s.ratings})</span></div>
        <div class="stat"><b>${s.month_requests}</b><span>հայտ այս ամիս, որից ${s.month_app}-ը՝ հավելվածից</span></div>
        <div class="stat"><b>${s.accounts}</b><span>պացիենտ հավելվածում</span></div>
      </div>
      <div class="sec"><h2>Սպասող հայտեր</h2>${bookingRows(o.pending, { decide: true })}</div>
      <div class="sec"><h2>Այսօր՝ ${esc(longDay(today()))}</h2>${bookingRows(o.today, { day: false })}</div>`;
    bindDecide(overview);
  }

  async function schedule(from = today(), doctor = "") {
    const r = await api(`/api/admin/bookings?from=${from}&days=7${doctor ? "&doctor=" + encodeURIComponent(doctor) : ""}`);
    const byDay = {};
    r.bookings.forEach((b) => (byDay[b.date] = byDay[b.date] || []).push(b));
    main.innerHTML = `<h1>Գրաֆիկ</h1>
      <div class="toolbar"><button class="btn small ghost" id="prev">‹ Նախորդ շաբաթ</button><button class="btn small ghost" id="now">Այս շաբաթ</button><button class="btn small ghost" id="next">Հաջորդ շաբաթ ›</button>
        <select class="text" id="doc" style="width:auto">${docOptions(doctor, true)}</select></div>
      <p class="muted">${esc(longDay(r.from))} — ${esc(longDay(r.to))}</p>
      ${Array.from({ length: 7 }, (_, i) => addDays(r.from, i)).map((d) => `<div class="day-h">${esc(longDay(d))}</div>${bookingRows((byDay[d] || []), { day: false, decide: true })}`).join("")}`;
    $("#prev").onclick = () => schedule(addDays(from, -7), doctor);
    $("#next").onclick = () => schedule(addDays(from, 7), doctor);
    $("#now").onclick = () => schedule(today(), doctor);
    $("#doc").onchange = (e) => schedule(from, e.target.value);
    bindDecide(() => schedule(from, doctor));
  }

  async function blocks() {
    const list = await api("/api/admin/blocks");
    main.innerHTML = `<h1>Փակ ժամեր</h1><p class="muted">Արձակուրդ, ընդմիջում կամ զբաղված ժամ․ այս ժամերը պացիենտներին չեն առաջարկվի ոչ հավելվածում, ոչ Telegram-ում։</p>
      <form class="card toolbar" id="bf" style="margin-top:14px">
        <label class="field"><span>Բժիշկ</span><select class="text" name="doctor">${docOptions()}</select></label>
        <label class="field"><span>Օր</span><input class="text" type="date" name="date" min="${today()}" required></label>
        <label class="field"><span>Սկսած</span><input class="text" type="time" name="from" value="09:00" step="900"></label>
        <label class="field"><span>Մինչև</span><input class="text" type="time" name="to" value="18:00" step="900"></label>
        <button class="btn" type="submit">Փակել</button></form>
      <div class="sec"><h2>Փակված</h2>${list.length ? `<table class="t"><thead><tr><th>Բժիշկ</th><th>Սկիզբ</th><th>Ավարտ</th><th></th></tr></thead><tbody>
        ${list.map((b) => `<tr><td>${esc(b.doctor_name)}</td><td class="n">${esc(String(b.start).slice(0, 16).replace("T", " "))}</td><td class="n">${esc(String(b.end).slice(0, 16).replace("T", " "))}</td>
          <td><button class="btn small ghost" data-un="${esc(b.doctor)}|${esc(b.id)}">Բացել</button></td></tr>`).join("")}</tbody></table>` : `<p class="empty">Փակ ժամեր չկան։</p>`}</div>`;
    $("#bf").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try { await api("/api/admin/blocks", { body: Object.fromEntries(f) }); toast("Փակված է։"); blocks(); } catch (err) { toast(err.message); }
    };
    main.querySelectorAll("[data-un]").forEach((b) => b.onclick = async () => {
      const [d, id] = b.dataset.un.split("|");
      try { await api(`/api/admin/blocks/${encodeURIComponent(d)}/${encodeURIComponent(id)}`, { method: "DELETE" }); toast("Բացված է։"); blocks(); } catch (err) { toast(err.message); }
    });
  }

  async function catalog() {
    const c = await api("/api/admin/catalog");
    main.innerHTML = `<h1>Գներ և բժիշկներ</h1><p class="muted">Փոփոխությունները միանգամից երևում են հավելվածում և Telegram բոտում։</p>
      <div class="sec"><h2>Ծառայություններ</h2><table class="t"><thead><tr><th>Ծառայություն</th><th>Տևողություն, րոպե</th><th>Գին</th></tr></thead><tbody>
        ${c.reasons.map((r) => `<tr><td>${esc(r.label)}<br><span class="small muted">${esc(r.name)}</span></td>
          <td><input class="text" type="number" min="15" max="240" step="15" data-min="${esc(r.key)}" value="${r.min}" style="max-width:110px"></td>
          <td><input class="text" data-price="${esc(r.key)}" value="${esc(r.price)}" maxlength="40"></td></tr>`).join("")}</tbody></table></div>
      <div class="sec"><h2>Բժիշկներ</h2><div class="grid2">${c.doctors.map((d) => `<div class="card"><h3>${esc(d.name)}</h3>
        <label class="field"><span>Ընդունելության ժամեր (տեքստ)</span><input class="text" data-hours="${esc(d.key)}" value="${esc(d.hours)}" maxlength="80"></label>
        <label class="field"><span>Կենսագրություն</span><textarea class="text" data-bio="${esc(d.key)}" maxlength="800">${esc(d.bio)}</textarea></label></div>`).join("")}</div>
        <p class="small muted" style="margin-top:8px">Բժշկի լուսանկարը ավելացրեք «Լուսանկարներ» բաժնում՝ որպես «Դիմանկար»։ Աշխատանքային գրաֆիկը (ժամերը, որոնք առաջարկվում են պացիենտներին) փոխվում է կարգավորումներում։</p></div>
      <div class="sec"><h2>Հավատարմության ծրագիր</h2><div class="card toolbar">
        <label class="field"><span>Յուրաքանչյուր N-րդ այցը</span><input class="text" type="number" id="lEvery" min="2" max="50" value="${c.loyalty.every}" style="max-width:110px"></label>
        <label class="field"><span>Զեղչ, %</span><input class="text" type="number" id="lPct" min="1" max="100" value="${c.loyalty.percent}" style="max-width:110px"></label></div></div>
      <div style="margin-top:20px"><button class="btn" id="saveCat">Պահպանել փոփոխությունները</button></div>`;
    $("#saveCat").onclick = async () => {
      const body = { reasons: {}, doctors: {}, loyalty: { every: Number($("#lEvery").value), percent: Number($("#lPct").value) } };
      main.querySelectorAll("[data-min]").forEach((i) => (body.reasons[i.dataset.min] = { ...(body.reasons[i.dataset.min] || {}), min: Number(i.value) }));
      main.querySelectorAll("[data-price]").forEach((i) => (body.reasons[i.dataset.price] = { ...(body.reasons[i.dataset.price] || {}), price: i.value }));
      main.querySelectorAll("[data-bio]").forEach((i) => (body.doctors[i.dataset.bio] = { ...(body.doctors[i.dataset.bio] || {}), bio: i.value }));
      main.querySelectorAll("[data-hours]").forEach((i) => (body.doctors[i.dataset.hours] = { ...(body.doctors[i.dataset.hours] || {}), hours: i.value }));
      try { await api("/api/admin/catalog", { body }); toast("Պահպանված է։"); clinic = await api("/api/clinic"); } catch (e) { toast(e.message); }
    };
  }

  async function promos() {
    const list = await api("/api/admin/promos");
    main.innerHTML = `<h1>Պրոմոկոդեր</h1><p class="muted">Պացիենտը կոդը գրում է հավելվածում ամրագրելիս։ Զեղչը նշվում է բժշկին ուղարկվող հայտում։</p>
      <form class="card toolbar" id="pf" style="margin-top:14px">
        <label class="field"><span>Կոդ</span><input class="text" name="code" required maxlength="20" placeholder="SMILE10" style="text-transform:uppercase"></label>
        <label class="field"><span>Զեղչ, %</span><input class="text" name="percent" type="number" min="1" max="100" value="10" required style="max-width:100px"></label>
        <label class="field"><span>Քանի անգամ (0 = անսահմանափակ)</span><input class="text" name="max_uses" type="number" min="0" value="0" style="max-width:120px"></label>
        <label class="field" style="flex:1;min-width:180px"><span>Նշում</span><input class="text" name="note" maxlength="120" placeholder="Օր․՝ Նոր տարվա ակցիա"></label>
        <button class="btn" type="submit">Ավելացնել</button></form>
      <div class="sec">${list.length ? `<table class="t"><thead><tr><th>Կոդ</th><th>Զեղչ</th><th>Օգտագործվել է</th><th>Նշում</th><th></th></tr></thead><tbody>
        ${list.map((p) => `<tr><td><b>${esc(p.code)}</b>${p.active ? "" : ` <span class="pill cancelled">անջատված</span>`}</td><td>−${p.percent}%</td><td>${p.uses}${p.max_uses ? " / " + p.max_uses : ""}</td><td>${esc(p.note)}</td>
          <td><div class="acts"><button class="btn small ghost" data-tg="${esc(p.code)}" data-on="${p.active ? 0 : 1}" data-pct="${p.percent}" data-max="${p.max_uses}" data-note="${esc(p.note)}">${p.active ? "Անջատել" : "Միացնել"}</button>
          <button class="btn small danger" data-del="${esc(p.code)}">Ջնջել</button></div></td></tr>`).join("")}</tbody></table>` : `<p class="empty">Պրոմոկոդեր դեռ չկան։</p>`}</div>`;
    $("#pf").onsubmit = async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target));
      try { await api("/api/admin/promos", { body: { ...f, percent: Number(f.percent), max_uses: Number(f.max_uses), active: true } }); toast("Ավելացված է։"); promos(); } catch (err) { toast(err.message); }
    };
    main.querySelectorAll("[data-tg]").forEach((b) => b.onclick = async () => {
      try { await api("/api/admin/promos", { body: { code: b.dataset.tg, percent: Number(b.dataset.pct), max_uses: Number(b.dataset.max), note: b.dataset.note, active: b.dataset.on === "1" } }); promos(); } catch (e) { toast(e.message); }
    });
    main.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
      if (!confirm("Ջնջե՞լ " + b.dataset.del + " կոդը։")) return;
      try { await api("/api/admin/promos/" + encodeURIComponent(b.dataset.del), { method: "DELETE" }); promos(); } catch (e) { toast(e.message); }
    });
  }

  async function photos() {
    const list = await api("/api/admin/photos");
    const kinds = { portrait: "Դիմանկար", work: "Աշխատանք", clinic: "Կլինիկա" };
    main.innerHTML = `<h1>Լուսանկարներ</h1><p class="muted">Դիմանկարը դառնում է բժշկի նկարը հավելվածում։ «Աշխատանք» և «Կլինիկա» լուսանկարները երևում են պատկերասրահում։ Պացիենտի լուսանկար տեղադրեք միայն նրա համաձայնությամբ։</p>
      <form class="card toolbar" id="uf" style="margin-top:14px">
        <label class="field"><span>Լուսանկար</span><input class="text" type="file" name="file" accept="image/jpeg,image/png,image/webp" required></label>
        <label class="field"><span>Տեսակ</span><select class="text" name="kind">${Object.entries(kinds).map(([k, v]) => `<option value="${k}" ${k === "work" ? "selected" : ""}>${v}</option>`).join("")}</select></label>
        <label class="field"><span>Բժիշկ</span><select class="text" name="doctor"><option value="">—</option>${docOptions()}</select></label>
        <label class="field" style="flex:1;min-width:160px"><span>Մակագրություն</span><input class="text" name="caption" maxlength="140"></label>
        <button class="btn" type="submit">Վերբեռնել</button></form>
      <div class="sec">${list.length ? `<div class="photos">${list.map((p) => `<figure><img src="${esc(p.url)}" alt="" loading="lazy">
        <figcaption><b>${kinds[p.kind] || ""}</b>${p.doctor ? " · " + esc(docName(p.doctor)) : ""}${p.caption ? "<br>" + esc(p.caption) : ""}
        <br><button class="linkbtn" style="color:var(--bad)" data-del="${p.id}">Ջնջել</button></figcaption></figure>`).join("")}</div>` : `<p class="empty">Լուսանկարներ դեռ չկան։</p>`}</div>`;
    $("#uf").onsubmit = async (e) => {
      e.preventDefault();
      const btn = e.target.querySelector("button"); btn.disabled = true;
      try { await api("/api/admin/photos", { body: new FormData(e.target) }); toast("Վերբեռնված է։"); photos(); } catch (err) { btn.disabled = false; toast(err.message); }
    };
    main.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
      if (!confirm("Ջնջե՞լ լուսանկարը։")) return;
      try { await api("/api/admin/photos/" + b.dataset.del, { method: "DELETE" }); photos(); } catch (e) { toast(e.message); }
    });
  }

  async function reviews() {
    const r = await api("/api/admin/reviews");
    main.innerHTML = `<h1>Կարծիքներ</h1>
      <div class="stats">${r.doctors.map((d) => `<div class="stat"><b>★ ${d.average}</b><span>${esc(d.name)} · ${d.count} գնահատական</span></div>`).join("") || `<p class="empty">Գնահատականներ դեռ չկան։</p>`}</div>
      <div class="sec">${r.reviews.length ? `<table class="t"><thead><tr><th>Օր</th><th>Պացիենտ</th><th>Բժիշկ</th><th>Գնահատական</th><th>Կարծիք</th></tr></thead><tbody>
        ${r.reviews.map((x) => `<tr><td class="n">${esc(x.date)}</td><td>${esc(x.name)}<br><a class="small" href="tel:${esc(x.phone)}">${esc(x.phone)}</a></td><td>${esc(x.doctor)}</td>
          <td class="n"><span class="stars">${"★".repeat(x.stars)}${"☆".repeat(5 - x.stars)}</span></td><td>${esc(x.text) || '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table>` : ""}</div>
      <p class="small muted" style="margin-top:10px">4–5 աստղ ստացած կարծիքները ցուցադրվում են հավելվածում։ Ցածր գնահատականների մասին բոտը միանգամից տեղեկացնում է Telegram-ով։</p>`;
  }

  const SECTIONS = { overview, schedule, blocks, catalog, promos, photos, reviews };
  async function route() {
    const k = (location.hash || "#overview").slice(1);
    const fn = SECTIONS[k] || overview;
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + (SECTIONS[k] ? k : "overview")));
    main.innerHTML = `<p class="muted">Բեռնվում է…</p>`;
    try { await fn(); } catch (e) { if (token) main.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  }
  async function start() {
    $("#login").classList.add("hidden"); $("#shell").classList.remove("hidden");
    clinic = await api("/api/clinic");
    route();
  }
  window.addEventListener("hashchange", () => token && route());
  if (token) start().catch(showLogin); else showLogin();
})();
