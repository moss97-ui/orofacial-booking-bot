/* OroFacial patient app. Plain JavaScript, no build step. All text in Armenian. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const view = $("#view");
  const MONTHS_OF = ["հունվարի", "փետրվարի", "մարտի", "ապրիլի", "մայիսի", "հունիսի", "հուլիսի", "օգոստոսի", "սեպտեմբերի", "հոկտեմբերի", "նոյեմբերի", "դեկտեմբերի"];
  const DAYS = ["կիրակի", "երկուշաբթի", "երեքշաբթի", "չորեքշաբթի", "հինգշաբթի", "ուրբաթ", "շաբաթ"];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const initials = (n) => String(n || "").split(" ").map((w) => w[0] || "").join("").slice(0, 2);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const S = { clinic: null, token: store.get("of_token"), me: null, book: {}, nextFree: null };

  // ---------------------------------------------------------------- helpers
  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    if (S.token) headers.Authorization = "Bearer " + S.token;
    const res = await fetch(path, { method: opts.body ? "POST" : "GET", ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    if (res.status === 401 && S.token && !path.startsWith("/api/auth")) { setToken(null); }
    if (!res.ok) throw new Error(data.error || "Կապի խնդիր։ Փորձեք կրկին։");
    return data;
  }
  function setToken(t) { S.token = t; S.me = null; store.set("of_token", t); }
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), 3200);
  }
  const dateObj = (d) => new Date(d + "T12:00:00");
  function niceDay(d, today) {
    const t = today || new Date().toISOString().slice(0, 10);
    const diff = Math.round((dateObj(d) - dateObj(t)) / 864e5);
    if (diff === 0) return "այսօր";
    if (diff === 1) return "վաղը";
    const o = dateObj(d);
    return DAYS[o.getDay()] + ", " + o.getDate() + " " + MONTHS_OF[o.getMonth()];
  }
  const when = (iso) => { const t = new Date(iso); return isNaN(t) ? "" : t.toLocaleString("hy-AM", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); };
  const longDay = (d) => { const o = dateObj(d); return o.getDate() + " " + MONTHS_OF[o.getMonth()] + ", " + DAYS[o.getDay()]; };
  const doctor = (k) => S.clinic.doctors.find((d) => d.key === k);
  const avatar = (d, cls = "") => `<div class="ava ${cls}">${d.photo ? `<img src="${esc(d.photo)}" alt="" loading="lazy">` : esc(initials(d.name))}</div>`;
  const stars = (n) => "★".repeat(Math.round(n)) + "☆".repeat(5 - Math.round(n));
  async function loadMe() {
    if (!S.token) return null;
    try { S.me = await api("/api/me"); } catch { S.me = null; }
    const b = $("#badge");
    const n = S.me ? S.me.unread : 0;
    b.textContent = n; b.classList.toggle("hidden", !n);
    return S.me;
  }
  function render(html) { view.innerHTML = html; window.scrollTo(0, 0); }

  // ---------------------------------------------------------------- home
  async function home() {
    const c = S.clinic;
    render(`
      <div class="hello"><h1>Բարի գալուստ ${esc(c.name)}</h1><p class="muted">Ամրագրեք այց մի քանի հպումով։ Հայտը կհաստատի բժիշկը։</p></div>
      <div id="hero"><div class="skeleton"></div></div>
      <section><div class="row"><h2>Մեր բժիշկները</h2></div><div class="docs">${c.doctors.map((d) => `
        <a class="doc" href="#/doctor/${esc(d.key)}">${avatar(d)}<div class="name">${esc(d.name)}</div>
        <div class="spec">${esc(d.specialty_name)}</div>${d.rating ? `<div class="small"><span class="stars">★</span> ${d.rating} · ${d.ratings}</div>` : ""}</a>`).join("")}</div></section>
      <section><h2>Ծառայություններ և գներ</h2><div class="list">${c.services.map((s) => `
        <a href="#/book/s/${esc(s.key)}"><span class="grow">${esc(s.label)}<br><span class="small muted">${s.min} րոպե</span></span><span class="price">${esc(s.price)}</span><span class="chev" aria-hidden="true">›</span></a>`).join("")}</div>
        ${c.price_note ? `<p class="small muted" style="margin-top:8px">${esc(c.price_note)}</p>` : ""}</section>
      <section id="gallery" class="hidden"><h2>Մեր աշխատանքները</h2><div class="gallery"></div></section>
      <section id="reviews" class="hidden"><h2>Պացիենտների կարծիքները</h2><div class="list"></div></section>
      <section class="contact"><h2>Կապ</h2><div class="card">
        <p><b>${esc(c.full_name)}</b></p><p class="muted">${esc(c.address)}</p><p class="muted">${esc(c.hours)}</p>
        <div class="row" style="margin-top:14px"><a class="btn" href="tel:${esc(c.phone)}">Զանգահարել</a><a class="btn ghost" href="${esc(c.links.route || c.links.map || "#")}" target="_blank" rel="noopener">Երթուղի</a></div>
        <div class="row small" style="margin-top:12px;justify-content:flex-start;gap:16px">
          ${["whatsapp", "viber", "telegram", "instagram"].filter((k) => c.links[k]).map((k) => `<a href="${esc(c.links[k])}" target="_blank" rel="noopener">${k[0].toUpperCase() + k.slice(1)}</a>`).join("")}
        </div></div></section>
      ${installTip()}`);
    api("/api/next-free").then((nf) => {
      S.nextFree = nf;
      const b = nf.best;
      $("#hero").innerHTML = b ? `
        <div class="slot-hero"><p class="muted">Ամենամոտ ազատ ժամը</p>
          <div class="when"><span class="time">${esc(b.time)}</span><span class="day">${esc(niceDay(b.date, nf.today))}</span></div>
          <p class="who"><b>${esc(b.doctor_name)}</b> · ${esc(b.reason_label.replace(/^\S+\s/, ""))}</p>
          <a class="btn block" href="#/book/quick">Ամրագրել այս ժամը</a></div>` : `
        <div class="slot-hero empty"><p class="time">Առաջիկա օրերին ազատ ժամ չկա</p><p class="who">Զանգահարեք կլինիկա՝ ${esc(c.phone)}</p></div>`;
    }).catch(() => { $("#hero").innerHTML = ""; });
    api("/api/photos").then((ph) => {
      if (!ph.length) return;
      $("#gallery").classList.remove("hidden");
      $("#gallery .gallery").innerHTML = ph.slice(0, 9).map((p) => `<figure><img src="${esc(p.url)}" alt="${esc(p.caption)}" loading="lazy"></figure>`).join("");
    }).catch(() => {});
    api("/api/reviews").then((r) => {
      if (!r.reviews.length) return;
      $("#reviews").classList.remove("hidden");
      $("#reviews h2").insertAdjacentHTML("beforeend", ` <span class="small muted">★ ${r.average} · ${r.count}</span>`);
      $("#reviews .list").innerHTML = r.reviews.slice(0, 5).map((x) => `<div class="review" style="display:block"><div class="row"><b>${esc(x.name)}</b><span class="stars">${stars(x.stars)}</span></div>
        <p>${esc(x.text)}</p><p class="small muted">${esc(x.doctor)}</p></div>`).join("");
    }).catch(() => {});
  }

  function installTip() {
    const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    if (standalone || !ios || store.get("of_tip")) return "";
    return `<div class="install-tip" id="tip">Տեղադրեք հավելվածը․ սեղմեք «Կիսվել» <span aria-hidden="true">⬆︎</span>, ապա «Ավելացնել գլխավոր էկրանին»։
      <button class="btn small ghost" style="margin-top:8px" onclick="localStorage.setItem('of_tip','1');this.parentNode.remove()">Լավ</button></div>`;
  }

  // ---------------------------------------------------------------- doctor page
  async function doctorPage(key) {
    const d = doctor(key);
    if (!d) return go("#/");
    const photos = (await api("/api/photos").catch(() => [])).filter((p) => p.doctor === key);
    render(`
      <div style="display:flex;gap:16px;align-items:center;margin-top:16px">${avatar(d, "lg")}
        <div><h1 style="font-size:1.45rem">${esc(d.name)}</h1><p class="muted">${esc(d.specialty_name)}</p>
        ${d.rating ? `<p class="small"><span class="stars">${stars(d.rating)}</span> ${d.rating} (${d.ratings})</p>` : ""}</div></div>
      <p style="margin-top:16px;white-space:pre-line">${esc(d.bio)}</p>
      ${d.hours ? `<p class="muted" style="margin-top:8px">Ընդունելության ժամեր՝ ${esc(d.hours)}</p>` : ""}
      <section><h2>Ծառայություններ</h2><div class="list">${d.reasons.map((r) => `
        <a href="#/book/d/${esc(d.key)}/${esc(r.key)}"><span class="grow">${esc(r.label)}<br><span class="small muted">${r.min} րոպե</span></span><span class="price">${esc(r.price)}</span><span class="chev">›</span></a>`).join("")}</div></section>
      ${photos.length ? `<section><h2>Աշխատանքներ</h2><div class="gallery">${photos.map((p) => `<figure><img src="${esc(p.url)}" alt="${esc(p.caption)}" loading="lazy"></figure>`).join("")}</div></section>` : ""}
      <div style="margin-top:24px"><a class="btn block" href="#/book/d/${esc(d.key)}">Ամրագրել ${esc(d.name.split(" ")[0])}ի մոտ</a></div>`);
  }

  // ---------------------------------------------------------------- booking
  function steps(n) { return `<div class="steps" aria-label="Քայլ ${n}՝ 5-ից">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= n ? "done" : ""}"></i>`).join("")}</div>`; }
  function head(n, title, sub) {
    return `${steps(n)}<div class="step-head"><div class="row"><h1 style="font-size:1.4rem">${esc(title)}</h1>
      ${n > 1 ? `<button class="btn small ghost" type="button" data-back>Հետ</button>` : ""}</div>${sub ? `<p class="muted">${sub}</p>` : ""}</div>`;
  }
  function bindBack(fn) { const b = view.querySelector("[data-back]"); if (b) b.onclick = fn; }

  function bookStart(args) {
    const B = (S.book = { doctor: null, reason: null, date: null, time: null, promo: null });
    if (args[0] === "quick" && S.nextFree && S.nextFree.best) {
      const b = S.nextFree.best;
      Object.assign(B, { doctor: b.doctor, reason: b.reason, date: b.date, time: b.time });
      return stepConfirm();
    }
    if (args[0] === "d" && doctor(args[1])) {
      B.doctor = args[1];
      if (args[2] && doctor(args[1]).reasons.some((r) => r.key === args[2])) { B.reason = args[2]; return stepDate(); }
      return stepReason();
    }
    if (args[0] === "s") { B.service = args[1]; }
    stepDoctor();
  }

  function stepDoctor() {
    const B = S.book;
    let docs = S.clinic.doctors;
    const svc = B.service && S.clinic.services.find((s) => s.key === B.service);
    if (svc) docs = docs.filter((d) => svc.doctors.includes(d.key));
    const fav = S.me && S.me.favourite;
    docs = [...docs].sort((a, b) => (b.key === fav) - (a.key === fav));
    render(head(1, "Ընտրեք բժշկին", svc ? esc(svc.label) : "") + `<div class="list">${docs.map((d) => `
      <button type="button" data-k="${esc(d.key)}">${avatar(d, "sm")}<span class="grow"><b>${esc(d.name)}</b><br><span class="small muted">${esc(d.specialty_name)}${d.key === fav ? " · Ձեր բժիշկը" : ""}</span></span><span class="chev">›</span></button>`).join("")}</div>`);
    view.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => {
      B.doctor = b.dataset.k;
      if (svc && doctor(B.doctor).reasons.some((r) => r.key === svc.key)) { B.reason = svc.key; return stepDate(); }
      stepReason();
    });
  }

  function stepReason() {
    const B = S.book, d = doctor(B.doctor);
    render(head(2, "Այցի նպատակը", "Բժիշկ՝ " + esc(d.name) + ". Նպատակից է կախված այցի տևողությունը։") + `<div class="list">${d.reasons.map((r) => `
      <button type="button" data-k="${esc(r.key)}"><span class="grow">${esc(r.label)}<br><span class="small muted">${r.min} րոպե</span></span><span class="price">${esc(r.price)}</span></button>`).join("")}</div>`);
    bindBack(stepDoctor);
    view.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => { B.reason = b.dataset.k; stepDate(); });
  }

  async function stepDate(monthIdx = 0) {
    const B = S.book, d = doctor(B.doctor), r = d.reasons.find((x) => x.key === B.reason);
    render(head(3, "Ընտրեք օրը", esc(d.name) + " · " + esc(r.label) + " · " + r.min + " րոպե") + `<div class="skeleton"></div>`);
    bindBack(stepReason);
    let data;
    try { data = await api(`/api/dates?doctor=${encodeURIComponent(B.doctor)}&reason=${encodeURIComponent(B.reason)}`); }
    catch (e) { view.querySelector(".skeleton").outerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    if (!data.months[monthIdx].days.length && monthIdx === 0 && data.months[1].days.length) monthIdx = 1;
    const m = data.months[monthIdx];
    const body = `<div class="months">${data.months.map((x, i) => `<button type="button" class="chip ${i === monthIdx ? "on" : ""}" data-m="${i}">${esc(x.name)}<small>${x.days.length} ազատ օր</small></button>`).join("")}</div>
      ${m.days.length ? `<div class="chips">${m.days.map((x) => `<button type="button" class="chip" data-d="${x.date}">${Number(x.date.slice(8))}<small>${esc(x.weekday)}</small></button>`).join("")}</div>`
        : `<div class="card empty-state"><p>Այս ամսին ազատ օր չկա։</p><a class="btn ghost" href="tel:${esc(S.clinic.phone)}">Զանգահարել կլինիկա</a></div>`}`;
    view.querySelector(".skeleton").outerHTML = body;
    view.querySelectorAll("[data-m]").forEach((b) => b.onclick = () => stepDate(Number(b.dataset.m)));
    view.querySelectorAll("[data-d]").forEach((b) => b.onclick = () => { B.date = b.dataset.d; stepTime(); });
  }

  async function stepTime() {
    const B = S.book;
    render(head(4, "Ընտրեք ժամը", esc(longDay(B.date))) + `<div class="skeleton"></div>`);
    bindBack(() => stepDate());
    let data;
    try { data = await api(`/api/slots?doctor=${encodeURIComponent(B.doctor)}&reason=${encodeURIComponent(B.reason)}&date=${B.date}`); }
    catch (e) { view.querySelector(".skeleton").outerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    view.querySelector(".skeleton").outerHTML = data.times.length
      ? `<div class="chips">${data.times.map((t) => `<button type="button" class="chip" data-t="${t}">${t}</button>`).join("")}</div>`
      : `<div class="card empty-state"><p>Այս օրը ազատ ժամ այլևս չկա։</p><button class="btn ghost" type="button" data-back2>Այլ օր</button></div>`;
    view.querySelectorAll("[data-t]").forEach((b) => b.onclick = () => { B.time = b.dataset.t; stepConfirm(); });
    const b2 = view.querySelector("[data-back2]"); if (b2) b2.onclick = () => stepDate();
  }

  async function stepConfirm() {
    const B = S.book, d = doctor(B.doctor), r = d.reasons.find((x) => x.key === B.reason);
    await loadMe();
    const reward = S.me && S.me.loyalty.next_is_reward;
    render(head(5, "Ստուգեք և ուղարկեք", "") + `
      <div class="card summary"><dl>
        <dt>Բժիշկ</dt><dd>${esc(d.name)}</dd><dt>Ծառայություն</dt><dd>${esc(r.name)}</dd>
        <dt>Օր</dt><dd>${esc(longDay(B.date))}</dd><dt>Ժամ</dt><dd>${esc(B.time)} · ${r.min} րոպե</dd><dt>Գին</dt><dd>${esc(r.price)}</dd></dl>
        ${reward ? `<div class="reward">🎁 Սա Ձեր ${S.me.loyalty.every}-րդ այցն է՝ −${S.me.loyalty.percent}% զեղչ։</div>` : ""}</div>
      <label class="field"><span>Պրոմոկոդ (եթե ունեք)</span><div class="promo"><input class="text" id="promo" autocomplete="off" maxlength="20" value="${esc(B.promo || "")}">
        <button class="btn ghost" type="button" id="promoBtn">Ստուգել</button></div></label><p id="promoMsg" class="small"></p>
      <div id="who" style="margin-top:8px"></div>
      <button class="btn block" type="button" id="send" style="margin-top:16px">Ուղարկել հայտը</button>
      <p id="sendErr" class="error"></p>
      <p class="small muted" style="margin-top:10px">Հայտը կուղարկվի բժշկին։ Պատասխանը կտեսնեք «Այցերս» բաժնում։</p>`);
    bindBack(() => (S.nextFree && S.nextFree.best && B.time === S.nextFree.best.time && B.date === S.nextFree.best.date ? go("#/") : stepTime()));
    $("#who").innerHTML = S.me ? `<p class="muted">Այցելու՝ <b style="color:var(--ink)">${esc(S.me.name)}</b> · ${esc(S.me.phone)}</p>` : authForm(true);
    if (!S.me) bindAuth(() => stepConfirm());
    $("#promoBtn").onclick = async () => {
      const code = $("#promo").value.trim();
      if (!code) return;
      try { const p = await api("/api/promo/check", { body: { code } }); B.promo = p.code; $("#promoMsg").textContent = "✓ Զեղչ −" + p.percent + "%" + (p.note ? " · " + p.note : ""); $("#promoMsg").className = "small"; }
      catch (e) { B.promo = null; $("#promoMsg").textContent = e.message; $("#promoMsg").className = "small error"; }
    };
    $("#send").onclick = async () => {
      if (!S.me) { $("#sendErr").textContent = "Նախ մուտք գործեք կամ գրանցվեք վերևում։"; return; }
      const code = $("#promo").value.trim();
      $("#send").disabled = true;
      try {
        const res = await api("/api/book", { body: { doctor: B.doctor, reason: B.reason, date: B.date, time: B.time, promo: code || undefined } });
        render(`<div class="done-mark" aria-hidden="true">✓</div><h1 style="text-align:center">Հայտն ուղարկված է</h1>
          <p class="muted" style="text-align:center;margin-top:8px">${esc(d.name)} · ${esc(longDay(B.date))}, ${esc(B.time)}${res.discount ? `<br>🎁 Զեղչ՝ −${res.discount}%` : ""}</p>
          <p style="text-align:center;margin-top:12px">Բժիշկը կհաստատի հայտը, և Դուք կտեսնեք պատասխանը «Այցերս» բաժնում։</p>
          <div style="margin-top:24px;display:grid;gap:10px"><a class="btn" href="#/visits">Իմ այցերը</a><a class="btn ghost" href="#/">Գլխավոր</a></div>`);
        S.nextFree = null; loadMe();
      } catch (e) {
        $("#send").disabled = false; $("#sendErr").textContent = e.message;
        if (/ազատ չէ|ամրագրվեց/.test(e.message)) setTimeout(stepTime, 1600);
      }
    };
  }

  // ---------------------------------------------------------------- sign in
  function authForm(compact) {
    return `<div class="card"><h3>${compact ? "Ով է գալու" : "Մուտք"}</h3>
      <p class="small muted" style="margin-top:4px">Մուտք գործեք հեռախոսահամարով և PIN-ով։ Առաջին անգամ՝ ընտրեք նոր PIN և գրեք Ձեր անունը։</p>
      <label class="field"><span>Հեռախոս</span><input class="text" id="aPhone" type="tel" inputmode="tel" autocomplete="tel" placeholder="091 123456"></label>
      <label class="field"><span>PIN (4–6 թիվ)</span><input class="text" id="aPin" type="password" inputmode="numeric" autocomplete="current-password" maxlength="6"></label>
      <label class="field"><span>Անուն և ազգանուն (միայն առաջին անգամ)</span><input class="text" id="aName" autocomplete="name" placeholder="Անի Պետրոսյան"></label>
      <button class="btn block" type="button" id="aGo">Շարունակել</button><p class="error" id="aErr"></p></div>`;
  }
  function bindAuth(after) {
    $("#aGo").onclick = async () => {
      $("#aGo").disabled = true; $("#aErr").textContent = "";
      try {
        const res = await api("/api/auth", { body: { phone: $("#aPhone").value, pin: $("#aPin").value, name: $("#aName").value } });
        setToken(res.token); await loadMe();
        toast(res.created ? "Բարի գալուստ, " + res.account.name.split(" ")[0] + "։" : "Բարի վերադարձ։");
        after();
      } catch (e) { $("#aGo").disabled = false; $("#aErr").textContent = e.message; }
    };
  }

  // ---------------------------------------------------------------- my visits
  function visitCard(v) {
    const acts = [];
    if (v.can_confirm) acts.push(`<button class="btn small" data-a="confirm" data-id="${esc(v.id)}">Կգամ</button>`);
    if (v.can_cancel) acts.push(`<button class="btn small danger" data-a="cancel" data-id="${esc(v.id)}">Չեղարկել</button>`);
    return `<div class="card visit"><div class="row"><span class="date">${esc(v.date === new Date().toISOString().slice(0, 10) ? "Այսօր" : longDay(v.date))}</span><span class="pill ${esc(v.status)}">${esc(v.status_text)}</span></div>
      <p style="margin-top:4px"><b>${esc(v.time)}–${esc(v.end)}</b> · ${esc(v.doctor)}</p><p class="muted">${esc(v.service)}</p>
      ${v.discount ? `<p class="small" style="margin-top:4px">🎁 ${esc(v.discount)}</p>` : ""}${v.confirmed ? `<p class="small" style="margin-top:4px">✓ Դուք հաստատել եք, որ կգաք</p>` : ""}
      ${v.can_rate ? `<div style="margin-top:10px"><p class="small">Ինչպե՞ս անցավ այցը</p><div class="rate" data-id="${esc(v.id)}">${[1, 2, 3, 4, 5].map((i) => `<button type="button" data-s="${i}" aria-label="${i} աստղ">★</button>`).join("")}</div>
        <textarea class="text hidden" placeholder="Մի քանի խոսք բժշկի մասին (ոչ պարտադիր)" maxlength="600"></textarea><button class="btn small hidden" data-a="rate" data-id="${esc(v.id)}" style="margin-top:8px">Ուղարկել գնահատականը</button></div>` : ""}
      ${v.rating ? `<p class="small" style="margin-top:6px"><span class="stars">${stars(v.rating)}</span>${v.review ? " · " + esc(v.review) : ""}</p>` : ""}
      ${acts.length ? `<div class="acts">${acts.join("")}</div>` : ""}</div>`;
  }
  async function visits() {
    if (!S.token) return render(`<h1 style="margin-top:16px">Իմ այցերը</h1><div style="margin-top:16px">${authForm()}</div>`), bindAuth(visits);
    await loadMe();
    if (!S.me) return visits();
    const me = S.me;
    render(`<h1 style="margin-top:16px">Իմ այցերը</h1>
      <section style="margin-top:16px"><h2>Առաջիկա</h2>${me.upcoming.length ? me.upcoming.map(visitCard).join("") :
        `<div class="card empty-state"><p>Առաջիկա այցեր չունեք։</p><a class="btn" href="#/book">Ամրագրել այց</a></div>`}</section>
      ${me.past.length ? `<section><h2>Նախկին</h2>${me.past.map(visitCard).join("")}</section>` : ""}`);
    view.querySelectorAll(".rate").forEach((box) => {
      box.querySelectorAll("button").forEach((b) => b.onclick = () => {
        box.dataset.stars = b.dataset.s;
        box.querySelectorAll("button").forEach((x) => x.classList.toggle("on", Number(x.dataset.s) <= Number(b.dataset.s)));
        box.parentNode.querySelector("textarea").classList.remove("hidden");
        box.parentNode.querySelector("[data-a=rate]").classList.remove("hidden");
      });
    });
    view.querySelectorAll("[data-a]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.id, a = b.dataset.a;
      if (a === "cancel" && !confirm("Չեղարկե՞լ այս այցը։")) return;
      b.disabled = true;
      try {
        if (a === "rate") {
          const box = b.parentNode.querySelector(".rate");
          await api(`/api/bookings/${encodeURIComponent(id)}/rate`, { body: { stars: Number(box.dataset.stars), review: b.parentNode.querySelector("textarea").value } });
          toast("Շնորհակալություն գնահատականի համար։");
        } else {
          await api(`/api/bookings/${encodeURIComponent(id)}/${a}`, { body: {} });
          toast(a === "cancel" ? "Այցը չեղարկված է։ Բժիշկը տեղեկացվել է։" : "Շնորհակալություն, սպասում ենք Ձեզ։");
        }
        visits();
      } catch (e) { b.disabled = false; toast(e.message); }
    });
  }

  // ---------------------------------------------------------------- profile
  async function profile() {
    if (!S.token) return render(`<h1 style="margin-top:16px">Պրոֆիլ</h1><div style="margin-top:16px">${authForm()}</div>${staffLink()}`), bindAuth(profile);
    await loadMe();
    if (!S.me) return profile();
    const me = S.me, L = me.loyalty;
    const notes = await api("/api/notifications").catch(() => []);
    const cells = Array.from({ length: L.every }, (_, i) => i < L.in_cycle ? `<span class="on">✓</span>` : i === L.every - 1 ? `<span class="gift">🎁</span>` : `<span>${i + 1}</span>`);
    render(`<h1 style="margin-top:16px">${esc(me.name)}</h1><p class="muted">${esc(me.phone)}</p>
      <section><h2>Հավատարմության քարտ</h2><div class="card">
        <p>Յուրաքանչյուր ${L.every}-րդ այցը՝ <b>−${L.percent}%</b> զեղչով։</p><div class="stamps">${cells.join("")}</div>
        <p class="small muted">${L.next_is_reward ? "Ձեր հաջորդ այցը զեղչով է։" : "Մինչև զեղչ՝ " + (L.every - 1 - L.in_cycle) + " այց։"} Ընդամենը՝ ${L.visits} այց։</p></div></section>
      <section><div class="row"><h2>Ծանուցումներ</h2>${notes.some((n) => !n.read) ? `<button class="btn small ghost" id="readAll">Նշել կարդացված</button>` : ""}</div>
        ${notes.length ? `<div class="list">${notes.slice(0, 20).map((n) => `<div class="note ${n.read ? "" : "unread"}" style="display:block"><pre>${esc(n.text)}</pre><p class="small muted">${esc(when(n.at))}</p></div>`).join("")}</div>`
          : `<p class="muted">Ծանուցումներ դեռ չկան։</p>`}</section>
      <section><h2>Կարգավորումներ</h2><div class="card">
        <label class="field"><span>Իմ բժիշկը</span><select class="text" id="fav"><option value="">—</option>${S.clinic.doctors.map((d) => `<option value="${esc(d.key)}" ${d.key === me.favourite ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
        <label class="field"><span>Անուն և ազգանուն</span><input class="text" id="nm" value="${esc(me.name)}"></label>
        <label class="field"><span>Նոր PIN (եթե ուզում եք փոխել)</span><input class="text" id="np" type="password" inputmode="numeric" maxlength="6" autocomplete="new-password"></label>
        <button class="btn block" id="save">Պահպանել</button><p class="error" id="sErr"></p></div></section>
      <div style="margin-top:20px"><button class="btn block ghost" id="out">Դուրս գալ</button></div>${staffLink()}`);
    const ra = $("#readAll"); if (ra) ra.onclick = async () => { await api("/api/notifications/read", { body: {} }); profile(); };
    if (notes.some((n) => !n.read)) setTimeout(() => api("/api/notifications/read", { body: {} }).then(loadMe), 4000);
    $("#save").onclick = async () => {
      const body = { favourite: $("#fav").value, name: $("#nm").value };
      if ($("#np").value) body.pin = $("#np").value;
      try { await api("/api/me", { body }); toast("Պահպանված է։"); profile(); } catch (e) { $("#sErr").textContent = e.message; }
    };
    $("#out").onclick = async () => { await api("/api/logout", { body: {} }).catch(() => {}); setToken(null); go("#/"); };
  }
  const staffLink = () => `<p class="small" style="text-align:center;margin-top:28px"><a href="/admin">Աշխատակազմի մուտք</a></p>`;

  // ---------------------------------------------------------------- router
  function go(h) { if (location.hash === h) route(); else location.hash = h; }
  async function route() {
    const parts = (location.hash.replace(/^#\/?/, "") || "").split("/").filter(Boolean);
    const tab = { book: "book", visits: "visits", me: "me" }[parts[0]] || "home";
    document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
    try {
      if (parts[0] === "book") bookStart(parts.slice(1));
      else if (parts[0] === "doctor") await doctorPage(parts[1]);
      else if (parts[0] === "visits") await visits();
      else if (parts[0] === "me") await profile();
      else await home();
    } catch (e) { render(`<div class="card empty-state" style="margin-top:24px"><p>${esc(e.message)}</p><button class="btn" onclick="location.reload()">Կրկին փորձել</button></div>`); }
    view.focus({ preventScroll: true });
  }

  // install button (Android / desktop Chrome)
  let deferred = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; $("#installBtn").classList.remove("hidden"); });
  $("#installBtn").onclick = async () => { if (!deferred) return; deferred.prompt(); await deferred.userChoice; deferred = null; $("#installBtn").classList.add("hidden"); };
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

  (async () => {
    try { S.clinic = await api("/api/clinic"); }
    catch (e) { render(`<div class="card empty-state" style="margin-top:24px"><p>Չհաջողվեց բեռնել։ Ստուգեք ինտերնետը։</p><button class="btn" onclick="location.reload()">Կրկին փորձել</button></div>`); return; }
    document.title = S.clinic.name;
    await loadMe();
    window.addEventListener("hashchange", route);
    route();
    setInterval(loadMe, 60000);
  })();
})();
