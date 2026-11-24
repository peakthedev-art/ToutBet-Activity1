import os, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toutbet as tb
from test_toutbet import C

PW = "motdepasse-demo-1"


class ParisSimultanes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tb.DB = os.path.join(tempfile.mkdtemp(), "conc.db"); tb.init(); db = tb.db()
        for e, r in [("bookie@t.fr", "bookie"), ("alice@t.fr", "parieur"), ("bob@t.fr", "parieur")]:
            tb.mk_user(db, e, e[:4], PW, r)
        db.close()
        cls.srv = tb.serve(0); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def setUp(self): tb.HITS.clear()

    def en_parallele(self, actions):
        depart, codes = threading.Barrier(len(actions)), []
        def lancer(action):
            depart.wait()
            try: codes.append(action())
            except OSError: codes.append("connexion refusee")
        threads = [threading.Thread(target=lancer, args=(a,)) for a in actions]
        for t in threads: t.start()
        for t in threads: t.join()
        return codes

    def test_paris_simultanes_meme_utilisateur(self):
        bk = C(self.port); bk.login("bookie@t.fr")
        paris = []
        for i in range(8):
            bid = bk.r("POST", "/api/bets", {"title": f"Pari {i}", "stake": 2500, "closes_in_min": 10, "choices": [{"label": "A", "pct": 50}, {"label": "B", "pct": 50}]})[1]["id"]
            paris.append((bid, bk.r("GET", f"/api/bets/{bid}")[1]["choices"][0]["id"]))
        alice = C(self.port); alice.login("alice@t.fr")
        solde = alice.r("GET", "/api/me")[1]["bal"]
        codes = self.en_parallele([lambda b=b, c=c: alice.r("POST", f"/api/bets/{b}/join", {"choice_id": c})[0] for b, c in paris])
        final = alice.r("GET", "/api/me")[1]["bal"]
        print(f"\n8 paris de 25 EUR lances en meme temps avec 100 EUR : {codes.count(200)} acceptes, {codes.count(409)} refuses, solde final {final / 100:.2f} EUR")
        self.assertEqual(codes.count(200), solde // 2500)
        self.assertEqual(final, solde - 2500 * codes.count(200))
        self.assertGreaterEqual(final, 0)

    def test_retraits_simultanes_meme_utilisateur(self):
        bob = C(self.port); bob.login("bob@t.fr")
        solde = bob.r("GET", "/api/me")[1]["bal"]
        codes = self.en_parallele([lambda i=i: bob.r("POST", "/api/me/withdraw", {"amount_cents": 1000, "key": f"retrait-{i}"})[0] for i in range(20)])
        final = bob.r("GET", "/api/me")[1]["bal"]
        print(f"\n20 retraits de 10 EUR lances en meme temps avec 100 EUR : {codes.count(200)} acceptes, solde final {final / 100:.2f} EUR")
        self.assertEqual(codes.count(200), solde // 1000)
        self.assertGreaterEqual(final, 0)


if __name__ == "__main__":
    unittest.main()
