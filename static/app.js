"use strict";
// Tout le contenu dynamique passe par textContent / append(string) : jamais d'innerHTML (anti-XSS).
const $ = s => document.querySelector(s), ADMIN = document.body.dataset.page === "admin";
let me = null, csrf = "";
const h = (t, a = {}, ...k) => { const e = document.createElement(t); for (const [x, v] of Object.entries(a)) x.startsWith("on") ? e.addEventListener(x.slice(2), v) : e.setAttribute(x, v); e.append(...k); return e; };
const eur = c => (c / 100).toFixed(2) + " € fictifs", date = t => new Date(t * 1000).toLocaleString("fr-FR");
const say = (t, bad) => { $("#msg").textContent = t; $("#msg").className = bad ? "err" : "ok"; };
async function api(m, p, b) {
  const r = await fetch("/api" + p, { method: m, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: b ? JSON.stringify(b) : undefined });
  const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || "Erreur " + r.status); return d;
}
const act = (f, ok, ask) => async () => { if (ask && !confirm(ask)) return; try { await f(); if (ok) say(ok); route(); } catch (e) { say(e.message, 1); } };
const show = (...n) => { const m = $("#main"); m.replaceChildren(...n); };
const field = (l, id, type = "text") => h("label", {}, l, h("input", { id, type, required: "" }));

function nav() {
  const n = $("#nav"); n.replaceChildren();
  if (!me) return;
  const L = (t, hr) => h("a", { href: hr }, t);
  if (!ADMIN) n.append(L("Paris", "#/"), L("Mon espace", "#/me"), L("Notifications", "#/notifs"), L("Profil", "#/profile"), ...(me.role !== "parieur" ? [L("Créer", "#/new")] : []));
  n.append(h("span", {}, me.name + " · " + eur(me.bal)), h("button", { onclick: act(async () => { await api("POST", "/logout"); me = null; }) }, "Déconnexion"));
}
function authView() {
  const f = h("form", { onsubmit: e => e.preventDefault() }, h("h1", {}, "Connexion / création de compte"), field("E-mail", "e", "email"), h("label", {}, "Pseudo (inscription)", h("input", { id: "n" })), field("Mot de passe (10 caractères min.)", "p", "password"),
    h("button", { class: "p", onclick: act(async () => { const d = await api("POST", "/login", { email: $("#e").value, password: $("#p").value }); me = d; csrf = d.csrf; if (ADMIN && d.role !== "admin") { me = null; throw new Error("Accès administrateur requis"); } }) }, "Se connecter"),
    h("button", { onclick: act(async () => { await api("POST", "/register", { email: $("#e").value, name: $("#n").value, password: $("#p").value }); }, "Compte créé (100 € fictifs offerts). Connectez-vous.") }, "Créer un compte"));
  show(f);
}
const pct = ch => h("ul", {}, ...ch.map(c => h("li", {}, `${c.label} : ${c.pct} %`)));
async function home() {
  const l = await api("GET", "/bets"); show(h("h1", {}, "Paris ouverts"), ...l.map(b => h("div", { class: "card" }, h("a", { href: "#/bet/" + b.id }, b.title), h("br"), `Mise : ${eur(b.stake)} · ${b.n} participant(s) · clôture ${date(b.closes_at)}`)), l.length ? "" : "Aucun pari ouvert.");
}
async function betView(id) {
  const b = await api("GET", "/bets/" + id), sel = h("select", { id: "ch", "aria-label": "Votre choix" }, ...b.choices.map(c => h("option", { value: c.id }, c.label)));
  const bt = (t, f, ask) => h("button", { class: "p", onclick: act(f, "Fait.", ask) }, t), post = (p, body) => () => api("POST", `/bets/${id}/${p}`, body);
  const ctl = [];
  if (b.status === "open" && !b.owner) ctl.push(b.mine ? bt("Annuler ma participation", post("leave"), "Annuler et être remboursé ?") : h("div", {}, sel, bt("Participer", () => api("POST", `/bets/${id}/join`, { choice_id: +$("#ch").value }), `Confirmer la mise de ${eur(b.stake)} ?`)));
  if (b.mine && b.status === "proposed") ctl.push(bt("Confirmer le résultat", post("vote", { kind: "confirm" })), bt("Contester", post("vote", { kind: "contest", comment: "contestation" })));
  if (b.owner || me.role === "admin") {
    if (b.status === "open") ctl.push(bt("Clôturer", post("close"), "Clôturer maintenant ?"));
    if (b.status === "closed") ctl.push(sel, bt("Proposer ce résultat", () => post("result", { choice_id: +$("#ch").value })(), "Proposer ce résultat ?"));
    if (b.status === "proposed") ctl.push(bt("Régler le pari", post("settle"), "Distribuer les gains fictifs ?"));
  }
  show(h("h1", {}, b.title), h("div", { class: "card" }, `Statut : ${b.status} · Mise : ${eur(b.stake)} · Échéance : ${date(b.closes_at)}`, h("h2", {}, "Probabilités estimées"), pct(b.choices),
    h("small", {}, "Estimations du Bookie : elles ne garantissent AUCUN gain."), b.result ? h("p", {}, "Résultat proposé/validé : " + b.choices.find(c => c.id === b.result)?.label) : ""), ...ctl);
}
async function mine() {
  const [s, w, hs] = await Promise.all([api("GET", "/me/stats"), api("GET", "/me/wallet"), api("GET", "/me/history")]);
  const a = h("input", { id: "amt", type: "number", min: "1", step: "0.01", "aria-label": "Montant en euros fictifs" });
  show(h("h1", {}, "Mon espace"), h("div", { class: "card" }, `Solde : ${eur(w.bal)} · Paris : ${s.paris} · Victoires : ${s.victoires} · Mises : ${eur(s.mises)} · Gains : ${eur(s.gains)}`),
    h("div", { class: "card" }, h("h2", {}, "Retrait fictif"), a, h("button", { class: "p", onclick: act(() => api("POST", "/me/withdraw", { amount_cents: Math.round(a.value * 100), key: crypto.randomUUID() }), "Retrait fictif effectué.", "Confirmer ce retrait fictif ?") }, "Retirer")),
    h("h2", {}, "Historique des paris"), ...hs.map(x => h("div", { class: "card" }, `${x.title} – ${x.status} – mise ${eur(x.stake)}`)),
    h("h2", {}, "Mouvements simulés"), ...w.txs.map(t => h("div", {}, `${date(t.ts)} · ${t.kind} · ${eur(t.amt)}`)));
}
async function notifs() {
  const l = await api("GET", "/notifications"); await api("POST", "/notifications/read", {});
  show(h("h1", {}, "Notifications"), ...l.map(n => h("div", { class: "card" }, n.text, h("br"), h("small", {}, date(n.ts)))), l.length ? "" : "Aucune notification.");
}
function profile() {
  const n = h("input", { id: "nm", value: me.name, "aria-label": "Pseudo" }), d = h("select", { id: "d", "aria-label": "Durée" }, ...[1, 7, 30].map(x => h("option", { value: x }, x + " jour(s)")));
  show(h("h1", {}, "Profil"), n, h("button", { class: "p", onclick: act(async () => { await api("PATCH", "/me", { name: n.value }); me.name = n.value; }, "Profil mis à jour.") }, "Enregistrer"),
    h("div", { class: "card" }, h("h2", {}, "Blocage volontaire"), h("p", {}, me.block_until * 1000 > Date.now() ? "Bloqué jusqu'au " + date(me.block_until) : "Aucun blocage actif."), d,
      h("button", { class: "p", onclick: act(async () => { me.block_until = (await api("POST", "/me/block", { days: +d.value })).block_until; }, "Compte bloqué pour les paris.", "Bloquer les paris ? Vous ne pourrez pas lever ce blocage avant son terme.") }, "Activer le blocage")));
}
function newBet() {
  const f = h("div", {}, h("h1", {}, "Créer un pari"), field("Titre", "t"), field("Mise (centimes)", "s", "number"), field("Clôture dans (minutes)", "m", "number"), field("Choix A", "a"), field("Probabilité A (%)", "pa", "number"), field("Choix B", "b"), field("Probabilité B (%)", "pb", "number"),
    h("button", { class: "p", onclick: act(async () => { const r = await api("POST", "/bets", { title: $("#t").value, stake: +$("#s").value, closes_in_min: +$("#m").value, choices: [{ label: $("#a").value, pct: +$("#pa").value }, { label: $("#b").value, pct: +$("#pb").value }] }); location.hash = "#/bet/" + r.id; }) }, "Créer"));
  show(f);
}
async function admin() {
  const [u, a] = await Promise.all([api("GET", "/admin/users"), api("GET", "/admin/audit")]);
  const rows = u.map(x => { const s = h("select", { "aria-label": "Rôle de " + x.name }, ...["parieur", "bookie", "admin"].map(r => h("option", { value: r, ...(r === x.role ? { selected: "" } : {}) }, r)));
    return h("tr", {}, h("td", {}, x.email), h("td", {}, s, h("button", { onclick: act(() => api("POST", `/admin/users/${x.id}/role`, { role: s.value }), "Rôle modifié.", "Modifier le rôle ?") }, "OK")),
      h("td", {}, x.status, h("button", { onclick: act(() => api("POST", `/admin/users/${x.id}/status`, { suspended: x.status !== "suspended" }), "Statut modifié.", "Changer le statut du compte ?") }, x.status === "suspended" ? "Réactiver" : "Suspendre"))); });
  show(h("h1", {}, "Administration"), h("table", {}, h("tr", {}, h("th", {}, "E-mail"), h("th", {}, "Rôle"), h("th", {}, "Statut")), ...rows),
    h("h2", {}, "Journal d'audit"), h("small", {}, "Journal chaîné par hachage : aide à la traçabilité, pas une preuve juridique infaillible."), ...a.map(x => h("div", {}, `${date(x.ts)} · acteur ${x.actor} · ${x.action} · ${x.target}`)));
}
async function route() {
  try {
    if (!me) { try { me = await api("GET", "/me"); csrf = me.csrf; } catch { me = null; } }
    nav(); if (!me) return authView();
    const [, p, a] = location.hash.split("/");
    if (ADMIN) return me.role === "admin" ? await admin() : (say("Accès refusé", 1), show());
    await ({ bet: () => betView(a), me: mine, notifs, profile, new: newBet }[p] || home)();
  } catch (e) { say(e.message, 1); }
}
addEventListener("hashchange", route); route();
