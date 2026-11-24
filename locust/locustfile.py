import uuid
from locust import HttpUser, task, between


class Parieur(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        email = f"parieur-{uuid.uuid4().hex[:10]}@charge.test"
        self.client.post("/api/register", json={"email": email, "name": "Parieur", "password": "motdepasse-charge"})
        csrf = self.client.post("/api/login", json={"email": email, "password": "motdepasse-charge"}).json()["csrf"]
        self.client.headers["X-CSRF-Token"] = csrf
        pari = self.client.get("/api/bets?status=open", name="/api/bets").json()[0]
        self.bet = pari["id"]
        self.choice = self.client.get(f"/api/bets/{self.bet}", name="/api/bets/[id]").json()["choices"][0]["id"]

    @task(5)
    def consulter_le_pari(self):
        self.client.get(f"/api/bets/{self.bet}", name="/api/bets/[id]")

    @task(3)
    def parier(self):
        with self.client.post(f"/api/bets/{self.bet}/join", json={"choice_id": self.choice}, name="/api/bets/[id]/join", catch_response=True) as r:
            if r.status_code in (200, 409):
                r.success()

    @task(1)
    def annuler(self):
        with self.client.post(f"/api/bets/{self.bet}/leave", name="/api/bets/[id]/leave", catch_response=True) as r:
            if r.status_code in (200, 404):
                r.success()
