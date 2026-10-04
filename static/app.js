"use strict";
// Tout le contenu dynamique passe par textContent / append(string) : jamais d'innerHTML (anti-XSS).
const $ = s => document.querySelector(s), ADMIN = document.body.dataset.page === "admin";
let me = null, csrf = "";
const h = (t, a = {}, ...k) => { const e = document.createElement(t); for (const [x, v] of Object.entries(a)) x.startsWith("on") ? e.addEventListener(x.slice(2), v) : e.setAttribute(x, v); e.append(...k); return e; };
const eur = c => (c / 100).toFixed(2).replace(".", ",") + " € fictifs";
const date = t => new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" });
const ST = { open: "Ouvert", closed: "Clôturé", proposed: "Résultat proposé", settled: "Réglé" };
const KIND = { mise: "Mise", gain: "Gain", remboursement: "Remboursement", retrait_fictif: "Retrait fictif", credit_fictif: "Crédit de départ" };
const say = (t, bad) => { $("#msg").textContent = t; $("#msg").className = bad ? "err" : "ok"; };
async function api(m, p, b) {
  const r = await fetch("/api" + p, { method: m, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: b ? JSON.stringify(b) : undefined });
  const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || "Erreur " + r.status); return d;
}
const act = (f, ok, ask) => async () => { if (ask && !confirm(ask)) return; try { await f(); await route(); if (ok) say(ok); } catch (e) { say(e.message, 1); } };
const show = (...n) => $("#main").replaceChildren(...n);
const field = (l, id, type = "text", v = "", ac = "off") => h("label", {}, l, h("input", { id, type, value: v, autocomplete: ac }));
const kv = (...p) => h("dl", { class: "kv" }, ...p.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
const card = (...k) => h("section", { class: "card" }, ...k);
const btn = (t, f, ok, ask) => h("button", { class: "p", type: "button", onclick: act(f, ok, ask) }, t);
const empty = t => h("p", { class: "empty" }, t);
const badge = s => h("span", { class: "badge " + s }, ST[s]);

function nav() {
  const n = $("#nav"); n.replaceChildren(); if (!me) return;
  const L = (t, hr) => h("a", { href: hr }, t);
  if (!ADMIN) n.append(L("Paris", "#/"), L("Mon espace", "#/me"), L("Notifications", "#/notifs"), L("Profil", "#/profile"), ...(me.role !== "parieur" ? [L("Créer un pari", "#/new")] : []));
  n.append(h("span", { class: "bal" }, me.name + " · " + eur(me.bal)), h("button", { onclick: act(async () => { await api("POST", "/logout"); me = null; }) }, "Déconnexion"));
}
async function doLogin() {
  const d = await api("POST", "/login", { email: $("#e").value, password: $("#p").value }); me = d; csrf = d.csrf;
  if (ADMIN && d.role !== "admin") { me = null; throw new Error("Accès administrateur requis"); }
}
function authView() {
  show(h("form", { class: "card auth", onsubmit: e => { e.preventDefault(); act(doLogin)(); } }, h("h1", {}, "Bienvenue sur ToutBet'"),
    h("p", { class: "hint" }, "Connectez-vous, ou créez un compte de démonstration (100 € fictifs offerts)."),
    field("E-mail", "e", "email", "", "username"), field("Mot de passe (10 caractères minimum)", "p", "password", "", "current-password"),
    field("Pseudo (uniquement pour créer un compte)", "n", "text", "", "nickname"),
    h("button", { class: "p", type: "submit" }, "Se connecter"),
    h("button", { type: "button", onclick: act(() => api("POST", "/register", { email: $("#e").value, name: $("#n").value, password: $("#p").value }), "Compte créé. Vous pouvez maintenant vous connecter.") }, "Créer un compte")));
}
const x = n => "×" + n.toFixed(2).replace(".", ",");
const pct = ch => h("div", {}, ...ch.map(c => { const i = h("i"); i.style.width = c.pct + "%"; return h("div", { class: "opt" }, h("span", {}, c.label), h("b", {}, c.pct + " %"), h("div", { class: "bar" }, i),
  h("small", {}, `Cote estimée ${x(c.cote)} · Cote actuelle ${c.cote_live ? x(c.cote_live) : "—"} (${c.n} mise${c.n > 1 ? "s" : ""})`)); }));

async function home() {
  const l = await api("GET", "/bets");
  show(h("h1", {}, "Paris ouverts"), ...(l.length ? l.map(b => h("a", { class: "card bet", href: "#/bet/" + b.id }, h("strong", {}, b.title),
    h("span", { class: "meta" }, `Mise : ${eur(b.stake)} · ${b.n} participant${b.n > 1 ? "s" : ""}`), h("span", { class: "meta" }, "Clôture : " + date(b.closes_at)), b.mine ? h("span", { class: "badge open" }, "Vous participez") : "")) : [empty("Aucun pari ouvert pour le moment." + (me.role === "parieur" ? " Un Bookie doit en créer un." : "")), ...(me.role !== "parieur" ? [h("p", { class: "center" }, h("a", { class: "cta", href: "#/new" }, "Créer un pari"))] : [])]));
}
async function betView(id) {
  const b = await api("GET", "/bets/" + id), sel = h("select", { id: "ch", "aria-label": "Votre choix" }, ...b.choices.map(c => h("option", { value: c.id }, `${c.label} (cote ${x(c.cote)})`)));
  const bt = (t, f, ask) => btn(t, f, "Action effectuée.", ask), post = (p, body) => () => api("POST", `/bets/${id}/${p}`, body), ctl = [];
  if (b.status === "open" && !b.owner) ctl.push(b.mine ? bt("Annuler ma participation", post("leave"), "Annuler et être remboursé ?") : h("div", {}, h("label", {}, "Votre choix", sel), bt("Participer", () => api("POST", `/bets/${id}/join`, { choice_id: +$("#ch").value }), `Confirmer la mise de ${eur(b.stake)} ?`)));
  if (b.mine && b.status === "proposed") ctl.push(bt("Confirmer le résultat", post("vote", { kind: "confirm" })), bt("Contester", post("vote", { kind: "contest", comment: "contestation" })));
  if (b.owner || me.role === "admin") {
    if (b.status === "open") ctl.push(bt("Clôturer maintenant", post("close"), "Clôturer maintenant ?"));
    if (b.status === "closed") ctl.push(h("label", {}, "Résultat à proposer", sel), bt("Proposer ce résultat", () => post("result", { choice_id: +$("#ch").value })(), "Proposer ce résultat ?"));
    if (b.status === "proposed") ctl.push(bt("Régler le pari", post("settle"), "Distribuer les gains fictifs ?"));
  }
  const res = b.result && b.choices.find(c => c.id === b.result);
  show(h("a", { href: "#/", class: "back" }, "← Retour aux paris"), h("h1", {}, b.title),
    card(kv(["Statut", badge(b.status)], ["Mise", eur(b.stake)], ["Échéance", date(b.closes_at)], ["Participants", b.n], ...(res ? [["Résultat", res.label]] : []))),
    card(h("h2", {}, "Probabilités estimées"), pct(b.choices), h("p", { class: "hint" }, "La cote estimée vient des probabilités du Bookie (100 ÷ probabilité). La cote actuelle suit la répartition des mises : les gagnants se partagent la cagnotte, donc le gain réel peut différer. Aucun gain n'est garanti.")),
    ...(ctl.length ? [card(h("h2", {}, "Actions"), ...ctl)] : []));
}
async function mine() {
  const [s, w, hs] = await Promise.all([api("GET", "/me/stats"), api("GET", "/me/wallet"), api("GET", "/me/history")]);
  const a = h("input", { id: "amt", type: "number", min: "0.01", step: "0.01", placeholder: "Montant en €", "aria-label": "Montant en euros fictifs" });
  show(h("h1", {}, "Mon espace"),
    card(h("h2", {}, "Statistiques"), kv(["Solde", eur(w.bal)], ["Paris joués", s.paris], ["Victoires", s.victoires], ["Total misé", eur(s.mises)], ["Total gagné", eur(s.gains)])),
    card(h("h2", {}, "Retrait fictif"), a, btn("Retirer", () => api("POST", "/me/withdraw", { amount_cents: Math.round(a.value * 100), key: crypto.randomUUID() }), "Retrait fictif effectué.", "Confirmer ce retrait fictif ?")),
    h("h2", { class: "sec" }, "Historique des paris"),
    ...(hs.length ? hs.map(x => card(h("strong", {}, x.title), kv(["Statut", ST[x.status]], ["Mise", eur(x.stake)]))) : [empty("Vous n'avez encore participé à aucun pari.")]),
    h("h2", { class: "sec" }, "Mouvements simulés"),
    card(...(w.txs.length ? w.txs.map(t => h("div", { class: "tx" }, h("span", {}, h("strong", {}, KIND[t.kind] || t.kind), h("small", {}, date(t.ts))), h("b", { class: t.amt < 0 ? "neg" : "pos" }, (t.amt > 0 ? "+" : "") + eur(t.amt)))) : [empty("Aucun mouvement.")])));
}
async function notifs() {
  const l = await api("GET", "/notifications"); await api("POST", "/notifications/read", {});
  show(h("h1", {}, "Notifications"), ...(l.length ? l.map(n => h("div", { class: "card notif" + (n.seen ? "" : " unread") }, n.text, h("small", {}, date(n.ts)))) : [empty("Aucune notification.")]));
}
function profile() {
  const d = h("select", { id: "d", "aria-label": "Durée du blocage" }, ...[1, 7, 30].map(x => h("option", { value: x }, x + (x > 1 ? " jours" : " jour"))));
  const blocked = me.block_until * 1000 > Date.now();
  show(h("h1", {}, "Mon profil"),
    card(h("h2", {}, "Informations"), field("Pseudo", "nm", "text", me.name, "nickname"), field("Nom complet (facultatif)", "fn", "text", me.fullname || "", "name"),
      btn("Enregistrer", () => api("PATCH", "/me", { name: $("#nm").value, fullname: $("#fn").value }), "Profil mis à jour.")),
    card(h("h2", {}, "Adresse e-mail"), h("p", { class: "hint" }, "Adresse actuelle : " + me.email), field("Nouvelle adresse", "em", "email", "", "email"), field("Mot de passe actuel (pour confirmer)", "emp", "password", "", "current-password"),
      btn("Changer l'e-mail", () => api("POST", "/me/email", { email: $("#em").value, password: $("#emp").value }), "Adresse e-mail modifiée.", "Modifier votre adresse e-mail ?")),
    card(h("h2", {}, "Mot de passe"), field("Mot de passe actuel", "pw0", "password", "", "current-password"), field("Nouveau mot de passe (10 caractères minimum)", "pw1", "password", "", "new-password"),
      h("p", { class: "hint" }, "Vos autres appareils seront déconnectés."), btn("Changer le mot de passe", () => api("POST", "/me/password", { current: $("#pw0").value, new: $("#pw1").value }), "Mot de passe modifié.")),
    card(h("h2", {}, "Blocage volontaire"), h("p", { class: blocked ? "warn" : "hint" }, blocked ? "Paris bloqués jusqu'au " + date(me.block_until) + "." : "Aucun blocage actif. Pendant un blocage, vous ne pouvez plus parier."),
      h("label", {}, "Durée", d), btn("Activer le blocage", () => api("POST", "/me/block", { days: +d.value }), "Blocage activé.", "Bloquer les paris ? Ce blocage ne pourra pas être levé avant son terme.")));
}
function newBet() {
  const rows = [["", 50], ["", 50]], list = h("div"), total = h("p", { class: "hint" });
  const sum = () => { const t = rows.reduce((x, r) => x + (+r[1] || 0), 0); total.textContent = "Total : " + t + " %" + (t === 100 ? " ✓" : " (doit faire 100 %)"); total.className = t === 100 ? "hint" : "warn"; };
  const draw = () => { list.replaceChildren(...rows.map((r, i) => h("div", { class: "choice" },
    h("input", { value: r[0], maxlength: "40", placeholder: "Choix " + (i + 1), "aria-label": "Nom du choix " + (i + 1), oninput: e => { r[0] = e.target.value; } }),
    h("input", { type: "number", min: "1", max: "99", step: "1", value: r[1], "aria-label": "Probabilité du choix " + (i + 1) + " en pourcent", oninput: e => { r[1] = +e.target.value; sum(); } }),
    rows.length > 2 ? h("button", { type: "button", "aria-label": "Retirer le choix " + (i + 1), onclick: () => { rows.splice(i, 1); draw(); } }, "✕") : h("span")))); sum(); };
  const even = () => { const n = rows.length, b = Math.floor(100 / n); rows.forEach((r, i) => { r[1] = b + (i === 0 ? 100 - b * n : 0); }); draw(); };
  draw();
  show(h("a", { href: "#/", class: "back" }, "← Retour aux paris"), h("h1", {}, "Créer un pari"),
    card(field("Titre", "t"), field("Mise par participant (en centimes, min. 100)", "s", "number", "500"), field("Clôture dans (minutes, min. 5)", "m", "number", "60")),
    card(h("h2", {}, "Choix possibles (2 à 6)"), list, total,
      h("button", { type: "button", onclick: () => { if (rows.length < 6) { rows.push(["", 0]); draw(); } else say("6 choix maximum.", 1); } }, "+ Ajouter un choix"),
      h("button", { type: "button", onclick: even }, "Répartir équitablement"), h("p", { class: "hint" }, "Les probabilités doivent totaliser 100 % et ne pourront plus être modifiées.")),
    btn("Créer le pari", async () => { const r = await api("POST", "/bets", { title: $("#t").value, stake: +$("#s").value, closes_in_min: +$("#m").value, choices: rows.map(r => ({ label: r[0], pct: r[1] })) }); location.hash = "#/bet/" + r.id; }));
}
async function admin() {
  const [u, a] = await Promise.all([api("GET", "/admin/users"), api("GET", "/admin/audit")]);
  const rows = u.map(x => { const s = h("select", { "aria-label": "Rôle de " + x.name }, ...["parieur", "bookie", "admin"].map(r => h("option", { value: r, ...(r === x.role ? { selected: "" } : {}) }, r)));
    return h("tr", {}, h("td", {}, x.email), h("td", {}, s, h("button", { onclick: act(() => api("POST", `/admin/users/${x.id}/role`, { role: s.value }), "Rôle modifié.", "Modifier le rôle ?") }, "Appliquer")),
      h("td", {}, h("span", { class: "badge " + (x.status === "suspended" ? "closed" : "open") }, x.status === "suspended" ? "Suspendu" : "Actif"), h("button", { onclick: act(() => api("POST", `/admin/users/${x.id}/status`, { suspended: x.status !== "suspended" }), "Statut modifié.", "Changer le statut du compte ?") }, x.status === "suspended" ? "Réactiver" : "Suspendre"))); });
  show(h("h1", {}, "Administration"), h("div", { class: "wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "E-mail"), h("th", {}, "Rôle"), h("th", {}, "Statut"))), h("tbody", {}, ...rows))),
    h("h2", { class: "sec" }, "Journal d'audit"), h("p", { class: "hint" }, "Journal chaîné par hachage : aide à la traçabilité, pas une preuve juridique infaillible."),
    card(...a.map(x => h("div", { class: "tx" }, h("span", {}, h("strong", {}, x.action), h("small", {}, `${date(x.ts)} · acteur ${x.actor} · cible ${x.target}`))))));
}
async function route() {
  say("");
  try {
    try { me = await api("GET", "/me"); csrf = me.csrf; } catch { me = null; }
    nav(); if (!me) return authView();
    const [, p, a] = location.hash.split("/");
    if (ADMIN) return me.role === "admin" ? await admin() : (say("Accès refusé", 1), show());
    await ({ bet: () => betView(a), me: mine, notifs, profile, new: newBet }[p] || home)();
  } catch (e) { say(e.message, 1); }
}
addEventListener("hashchange", route); route();
