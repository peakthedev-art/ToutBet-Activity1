"""ToutBet' - prototype DEMO (fonds fictifs). Python 3.9+, sans dépendance."""
import os, re, sys, json, time, sqlite3, secrets, hashlib, hmac, threading
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Base HORS du dépôt par défaut (données personnelles) : ~/.toutbet/toutbet.db
DB = os.environ.get("TOUTBET_DB") or os.path.join(os.path.expanduser("~"), ".toutbet", "toutbet.db")
SECURE = os.environ.get("TOUTBET_SECURE_COOKIE") == "1"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
OFFSET = [0]  # décalage d'horloge (tests uniquement)
def now(): return int(time.time()) + OFFSET[0]

SCHEMA = """
create table if not exists users(id integer primary key, email text unique not null, name text not null, fullname text not null default '', ph text not null, role text not null default 'parieur', status text not null default 'active', block_until integer not null default 0, bal integer not null default 0, ts integer);
create table if not exists sess(th text primary key, uid integer not null, csrf text not null, exp integer not null);
create table if not exists bets(id integer primary key, bookie integer not null, title text not null, stake integer not null, status text not null default 'open', closes_at integer not null, result integer, ts integer);
create table if not exists choices(id integer primary key, bet integer not null, label text not null, pct integer not null);
create table if not exists parts(id integer primary key, bet integer not null, uid integer not null, choice integer not null, stake integer not null, ts integer, unique(bet,uid));
create table if not exists txs(id integer primary key, uid integer not null, kind text not null, amt integer not null, bet integer, key text, ts integer, unique(uid,key));
create table if not exists notif(id integer primary key, uid integer not null, kind text, bet integer, text text not null, ts integer, seen integer default 0);
create table if not exists votes(bet integer, uid integer, kind text, comment text, ts integer, primary key(bet,uid));
create table if not exists audit(id integer primary key, ts integer, actor integer, action text, target text, bet integer, detail text, prev text, hash text);
"""
def db():
    d = os.path.dirname(DB)
    if d: os.makedirs(d, mode=0o700, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10, isolation_level=None); c.row_factory = sqlite3.Row; return c
def init():
    c = db(); c.executescript(SCHEMA)
    if "fullname" not in [r[1] for r in c.execute("pragma table_info(users)")]: c.execute("alter table users add column fullname text not null default ''")
    c.close()
    try: os.chmod(DB, 0o600)  # lisible uniquement par le propriétaire
    except OSError: pass

class Err(Exception):
    def __init__(s, st, msg): s.st, s.msg = st, msg

# ---------- Sécurité : mots de passe, limitation de débit ----------
def hp(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()
def vp(pw, h):
    s, k = h.split("$"); return hmac.compare_digest(hp(pw, bytes.fromhex(s)).split("$")[1], k)
DUMMY = hp("dummy-password")  # égalise le temps de réponse si l'e-mail est inconnu
HITS, LOCK = {}, threading.Lock()
def hit(key, n, per, add=True):
    """True si la limite est atteinte (DoS / force brute). Sinon enregistre l'appel."""
    with LOCK:
        t = time.time(); q = [x for x in HITS.get(key, []) if x > t - per]
        if len(q) >= n: HITS[key] = q; return True
        if add: q.append(t)
        HITS[key] = q; return False

# ---------- Utilitaires métier ----------
def S(v, lo, hi):
    if not isinstance(v, str) or not lo <= len(v.strip()) <= hi: raise Err(400, "Champ invalide")
    return v.strip()
def I(v, lo, hi):
    if type(v) is not int or not lo <= v <= hi: raise Err(400, "Nombre invalide")
    return v
def log(c, actor, action, target="", bet=None, detail=""):
    """Journal chaîné par hachage : détecte une altération simple, PAS une preuve juridique."""
    p = c.execute("select hash from audit order by id desc limit 1").fetchone()
    ph, ts = (p[0] if p else ""), now()
    h = hashlib.sha256(f"{ph}|{ts}|{actor}|{action}|{target}|{bet}|{detail}".encode()).hexdigest()
    c.execute("insert into audit(ts,actor,action,target,bet,detail,prev,hash) values(?,?,?,?,?,?,?,?)", (ts, actor, action, str(target), bet, detail, ph, h))
TPL = {"closed": "Le pari « {t} » est clôturé.", "joined": "Participation enregistrée au pari « {t} ».",
       "proposed": "Un résultat est proposé pour « {t} » : confirmez ou contestez.", "settled": "Le pari « {t} » est réglé."}
def notify(c, uid, kind, b):
    """Seul point de création de notification : gabarits fixes, texte brut, aucun lien, 100 max/utilisateur."""
    c.execute("insert into notif(uid,kind,bet,text,ts) values(?,?,?,?,?)", (uid, kind, b["id"], "[ToutBet' · démo] " + TPL[kind].format(t=b["title"][:60]), now()))
    c.execute("delete from notif where uid=? and id not in (select id from notif where uid=? order by id desc limit 100)", (uid, uid))
def tx(c, uid, kind, amt, bet=None, key=None):
    if amt < 0:
        if c.execute("update users set bal=bal+? where id=? and bal>=?", (amt, uid, -amt)).rowcount != 1: raise Err(409, "Solde insuffisant")
    else: c.execute("update users set bal=bal+? where id=?", (amt, uid))
    c.execute("insert into txs(uid,kind,amt,bet,key,ts) values(?,?,?,?,?,?)", (uid, kind, amt, bet, key, now()))
def sweep(c):
    for b in c.execute("select * from bets where status='open' and closes_at<=? limit 50", (now(),)).fetchall():
        c.execute("update bets set status='closed' where id=?", (b["id"],))
        for r in c.execute("select uid from parts where bet=?", (b["id"],)).fetchall(): notify(c, r[0], "closed", b)
def mk_user(c, email, name, pw, role="parieur", bal=10000):
    uid = c.execute("insert into users(email,name,ph,role,ts) values(?,?,?,?,?)", (email.lower(), name, hp(pw), role, now())).lastrowid
    tx(c, uid, "credit_fictif", bal); return uid
def get_bet(c, bid):
    b = c.execute("select * from bets where id=?", (bid,)).fetchone()
    if not b: raise Err(404, "Pari introuvable")
    return b
def pub(c, b, uid):
    tot = c.execute("select count(*) from parts where bet=?", (b["id"],)).fetchone()[0]
    # cote estimée = 100/probabilité du Bookie ; cote actuelle = cagnotte / mises sur ce choix (gain réel, partagé entre gagnants)
    ch = [dict(id=r[0], label=r[1], pct=r[2], n=r[3], cote=round(100 / r[2], 2), cote_live=round(tot / r[3], 2) if r[3] else None)
          for r in c.execute("select id,label,pct,(select count(*) from parts p where p.choice=choices.id) from choices where bet=? order by id", (b["id"],))]
    mine = c.execute("select choice from parts where bet=? and uid=?", (b["id"], uid)).fetchone()
    return dict(id=b["id"], title=b["title"], stake=b["stake"], status=b["status"], closes_at=b["closes_at"], choices=ch,
                n=c.execute("select count(*) from parts where bet=?", (b["id"],)).fetchone()[0], mine=mine[0] if mine else None,
                owner=b["bookie"] == uid, result=b["result"])
def page(x):
    try: return max(0, min(1000, int(x.q.get("page", ["0"])[0])))
    except ValueError: return 0
def owner_or_admin(u, b):
    if b["bookie"] != u["id"] and u["role"] != "admin": raise Err(403, "Action réservée au Bookie du pari ou à un administrateur")

# ---------- Routes ----------
R = []
def route(m, p, role=None):
    def d(f): R.append((m, re.compile("^" + p + "$"), f, role)); return f
    return d
class X:  # contexte de requête
    def __init__(s, **k): s.__dict__.update(k)

def session_cookie(tok, age): return f"tb={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}" + ("; Secure" if SECURE else "")
def me_json(u): return dict(id=u["id"], email=u["email"], name=u["name"], fullname=u["fullname"], role=u["role"], bal=u["bal"], block_until=u["block_until"], csrf=u["csrf"])

@route("POST", "/api/register")
def register(x):
    if hit(f"reg:{x.ip}", 5, 3600): raise Err(429, "Trop d'inscriptions, réessayez plus tard")
    e, n, p = S(x.b.get("email"), 5, 120).lower(), S(x.b.get("name"), 2, 30), x.b.get("password")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e): raise Err(400, "E-mail invalide")
    if not isinstance(p, str) or not 10 <= len(p) <= 100: raise Err(400, "Mot de passe : 10 caractères minimum")
    try: uid = mk_user(x.c, e, n, p)  # le rôle envoyé par le client est ignoré : toujours « parieur »
    except sqlite3.IntegrityError: raise Err(409, "Inscription impossible avec ces informations")
    log(x.c, uid, "register", uid); return 201, {"ok": True}

@route("POST", "/api/login")
def login(x):
    e = str(x.b.get("email", ""))[:120].lower(); k1, k2 = f"lf:ip:{x.ip}", f"lf:em:{e}"
    if hit(k1, 20, 900, False) or hit(k2, 5, 900, False): raise Err(429, "Trop de tentatives, réessayez dans 15 minutes")
    u = x.c.execute("select * from users where email=?", (e,)).fetchone()
    ok = vp(str(x.b.get("password", ""))[:100], u["ph"] if u else DUMMY) and u and u["status"] != "suspended"
    if not ok: hit(k1, 20, 900); hit(k2, 5, 900); raise Err(401, "Identifiants invalides")
    tok, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(16)  # nouveau jeton à chaque connexion
    x.c.execute("delete from sess where exp<?", (now(),))
    x.c.execute("insert into sess values(?,?,?,?)", (hashlib.sha256(tok.encode()).hexdigest(), u["id"], csrf, now() + 8 * 3600))
    x.cookie = session_cookie(tok, 28800); log(x.c, u["id"], "login", u["id"])
    return 200, me_json(dict(u, csrf=csrf))

@route("POST", "/api/logout", "u")
def logout(x):
    x.c.execute("delete from sess where th=?", (x.u["th"],)); x.cookie = session_cookie("", 0); return 200, {"ok": True}
@route("GET", "/api/me", "u")
def me(x): return 200, me_json(x.u)
@route("PATCH", "/api/me", "u")
def patch_me(x):  # liste blanche : pseudo et nom uniquement (jamais rôle, solde, statut, e-mail)
    n = S(x.b["name"], 2, 30) if "name" in x.b else x.u["name"]
    f = str(x.b["fullname"]).strip()[:60] if "fullname" in x.b else x.u["fullname"]
    x.c.execute("update users set name=?, fullname=? where id=?", (n, f, x.u["id"])); log(x.c, x.u["id"], "profile_update", x.u["id"]); return 200, {"ok": True}
@route("POST", "/api/me/email", "u")
def set_email(x):  # action sensible : mot de passe actuel exigé
    if hit(f"em:{x.u['id']}", 5, 3600): raise Err(429, "Trop de tentatives, réessayez plus tard")
    e = S(x.b.get("email"), 5, 120).lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e): raise Err(400, "E-mail invalide")
    if not vp(str(x.b.get("password", ""))[:100], x.u["ph"]): raise Err(403, "Mot de passe actuel incorrect")
    try: x.c.execute("update users set email=? where id=?", (e, x.u["id"]))
    except sqlite3.IntegrityError: raise Err(409, "Cette adresse n'est pas disponible")
    log(x.c, x.u["id"], "email_change", x.u["id"]); return 200, {"ok": True}
@route("POST", "/api/me/password", "u")
def set_password(x):
    if hit(f"pw:{x.u['id']}", 5, 900): raise Err(429, "Trop de tentatives, réessayez plus tard")
    new = x.b.get("new")
    if not vp(str(x.b.get("current", ""))[:100], x.u["ph"]): raise Err(403, "Mot de passe actuel incorrect")
    if not isinstance(new, str) or not 10 <= len(new) <= 100: raise Err(400, "Nouveau mot de passe : 10 caractères minimum")
    x.c.execute("update users set ph=? where id=?", (hp(new), x.u["id"]))
    x.c.execute("delete from sess where uid=? and th!=?", (x.u["id"], x.u["th"]))  # déconnecte les autres appareils
    log(x.c, x.u["id"], "password_change", x.u["id"]); return 200, {"ok": True}
@route("POST", "/api/me/block", "u")
def block(x):
    d = x.b.get("days")
    if d not in (1, 7, 30) or type(d) is not int: raise Err(400, "Durée : 1, 7 ou 30 jours")
    until = max(x.u["block_until"], now() + d * 86400)  # ne peut jamais être raccourci par l'utilisateur
    x.c.execute("update users set block_until=? where id=?", (until, x.u["id"])); log(x.c, x.u["id"], "self_block", x.u["id"], detail=f"{d}j")
    return 200, {"block_until": until}

@route("GET", "/api/bets", "u")
def bets(x):
    st = x.q.get("status", ["open"])[0]
    if st not in ("open", "closed", "proposed", "settled"): raise Err(400, "Statut invalide")
    rows = x.c.execute("select * from bets where status=? order by closes_at limit 20 offset ?", (st, page(x) * 20)).fetchall()
    return 200, [pub(x.c, b, x.u["id"]) for b in rows]
@route("GET", r"/api/bets/(\d+)", "u")
def bet(x): return 200, pub(x.c, get_bet(x.c, int(x.g[0])), x.u["id"])

@route("POST", "/api/bets", "bookie")
def create_bet(x):
    if hit(f"mk:{x.u['id']}", 10, 3600): raise Err(429, "Trop de créations")
    t, stake, mins, ch = S(x.b.get("title"), 3, 80), I(x.b.get("stake"), 100, 50000), I(x.b.get("closes_in_min"), 5, 10080), x.b.get("choices")
    if not isinstance(ch, list) or not 2 <= len(ch) <= 6: raise Err(400, "2 à 6 choix")
    labels = [S(c.get("label") if isinstance(c, dict) else None, 1, 40) for c in ch]
    pcts = [I(c.get("pct"), 1, 99) for c in ch]
    if sum(pcts) != 100: raise Err(400, "Les probabilités doivent totaliser 100 %")
    bid = x.c.execute("insert into bets(bookie,title,stake,closes_at,ts) values(?,?,?,?,?)", (x.u["id"], t, stake, now() + mins * 60, now())).lastrowid
    for l, p in zip(labels, pcts): x.c.execute("insert into choices(bet,label,pct) values(?,?,?)", (bid, l, p))
    log(x.c, x.u["id"], "bet_create", bid, bid); return 201, {"id": bid}

@route("POST", r"/api/bets/(\d+)/join", "u")
def join(x):
    b, u = get_bet(x.c, int(x.g[0])), x.u
    if u["block_until"] > now(): raise Err(403, "Votre compte est en blocage volontaire")
    if b["status"] != "open": raise Err(409, "Ce pari est clôturé")
    if b["bookie"] == u["id"]: raise Err(403, "Un Bookie ne peut pas parier sur son propre pari")
    if not x.c.execute("select 1 from choices where id=? and bet=?", (I(x.b.get("choice_id"), 1, 10**9), b["id"])).fetchone(): raise Err(400, "Choix invalide")
    if x.c.execute("select count(*) from parts where bet=?", (b["id"],)).fetchone()[0] >= 200: raise Err(409, "Pari complet")
    try: x.c.execute("insert into parts(bet,uid,choice,stake,ts) values(?,?,?,?,?)", (b["id"], u["id"], x.b["choice_id"], b["stake"], now()))
    except sqlite3.IntegrityError: raise Err(409, "Vous participez déjà à ce pari")
    tx(x.c, u["id"], "mise", -b["stake"], b["id"]); notify(x.c, u["id"], "joined", b); log(x.c, u["id"], "join", u["id"], b["id"])
    return 200, {"ok": True}
@route("POST", r"/api/bets/(\d+)/leave", "u")
def leave(x):
    b, u = get_bet(x.c, int(x.g[0])), x.u
    if b["status"] != "open": raise Err(409, "Impossible d'annuler : le pari est clôturé")
    p = x.c.execute("select * from parts where bet=? and uid=?", (b["id"], u["id"])).fetchone()
    if not p: raise Err(404, "Aucune participation")
    x.c.execute("delete from parts where id=?", (p["id"],)); tx(x.c, u["id"], "remboursement", p["stake"], b["id"]); log(x.c, u["id"], "leave", u["id"], b["id"])
    return 200, {"ok": True}
@route("POST", r"/api/bets/(\d+)/close", "bookie")
def close(x):
    b = get_bet(x.c, int(x.g[0])); owner_or_admin(x.u, b)
    if b["status"] != "open": raise Err(409, "Déjà clôturé")
    x.c.execute("update bets set status='closed' where id=?", (b["id"],))
    for r in x.c.execute("select uid from parts where bet=?", (b["id"],)).fetchall(): notify(x.c, r[0], "closed", b)
    log(x.c, x.u["id"], "close", b["id"], b["id"]); return 200, {"ok": True}
@route("POST", r"/api/bets/(\d+)/result", "bookie")
def result(x):
    b = get_bet(x.c, int(x.g[0])); owner_or_admin(x.u, b)
    if b["status"] != "closed": raise Err(409, "Le pari doit être clôturé")
    cid = I(x.b.get("choice_id"), 1, 10**9)
    if not x.c.execute("select 1 from choices where id=? and bet=?", (cid, b["id"])).fetchone(): raise Err(400, "Choix invalide")
    x.c.execute("update bets set status='proposed', result=? where id=?", (cid, b["id"]))
    for r in x.c.execute("select uid from parts where bet=?", (b["id"],)).fetchall(): notify(x.c, r[0], "proposed", b)
    log(x.c, x.u["id"], "result_proposed", b["id"], b["id"], f"choice={cid}"); return 200, {"ok": True}
@route("POST", r"/api/bets/(\d+)/vote", "u")
def vote(x):
    b, u = get_bet(x.c, int(x.g[0])), x.u
    k = x.b.get("kind")
    if b["status"] != "proposed" or k not in ("confirm", "contest"): raise Err(409, "Vote impossible")
    if not x.c.execute("select 1 from parts where bet=? and uid=?", (b["id"], u["id"])).fetchone(): raise Err(403, "Réservé aux participants")
    x.c.execute("insert or replace into votes values(?,?,?,?,?)", (b["id"], u["id"], k, str(x.b.get("comment", ""))[:200], now()))
    log(x.c, u["id"], "vote_" + k, u["id"], b["id"]); return 200, {"ok": True}
@route("POST", r"/api/bets/(\d+)/settle", "bookie")
def settle(x):
    b = get_bet(x.c, int(x.g[0])); owner_or_admin(x.u, b)
    if b["status"] != "proposed": raise Err(409, "Aucun résultat à valider")
    if x.u["role"] != "admin" and x.c.execute("select 1 from votes where bet=? and kind='contest'", (b["id"],)).fetchone():
        raise Err(403, "Résultat contesté : arbitrage d'un administrateur requis")
    ps = x.c.execute("select * from parts where bet=? order by id", (b["id"],)).fetchall()
    win = [p for p in ps if p["choice"] == b["result"]]
    pot = sum(p["stake"] for p in ps)
    if win:
        share = pot // len(win)
        for i, p in enumerate(win): tx(x.c, p["uid"], "gain", share + (pot - share * len(win) if i == 0 else 0), b["id"])
    else:
        for p in ps: tx(x.c, p["uid"], "remboursement", p["stake"], b["id"])
    x.c.execute("update bets set status='settled' where id=?", (b["id"],))
    for p in ps: notify(x.c, p["uid"], "settled", b)
    log(x.c, x.u["id"], "settled", b["id"], b["id"]); return 200, {"ok": True}

@route("GET", "/api/me/history", "u")
def history(x):  # uniquement l'utilisateur authentifié : aucun identifiant accepté
    rows = x.c.execute("select b.id,b.title,b.status,b.result,p.choice,p.stake from parts p join bets b on b.id=p.bet where p.uid=? order by p.id desc limit 20 offset ?", (x.u["id"], page(x) * 20))
    return 200, [dict(r) for r in rows]
@route("GET", "/api/me/stats", "u")
def stats(x):
    q = lambda s: x.c.execute(s, (x.u["id"],)).fetchone()[0]
    return 200, dict(paris=q("select count(*) from parts where uid=?"), mises=q("select coalesce(sum(stake),0) from parts where uid=?"),
                     gains=q("select coalesce(sum(amt),0) from txs where uid=? and kind='gain'"),
                     victoires=q("select count(*) from parts p join bets b on b.id=p.bet where p.uid=? and b.status='settled' and p.choice=b.result"))
@route("GET", "/api/me/wallet", "u")
def wallet(x):
    rows = x.c.execute("select kind,amt,bet,ts from txs where uid=? order by id desc limit 20 offset ?", (x.u["id"], page(x) * 20))
    return 200, dict(bal=x.u["bal"], txs=[dict(r) for r in rows])
@route("POST", "/api/me/withdraw", "u")
def withdraw(x):
    amt, key = I(x.b.get("amount_cents"), 1, 10**7), S(x.b.get("key"), 8, 64)  # clé d'idempotence (anti double opération)
    if x.c.execute("select 1 from txs where uid=? and key=?", (x.u["id"], key)).fetchone(): return 200, {"ok": True, "duplicate": True}
    tx(x.c, x.u["id"], "retrait_fictif", -amt, key=key); log(x.c, x.u["id"], "withdraw", x.u["id"], detail=str(amt))
    return 200, {"ok": True}
@route("GET", "/api/notifications", "u")
def notifs(x):
    rows = x.c.execute("select id,text,ts,seen from notif where uid=? order by id desc limit 20 offset ?", (x.u["id"], page(x) * 20))
    return 200, [dict(r) for r in rows]
@route("POST", "/api/notifications/read", "u")
def read(x): x.c.execute("update notif set seen=1 where uid=?", (x.u["id"],)); return 200, {"ok": True}

@route("GET", "/api/admin/users", "admin")
def a_users(x):
    rows = x.c.execute("select id,email,name,role,status,block_until from users order by id limit 50 offset ?", (page(x) * 50,))
    return 200, [dict(r) for r in rows]
@route("POST", r"/api/admin/users/(\d+)/role", "admin")
def a_role(x):
    uid, r = int(x.g[0]), x.b.get("role")
    if r not in ("parieur", "bookie", "admin") or uid == x.u["id"]: raise Err(400, "Changement refusé")
    if x.c.execute("update users set role=? where id=?", (r, uid)).rowcount != 1: raise Err(404, "Utilisateur introuvable")
    log(x.c, x.u["id"], "role_change", uid, detail=r); return 200, {"ok": True}
@route("POST", r"/api/admin/users/(\d+)/status", "admin")
def a_status(x):
    uid, s = int(x.g[0]), x.b.get("suspended")
    if type(s) is not bool or uid == x.u["id"]: raise Err(400, "Changement refusé")
    if x.c.execute("update users set status=? where id=?", ("suspended" if s else "active", uid)).rowcount != 1: raise Err(404, "Utilisateur introuvable")
    if s: x.c.execute("delete from sess where uid=?", (uid,))  # révoque les sessions
    log(x.c, x.u["id"], "suspend" if s else "unsuspend", uid); return 200, {"ok": True}
@route("GET", "/api/admin/audit", "admin")
def a_audit(x):
    rows = x.c.execute("select ts,actor,action,target,bet,detail from audit order by id desc limit 50 offset ?", (page(x) * 50,))
    return 200, [dict(r) for r in rows]

# ---------- Serveur HTTP ----------
FILES = {"/": ("index.html", "text/html"), "/admin": ("admin.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
HDR = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
       "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}
def auth(c, h):
    m = SimpleCookie(h.get("Cookie", "")).get("tb")
    if not m: return None
    r = c.execute("select u.*, s.csrf, s.th from sess s join users u on u.id=s.uid where s.th=? and s.exp>?", (hashlib.sha256(m.value.encode()).hexdigest(), now())).fetchone()
    return dict(r) if r and r["status"] != "suspended" else None  # rôle relu en base à chaque requête

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, st, data, ctype="application/json", cookie=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(st); self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Content-Length", str(len(body)))
        for k, v in HDR.items(): self.send_header(k, v)
        if ctype == "application/json": self.send_header("Cache-Control", "no-store")
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers(); self.wfile.write(body)
    def handle_req(self):
        u = urlparse(self.path); ip = self.client_address[0]
        if not u.path.startswith("/api/"):
            f = FILES.get(u.path)
            if self.command != "GET" or not f: return self.out(404, {"error": "Introuvable"})
            return self.out(200, open(os.path.join(STATIC, f[0]), "rb").read(), f[1])
        if hit(f"ip:{ip}", 300, 60): return self.out(429, {"error": "Trop de requêtes"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 16384: return self.out(413, {"error": "Requête trop volumineuse"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict): raise ValueError
        except ValueError: return self.out(400, {"error": "JSON invalide"})
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE"); sweep(c); usr = auth(c, self.headers)
            for m, rx, f, role in R:
                g = rx.match(u.path)
                if m != self.command or not g: continue
                if role and not usr: raise Err(401, "Connexion requise")
                if role == "bookie" and usr["role"] not in ("bookie", "admin"): raise Err(403, "Réservé aux Bookies")
                if role == "admin" and usr["role"] != "admin": raise Err(403, "Réservé aux administrateurs")
                if usr and self.command != "GET":
                    if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), usr["csrf"]): raise Err(403, "Jeton CSRF invalide")
                    if hit(f"w:{usr['id']}", 30, 60): raise Err(429, "Trop d'actions, patientez")
                x = X(c=c, u=usr, b=body, q=parse_qs(u.query), g=g.groups(), ip=ip, cookie=None)
                st, data = f(x); c.execute("COMMIT"); return self.out(st, data, cookie=x.cookie)
            raise Err(404, "Introuvable")
        except Err as e:
            if c.in_transaction: c.execute("ROLLBACK")
            self.out(e.st, {"error": e.msg})
        except Exception:
            if c.in_transaction: c.execute("ROLLBACK")
            self.out(500, {"error": "Erreur interne"})
        finally: c.close()
    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = handle_req

def serve(port=8000):
    init(); return ThreadingHTTPServer(("127.0.0.1", port), H)

DEMO = [("Qui gagne le match de samedi ?", 500, 5, [("Équipe A", 55), ("Équipe B", 45)]),
        ("Quel temps dimanche ?", 200, 3, [("Soleil", 40), ("Nuages", 35), ("Pluie", 25)]),
        ("Vainqueur du quiz du vendredi", 300, 7, [("Camille", 30), ("Yanis", 30), ("Léa", 25), ("Hugo", 15)]),
        ("Le colis arrive avant mardi ?", 100, 2, [("Oui", 65), ("Non", 35)])]
def seed_bets(c, bookie_id):
    n = 0
    for t, st, d, ch in DEMO:
        if c.execute("select 1 from bets where title=? and bookie=? and status='open'", (t, bookie_id)).fetchone(): continue  # ne recrée que ce qui n'est plus ouvert
        bid = c.execute("insert into bets(bookie,title,stake,closes_at,ts) values(?,?,?,?,?)", (bookie_id, t, st, now() + d * 86400, now())).lastrowid
        for l, p in ch: c.execute("insert into choices(bet,label,pct) values(?,?,?)", (bid, l, p))
        n += 1
    return n
def more_bets():
    init(); c = db(); r = c.execute("select id from users where email='bookie@demo.test'").fetchone()
    print(f"{seed_bets(c, r[0])} pari(s) de démonstration ajouté(s)." if r else "Compte bookie@demo.test introuvable : lancez d'abord --seed."); c.close()
def ensure_demo():
    """Démo uniquement (désactivable : TOUTBET_NO_DEMO=1) : garantit des comptes et des paris ouverts au démarrage."""
    init(); c = db()
    try:
        if c.execute("select count(*) from users").fetchone()[0] == 0: c.close(); return seed()
        if c.execute("select 1 from bets where status='open' and closes_at>?", (now(),)).fetchone(): return
        r = c.execute("select id from users where email='bookie@demo.test'").fetchone()
        if r: print(f"Aucun pari ouvert : {seed_bets(c, r[0])} pari(s) de démonstration recréé(s).")
        else:
            pw = secrets.token_urlsafe(9); uid = mk_user(c, "bookie@demo.test", "Bookie", pw, "bookie"); n = seed_bets(c, uid)
            print(f"Aucun pari ouvert : compte Bookie de démo créé (affiché une seule fois)\n  bookie@demo.test  {pw}\n{n} paris de démonstration ajoutés.")
    finally: c.close()
def seed():
    init(); c = db(); pw = {}
    for e, n, r in [("admin@demo.test", "Admin", "admin"), ("bookie@demo.test", "Bookie", "bookie"), ("alice@demo.test", "Alice", "parieur"), ("bob@demo.test", "Bob", "parieur")]:
        pw[e] = secrets.token_urlsafe(9); mk_user(c, e, n, pw[e], r)  # mots de passe aléatoires, affichés une seule fois
    seed_bets(c, 2)
    c.close(); print(f"Base : {DB}\nComptes de démonstration (affichés une seule fois) :")
    for e, p in pw.items(): print(f"  {e}  {p}")

if __name__ == "__main__":
    if "--seed" in sys.argv: seed()
    elif "--more-bets" in sys.argv: more_bets()
    else:
        if os.environ.get("TOUTBET_NO_DEMO") != "1": ensure_demo()
        port = int(os.environ.get("PORT", 8000)); print(f"ToutBet' DÉMO (fonds fictifs) sur http://127.0.0.1:{port}"); serve(port).serve_forever()
