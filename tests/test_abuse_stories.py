import os, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toutbet as tb
from test_toutbet import C

PW = "motdepasse-demo-1"


class AbuseStories(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tb.DB = os.path.join(tempfile.mkdtemp(), "abuse.db"); tb.init(); db = tb.db()
        for e, r in [("admin@t.fr", "admin"), ("bookie@t.fr", "bookie"), ("bookie2@t.fr", "bookie"), ("alice@t.fr", "parieur"), ("bob@t.fr", "parieur")]:
            tb.mk_user(db, e, e[:4], PW, r)
        db.close()
        cls.srv = tb.serve(0); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def setUp(self): tb.HITS.clear(); tb.OFFSET[0] = 0

    def user(self, email):
        c = C(self.port); self.assertEqual(c.login(email), 200); return c

    def new_bet(self, bookie="bookie@t.fr", stake=500):
        bk = self.user(bookie)
        st, d = bk.r("POST", "/api/bets", {"title": "Abuse", "stake": stake, "closes_in_min": 10, "choices": [{"label": "A", "pct": 50}, {"label": "B", "pct": 50}]})
        self.assertEqual(st, 201)
        choices = bk.r("GET", f"/api/bets/{d['id']}")[1]["choices"]
        return bk, d["id"], choices[0]["id"], choices[1]["id"]

    def test_as01_modifier_pari_apres_cloture(self):
        bk, bid, a, b = self.new_bet(); alice = self.user("alice@t.fr")
        alice.r("POST", f"/api/bets/{bid}/join", {"choice_id": a})
        bk.r("POST", f"/api/bets/{bid}/close")
        self.assertEqual(alice.r("POST", f"/api/bets/{bid}/leave")[0], 409)
        self.assertEqual(alice.r("POST", f"/api/bets/{bid}/join", {"choice_id": b})[0], 409)

    def test_as02_miser_plus_que_son_solde(self):
        _, bid, a, _ = self.new_bet(stake=50000); alice = self.user("alice@t.fr")
        bal = alice.r("GET", "/api/me")[1]["bal"]
        self.assertEqual(alice.r("POST", f"/api/bets/{bid}/join", {"choice_id": a})[0], 409)
        self.assertEqual(alice.r("GET", "/api/me")[1]["bal"], bal)

    def test_as03_bookie_parie_sur_son_propre_pari(self):
        bk, bid, a, _ = self.new_bet()
        self.assertEqual(bk.r("POST", f"/api/bets/{bid}/join", {"choice_id": a})[0], 403)

    def test_as04_bookie_valide_un_resultat_conteste(self):
        bk, bid, a, b = self.new_bet(); alice = self.user("alice@t.fr")
        alice.r("POST", f"/api/bets/{bid}/join", {"choice_id": a})
        bk.r("POST", f"/api/bets/{bid}/close"); bk.r("POST", f"/api/bets/{bid}/result", {"choice_id": b})
        alice.r("POST", f"/api/bets/{bid}/vote", {"kind": "contest"})
        self.assertEqual(bk.r("POST", f"/api/bets/{bid}/settle")[0], 403)

    def test_as05_bookie_regle_le_pari_d_un_autre(self):
        _, bid, _, _ = self.new_bet(); autre = self.user("bookie2@t.fr")
        self.assertEqual(autre.r("POST", f"/api/bets/{bid}/close")[0], 403)

    def test_as06_resultat_hors_choix_du_pari(self):
        bk, bid, _, _ = self.new_bet(); bk.r("POST", f"/api/bets/{bid}/close")
        self.assertEqual(bk.r("POST", f"/api/bets/{bid}/result", {"choice_id": 999999})[0], 400)

    def test_as07_s_attribuer_un_role_ou_un_solde(self):
        c = C(self.port)
        c.r("POST", "/api/register", {"email": "pirate@t.fr", "name": "pirate", "password": PW, "role": "admin", "bal": 10**9})
        c.login("pirate@t.fr")
        c.r("PATCH", "/api/me", {"name": "pirate", "fullname": "x", "role": "bookie", "bal": 10**9})
        me = c.r("GET", "/api/me")[1]
        self.assertEqual((me["role"], me["bal"]), ("parieur", 10000))

    def test_as08_rejouer_un_retrait(self):
        bob = self.user("bob@t.fr"); bal = bob.r("GET", "/api/me")[1]["bal"]
        for _ in range(3): bob.r("POST", "/api/me/withdraw", {"amount_cents": 100, "key": "cle-rejeu-0001"})
        self.assertEqual(bob.r("GET", "/api/me")[1]["bal"], bal - 100)

    def test_as09_lire_l_historique_d_autrui(self):
        _, bid, a, _ = self.new_bet(); self.user("alice@t.fr").r("POST", f"/api/bets/{bid}/join", {"choice_id": a})
        bob = self.user("bob@t.fr")
        self.assertNotIn(bid, [x["id"] for x in bob.r("GET", "/api/me/history?uid=4")[1]])

    def test_as10_parier_deux_fois_sur_le_meme_pari(self):
        _, bid, a, b = self.new_bet(); alice = self.user("alice@t.fr")
        self.assertEqual(alice.r("POST", f"/api/bets/{bid}/join", {"choice_id": a})[0], 200)
        self.assertEqual(alice.r("POST", f"/api/bets/{bid}/join", {"choice_id": b})[0], 409)

    def test_as11_force_brute_du_mot_de_passe(self):
        c = C(self.port)
        for _ in range(5): c.login("alice@t.fr", "mauvais-mot-de-passe")
        self.assertEqual(c.login("alice@t.fr"), 429)

    def test_as12_parieur_accede_a_l_administration(self):
        alice = self.user("alice@t.fr")
        self.assertEqual(alice.r("GET", "/api/admin/users", extra={"X-Role": "admin"})[0], 403)
        self.assertEqual(alice.r("POST", "/api/admin/users/4/role", {"role": "admin"})[0], 403)

    def test_as13_action_sans_jeton_csrf(self):
        _, bid, a, _ = self.new_bet(); alice = self.user("alice@t.fr"); alice.csrf = ""
        self.assertEqual(alice.r("POST", f"/api/bets/{bid}/join", {"choice_id": a})[0], 403)

    def test_as14_retirer_plus_que_son_solde(self):
        bob = self.user("bob@t.fr"); bal = bob.r("GET", "/api/me")[1]["bal"]
        self.assertEqual(bob.r("POST", "/api/me/withdraw", {"amount_cents": bal + 1, "key": "cle-trop-grand-01"})[0], 409)
        self.assertEqual(bob.r("GET", "/api/me")[1]["bal"], bal)

    def test_as15_envoyer_une_fausse_notification(self):
        alice = self.user("alice@t.fr")
        self.assertIn(alice.r("POST", "/api/notifications", {"text": "Gagnez ici : http://phishing.test"})[0], (404, 405))

    def test_as16_script_dans_le_titre_d_un_pari(self):
        bk = self.user("bookie@t.fr")
        st, d = bk.r("POST", "/api/bets", {"title": "<script>alert(1)</script>", "stake": 100, "closes_in_min": 10, "choices": [{"label": "A", "pct": 50}, {"label": "B", "pct": 50}]})
        self.assertEqual(st, 201)
        self.assertEqual(bk.r("GET", f"/api/bets/{d['id']}")[1]["title"], "<script>alert(1)</script>")
        with open(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"), encoding="utf-8") as f:
            self.assertNotIn(".innerHTML", f.read())


if __name__ == "__main__":
    unittest.main()
