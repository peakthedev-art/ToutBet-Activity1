# ToutBet' – prototype de démonstration

> **DÉMO : tous les soldes, mises, gains et retraits sont fictifs.** Aucun paiement réel, aucune carte. Ce prototype n'est **pas prêt pour un lancement commercial** (pas d'audit, pas de HTTPS intégré, SQLite, limites en mémoire).

**Pile :** Python 3.9+ standard (aucune dépendance, aucun `pip install`), SQLite, front JS vanilla mobile-first. Choix : dépôt vide, sandbox sans réseau, surface d'attaque réduite.

## Démarrer
```bash
cd toutbet
python3 toutbet.py --seed        # crée la base + comptes démo (mots de passe aléatoires affichés une fois)
python3 toutbet.py --more-bets   # (facultatif) ajoute 3 paris de démo supplémentaires, sans doublon
python3 toutbet.py               # http://127.0.0.1:8000  (administration : /admin)
python3 -m unittest discover -s tests -v   # tests
```
Variables : `PORT`, `TOUTBET_DB` (chemin de la base, défaut `~/.toutbet/toutbet.db`), `TOUTBET_SECURE_COOKIE=1` (derrière HTTPS). Aucun secret dans le code. Au démarrage, le mode démo crée comptes et paris si la base est vide ou s'il n'y a plus de pari ouvert (désactivable : `TOUTBET_NO_DEMO=1`).
> Les tests n'ont **pas été exécutés** lors de la génération : lancez-les vous-même.

## Où sont les protections (`toutbet.py`)
| STRIDE | Menace | Composant / protection | Comment vérifier |
|---|---|---|---|
| Spoofing | Connexion au compte d'autrui | `hp/vp` (scrypt + sel), `login` (5 échecs/15 min par e-mail, 20 par IP, message générique, hash factice), `auth` + cookie `HttpOnly; SameSite=Strict`, session hachée en base, jeton renouvelé à chaque connexion, CSRF | `test_login_throttle`, `test_csrf_required`, `test_unauthenticated` |
| Tampering | Modifier mise/probabilités/pari clôturé | Aucune route de modification des mises/probabilités ; `join`/`leave` testent `status='open'` côté serveur ; `sweep` clôture à l'échéance ; mise lue en base | `test_closed_bet_immutable`, `test_no_probability_edit` |
| Repudiation | « Ce n'est pas moi » / résultat contesté | `log` (acteur, heure, pari/compte, chaîne de hachage), table `votes` (confirmation/contestation), `settle` bloqué si contesté | Admin → journal ; test manuel 6 |
| Info disclosure | Lire l'historique d'autrui | Routes `/api/me/*` sans identifiant (l'utilisateur vient de la session), champs minimaux, CSP + `textContent` | `test_history_idor` |
| DoS | Requêtes / notifications en masse | `hit` : 300 req/min/IP, 30 écritures/min/compte ; corps ≤16 Ko ; pages de 20 ; 200 participants/pari ; 100 notifications/compte ; `sweep` ≤50 | Spammer `/api/me/block` → 429 |
| Elevation | Devenir Bookie/admin | Rôle relu en base à chaque requête (`auth`), `route(..., role)`, inscription ignore `role`, seuls les admins changent rôle/statut (`a_role`, `a_status`), auto-modification refusée | `test_roles`, `test_register_ignores_role`, `test_suspension_revokes_session` |

**Notifications :** créées uniquement par `notify` (gabarits fixes, texte brut, sans lien). Aucune route ne permet d'en envoyer (`test_no_notification_injection`).
**Argent fictif :** `tx` (débit conditionnel `bal>=montant`), clé d'idempotence sur les retraits, jamais d'identifiant de compte dans la requête (`test_withdraw`).
**Blocage volontaire :** 1/7/30 jours, non raccourcissable (`test_self_block`).
**Journal :** la chaîne de hachage détecte des altérations simples, ce n'est **pas** une preuve juridique infaillible.
**Limites connues :** limitation de débit en mémoire (un seul processus), pas de HTTPS ni de 2FA (recommandés), l'IP proxy n'est pas lue.

## Données personnelles (important)
La base SQLite contient e-mails, noms, hachages de mots de passe, historiques et journaux. **Elle ne doit jamais être publiée.** Par défaut elle est créée **hors du dépôt** (`~/.toutbet/`, dossier 700, fichier 600) et `.gitignore` exclut `*.db`. Les mots de passe sont hachés (scrypt) et les jetons de session stockés hachés, mais les e-mails et historiques restent lisibles : en cas de fuite du fichier, ce sont des données personnelles exposées (RGPD). Ne mettez jamais de vraies données dans un dépôt public.

## Profil
`PATCH /api/me` (pseudo, nom : liste blanche), `POST /api/me/email` et `POST /api/me/password` (mot de passe actuel exigé, limités en débit, journalisés ; le changement de mot de passe déconnecte les autres appareils).

## Vérifications manuelles
**Parcours normal :** créer un compte (100 € fictifs) → se connecter → ouvrir un pari → participer (confirmation) → consulter notifications → Mon espace (historique, stats, retrait fictif) → Profil (blocage) → Bookie : créer, clôturer, proposer le résultat, régler.
**Scénarios malveillants :** 6 mauvais mots de passe (429) ; appeler `/api/admin/users` en Parieur (403) ; modifier un en-tête/rôle dans la requête (ignoré) ; participer/annuler après clôture (409) ; retrait > solde ou rejoué avec la même clé ; `POST /api/notifications` (404) ; requête sans `X-CSRF-Token` (403) ; titre de pari contenant `<script>` (affiché en texte).
