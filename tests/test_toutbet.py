import os, sys, json, http.client, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toutbet as tb

class C:  # client HTTP minimal (cookie + CSRF)
    def __init__(s, port): s.port, s.tok, s.csrf = port, None, ""
    def r(s, m, p, b=None, extra=None):
        h = http.client.HTTPConnection("127.0.0.1", s.port); hd = {"Content-Type": "application/json", **(extra or {})}
        if s.tok: hd["Cookie"] = "tb=" + s.tok
        if s.csrf: hd["X-CSRF-Token"] = s.csrf
        h.request(m, p, json.dumps(b) if b is not None else None, hd); R = h.getresponse(); d = json.loads(R.read() or b"{}")
        sc = R.getheader("Set-Cookie")
        if sc and sc.startswith("tb="): s.tok = sc.split(";")[0][3:]
        return R.status, d
    def login(s, e, p="motdepasse-demo-1"):
        st, d = s.r("POST", "/api/login", {"email": e, "password": p}); s.csrf = d.get("csrf", ""); return st

class T(unittest.TestCase):
    @classmethod
    def setUpClass(c):
        tb.DB = os.path.join(tempfile.mkdtemp(), "t.db"); tb.init(); db = tb.db()
        for e, r in [("admin@t.fr", "admin"), ("bookie@t.fr", "bookie"), ("alice@t.fr", "parieur"), ("bob@t.fr", "parieur")]: tb.mk_user(db, e, e[:3], "motdepasse-demo-1", r)
        db.close(); c.srv = tb.serve(0); c.port = c.srv.server_address[1]; threading.Thread(target=c.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(c): c.srv.shutdown()
    def setUp(s): tb.HITS.clear(); tb.OFFSET[0] = 0
    def user(s, e): c = C(s.port); assert c.login(e) == 200; return c
    def bet(s):
        bk = s.user("bookie@t.fr"); st, d = bk.r("POST", "/api/bets", {"title": "Test", "stake": 500, "closes_in_min": 10, "choices": [{"label": "A", "pct": 60}, {"label": "B", "pct": 40}]})
        assert st == 201; return bk, d["id"]

    def test_unauthenticated(s): s.assertEqual(C(s.port).r("GET", "/api/me/history")[0], 401)
    def test_register_ignores_role(s):
        c = C(s.port); c.r("POST", "/api/register", {"email": "x@t.fr", "name": "xx", "password": "motdepasse-demo-1", "role": "admin"}); c.login("x@t.fr")
        s.assertEqual(c.r("GET", "/api/me")[1]["role"], "parieur")
    def test_login_throttle(s):
        c = C(s.port)
        for _ in range(5): s.assertEqual(c.login("alice@t.fr", "mauvais-mot-de-passe"), 401)
        s.assertEqual(c.login("alice@t.fr"), 429)
    def test_csrf_required(s):
        c = s.user("alice@t.fr"); c.csrf = ""; s.assertEqual(c.r("POST", "/api/me/block", {"days": 1})[0], 403)
    def test_history_idor(s):
        _, bid = s.bet(); a, b = s.user("alice@t.fr"), s.user("bob@t.fr")
        s.assertEqual(a.r("POST", f"/api/bets/{bid}/join", {"choice_id": 1})[0], 200)
        s.assertEqual(len(a.r("GET", "/api/me/history")[1]), 1)
        s.assertEqual(b.r("GET", "/api/me/history?uid=3&user_id=3")[1], [])  # paramètre d'identifiant ignoré
        s.assertEqual(b.r("GET", "/api/users/3/history")[0], 404)
    def test_closed_bet_immutable(s):
        bk, bid = s.bet(); a, b = s.user("alice@t.fr"), s.user("bob@t.fr"); a.r("POST", f"/api/bets/{bid}/join", {"choice_id": 1})
        tb.OFFSET[0] = 3600  # l'échéance est dépassée
        s.assertEqual(a.r("POST", f"/api/bets/{bid}/leave")[0], 409)
        s.assertEqual(b.r("POST", f"/api/bets/{bid}/join", {"choice_id": 1})[0], 409)
    def test_no_probability_edit(s):
        _, bid = s.bet(); a = s.user("alice@t.fr")
        for m, p in [("PATCH", f"/api/bets/{bid}"), ("PUT", f"/api/bets/{bid}"), ("POST", f"/api/bets/{bid}/choices")]: s.assertIn(a.r(m, p, {"pct": 99})[0], (404, 405))
    def test_self_block(s):
        _, bid = s.bet(); a = s.user("alice@t.fr"); a.r("POST", "/api/me/block", {"days": 30})
        s.assertEqual(a.r("POST", f"/api/bets/{bid}/join", {"choice_id": 1})[0], 403)
        until = a.r("GET", "/api/me")[1]["block_until"]; a.r("POST", "/api/me/block", {"days": 1})
        s.assertEqual(a.r("GET", "/api/me")[1]["block_until"], until)  # impossible de raccourcir
    def test_roles(s):
        a = s.user("alice@t.fr")
        s.assertEqual(a.r("POST", "/api/bets", {})[0], 403)
        s.assertEqual(a.r("GET", "/api/admin/users", extra={"X-Role": "admin"})[0], 403)
        s.assertEqual(a.r("POST", "/api/admin/users/3/role", {"role": "admin"})[0], 403)
        s.assertEqual(s.user("bookie@t.fr").r("GET", "/api/admin/audit")[0], 403)
        s.assertEqual(s.user("admin@t.fr").r("GET", "/api/admin/users")[0], 200)
    def test_non_owner_cannot_settle(s):
        _, bid = s.bet(); s.assertEqual(s.user("alice@t.fr").r("POST", f"/api/bets/{bid}/close")[0], 403)
    def test_withdraw(s):
        a = s.user("alice@t.fr"); bal = a.r("GET", "/api/me")[1]["bal"]
        s.assertEqual(a.r("POST", "/api/me/withdraw", {"amount_cents": bal + 1, "key": "cle-trop-grand"})[0], 409)
        s.assertEqual(a.r("POST", "/api/me/withdraw", {"amount_cents": -5, "key": "cle-negative"})[0], 400)
        for _ in range(2): a.r("POST", "/api/me/withdraw", {"amount_cents": 100, "key": "cle-unique-1", "user_id": 4})
        s.assertEqual(a.r("GET", "/api/me")[1]["bal"], bal - 100)  # une seule fois, et sur son propre compte
    def test_suspension_revokes_session(s):
        b = s.user("bob@t.fr"); ad = s.user("admin@t.fr"); bid = b.r("GET", "/api/me")[1]["id"]
        s.assertEqual(ad.r("POST", f"/api/admin/users/{bid}/status", {"suspended": True})[0], 200)
        s.assertEqual(b.r("GET", "/api/me")[0], 401); s.assertEqual(C(s.port).login("bob@t.fr"), 401)
        ad.r("POST", f"/api/admin/users/{bid}/status", {"suspended": False})
    def test_no_notification_injection(s):
        a = s.user("alice@t.fr"); s.assertIn(a.r("POST", "/api/notifications", {"text": "http://phishing"})[0], (404, 405))

if __name__ == "__main__": unittest.main()
