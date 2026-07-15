# Τελική Εργασία — Terminal Management System (TMS)
## Mellon Group DevOps Bootcamp — Εκφώνηση


## Γενικό Πλαίσιο

Η εταιρία σας διαχειρίζεται ένα fleet από POS terminals (τερματικά πληρωμών).
Κάθε terminal ανήκει σε έναν merchant (κατάστημα) και έχει στοιχεία όπως
hardware model, software version, και πότε επικοινώνησε τελευταία φορά με
τον server.

Θα φτιάξετε **ένα Flask API** που:
1. Συνδέεται με μια βάση δεδομένων **MySQL**.
2. Χρησιμοποιεί **Redis** ως cache layer, ώστε τα ακριβά queries να μην
   χτυπάνε τη βάση σε κάθε request.
3. Τρέχει ολόκληρο μέσα σε **Docker** (API + βάση + cache — 3 containers που
   μιλάνε μεταξύ τους μέσω `docker compose`).

Σχεδιασμένο για **5 μέρες**, βήμα-βήμα.

---

## Παραδοτέα

1. **Git repository** με τον κώδικα.
2. **`docker-compose.yml`** — σηκώνει ολόκληρο το σύστημα (API + βάση + Redis)
   με ένα `docker compose up`, **3 services**: `tms-api`, `mysql`, `redis`.
3. **`.env.example`** — template χωρίς πραγματικά credentials.
4. **`README.md`** με:
   - Οδηγίες εκκίνησης
   - Λίστα endpoints με σύντομη περιγραφή του καθενός

---

## Μέρος 0 — Προαπαιτούμενα

| Εργαλείο         | Γιατί το χρειάζεστε                                  |
|------------------|-------------------------------------------------------|
| Docker Desktop   | Για να τρέχουν όλα τα containers                      |
| Python 3.11+     | Προαιρετικό, για local testing (το app τρέχει μέσα σε Docker) |
| Git              | Version control                                        |
| VS Code ή PyCharm| Επεξεργασία κώδικα                                     |


---

## Μέρος 1 — Docker & Βάση Δεδομένων

### Θα σας δοθούν

- `db/init/01_schema.sql` — τα `CREATE TABLE` του schema.
- `db/init/02_seed.sql` — δείγμα δεδομένων.

Αυτά τα δύο αρχεία τρέχουν **αυτόματα** την πρώτη φορά που ξεκινάει το MySQL
container (αν τα mountάρετε σωστά μέσα στο container — ψάξτε πώς δουλεύει το
`docker-entrypoint-initdb.d` στο official MySQL image). Δεν χρειάζεται καμία
χειροκίνητη διαδικασία restore.

### Τι πρέπει να χτίσετε εσείς

**`docker-compose.yml`** με 3 services:

| Service     | Απαιτήσεις                                                                 |
|-------------|-------------------------------------------------------------------------------|
| `mysql`     | Official MySQL image. Credentials/database name μέσω environment variables (όχι hardcoded). Volume ώστε τα δεδομένα να επιβιώνουν σε restart. Volume που να mountάρει το `db/init/` ώστε να τρέξει το auto-seed. Healthcheck. |
| `redis`     | Official Redis image. Healthcheck.                                             |
| `tms-api`   | Χτισμένο από δικό σας Dockerfile. Περιμένει (`depends_on` με health condition) και τα δύο άλλα services πριν ξεκινήσει. |

**`app/Dockerfile`**: Python 3.12 base image, εγκατάσταση dependencies από
`requirements.txt`, τρέχει το `main.py` σαν entrypoint.

**`app/requirements.txt`**: ό,τι χρειάζεται το Flask app (web framework, ORM,
MySQL driver, data processing, env var loading, Redis client).

**`.env.example`**: template με ονόματα μεταβλητών για: MySQL root
password, database name, application user/password, host/port για το app να
συνδεθεί, και αντίστοιχα για Redis. Μην ανεβάσετε ποτέ το πραγματικό `.env`
στο git.

### Εξερεύνηση του Schema (ΣΗΜΑΝΤΙΚΟ — πριν γράψετε κώδικα)

Τρέξτε πρώτα αυτό μέσα στη βάση για να δείτε τις στήλες ενός πίνακα:

```sql
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'terminals'
ORDER BY ORDINAL_POSITION;
```

**Τρεις πίνακες:**

| Πίνακας     | Τι είναι                                                          |
|-------------|---------------------------------------------------------------------|
| `terminals` | Πραγματικά, ενεργά terminals                                        |
| `merchants` | Καταστήματα (ένα terminal ανήκει σε ένα merchant)                   |
| `templates` | Πρότυπα από τα οποία μπορείτε να φτιάξετε νέα terminals (Feature B)  |

**ΠΡΟΣΟΧΗ: Το `mid` είναι στήλη του `terminals`? Τί ρόλο παίζει αυτό;**

> Ένα πεδίο ΔΕΝ υπάρχει ακόμα στο schema και πρέπει να το προσθέσετε **εσείς**
> μέσα από τον κώδικά σας: `updated_on` στο `terminals` (βλ. Feature A4).

---

## Μέρος 2 — Feature A: Terminals

### A1. Λίστα όλων των terminals
```
GET /terminals
GET /terminals?enabled=true
GET /terminals?enabled=false
```
Επιστρέφει JSON array. Κάθε αντικείμενο περιέχει:
`tid`, `mid`, `hardware_model`, `software_version`, `enabled`, `last_call`.

```json
[
  {
    "tid": "T0101001",
    "mid": "MID000101",
    "hardware_model": "Desk2600",
    "software_version": "12.4.0",
    "enabled": true,
    "last_call": "2026-06-23T12:35:56"
  }
]
```

### A2. Λεπτομέρειες ενός terminal
```
GET /terminals/<tid>
```
Επιστρέφει όλα τα σχετικά πεδία ενός terminal. Αν το TID δεν υπάρχει:
`404 Not Found`.

### A3. Terminals που χρειάζονται upgrade (flagged)
```
GET /terminals/flagged
```
Επιστρέφει terminals όπου το `scenario_number` **δεν** είναι `NULL`, κενό
string, ή `'0'`.

### A4. Flag / Unflag terminal
```
POST /terminals/<tid>/flag
Body: { "scenario_number": "5" }

POST /terminals/<tid>/unflag
```

Πριν γράψετε αυτό το endpoint, πρέπει να προσθέσετε στο `terminals` τη
στήλη `updated_on` — δεν υπάρχει στο seed schema. Πρέπει να το κάνετε **με
ασφαλή/idempotent τρόπο** (να μη σκάει αν το app ξεκινήσει ξανά και η
στήλη υπάρχει ήδη).

> ⚠️ Προσοχή: η MySQL **δεν** υποστηρίζει `ADD COLUMN IF NOT EXISTS` (αυτό
> είναι feature της MariaDB) — θα χρειαστεί να ελέγξετε πρώτα αν η στήλη
> υπάρχει με άλλον τρόπο πριν κάνετε το `ALTER TABLE`.

Το `/flag` θέτει το `scenario_number` στην τιμή από το body (ως string) και
το `updated_on` στην τρέχουσα ώρα. Το `/unflag` θέτει `scenario_number = '0'`.

**Απαιτήσεις:**
- Αν το TID δεν υπάρχει: `404`.
- Αν λείπει το `scenario_number` από το body: `400 Bad Request`.
- `logger.info()` για κάθε αλλαγή (ποιο TID, από ποια τιμή, σε ποια τιμή).
- Μετά από κάθε write, καθαρίστε το cache (βλ. Feature C).

### A5. Decommission Terminal
```
POST /terminals/<tid>/decommission
```
1. Ελέγχει ότι το terminal υπάρχει και είναι `enabled = 1`. Αν είναι ήδη
   decommissioned: `409 Conflict`.
2. Θέτει `enabled = 0`.
3. Καταχωρεί τη σήμανση σε νέο πίνακα `decommission_queue` (τον φτιάχνετε
   εσείς) με στήλες: `tid` (primary key, foreign key προς `terminals.tid`),
   `queued_on`, `delete_after` (= `queued_on` + 3 μέρες).

**Βοηθητικό endpoint:**
```
GET /terminals/decommissioned
```
Επιστρέφει τα terminals στην ουρά διαγραφής, με πόσες μέρες απομένουν.

> Το αυτόματο καθάρισμα μετά τις 3 μέρες (cron job) είναι **Bonus feature**
> — δείτε το τέλος του εγγράφου.

---

## Μέρος 3 — Feature B: Templates

### B1. Λίστα templates
```
GET /templates
```

### B2. Λεπτομέρειες template
```
GET /templates/<id>
```
`404` αν δεν υπάρχει.

### B3. Δημιουργία terminal από template
```
POST /terminals/from-template
Body: { "template_id": 1, "mid": "MID000101" }
```
1. Ελέγχει ότι το template υπάρχει (`404` αν όχι).
2. Ελέγχει ότι το MID υπάρχει στον πίνακα `merchants` (`404` αν όχι).
3. Δημιουργεί ένα νέο, μοναδικό `tid`: βρείτε το TID με το μεγαλύτερο
   αριθμητικό suffix για τον ίδιο merchant (π.χ. αν υπάρχουν
   `T0101001`..`T0101004`, το πρόθεμα είναι `T0101` και ο επόμενος αριθμός
   είναι `005` → νέο TID: `T0101005`).
4. Δημιουργεί νέα γραμμή στο `terminals`, αντιγράφοντας από το template τα
   `hardware_model`/`hardware_family`, με `merchant_id` και `template_id`
   σωστά συνδεδεμένα.
5. Επιστρέφει `201 Created` με το νέο TID.

Όλα τα βήματα 3-4-5 πρέπει να τρέξουν **μέσα σε μία transaction** — αν
οτιδήποτε αποτύχει, δεν πρέπει να μείνει το operation της βάσης στη μέση.

---

## Μέρος 4 — Feature C: Redis Caching

**Απαιτήσεις:**

1. **Cache-aside pattern** στα read-heavy endpoints:
   - `GET /terminals` (TTL 30 δευτερόλεπτα)
   - `GET /statistics/*` (TTL 60 δευτερόλεπτα — βλ. Feature D)
2. **Invalidation**: Σε **κάθε** write endpoint (`/flag`, `/unflag`,
   `/decommission`, `/terminals/from-template`), καθαρίστε ολόκληρο το
   cache πριν επιστρέψετε το response. Έτσι το επόμενο `GET` θα ξαναδιαβάσει
   φρέσκα δεδομένα από τη βάση.
3. Αν το Redis είναι εκτός λειτουργίας, το API **δεν πρέπει να κρασάρει** —
   απλά να μη χρησιμοποιεί cache.
4. `logger.info()` σε κάθε cache HIT/MISS.

**Πώς θα το επιβεβαιώσετε ότι δουλεύει:** κάντε δύο `GET /terminals`
συνεχόμενα (η δεύτερη πρέπει να είναι HIT στα logs), μετά ένα write, μετά
ξανά `GET /terminals` (πρέπει να ξαναδείτε MISS).

---

## Μέρος 5 — Feature D: Στατιστικά με Pandas

Τέσσερα endpoints που επιστρέφουν JSON με aggregated δεδομένα,
χρησιμοποιώντας Pandas, **και cache** (TTL 60s, ίδιο pattern με το Feature C).

### D1. Κατανομή ανά τύπο hardware
```
GET /statistics/by-hardware
```
```json
{
  "generated_at": "2026-07-01T10:00:00",
  "data": [
    {"hardware_model": "Desk2600", "count": 12},
    {"hardware_model": "iwl220", "count": 34}
  ]
}
```

### D2. Ενεργά vs Ανενεργά
```
GET /statistics/by-state
```
```json
{
  "generated_at": "2026-07-01T10:00:00",
  "active": 57,
  "inactive": 10,
  "total": 67
}
```

### D3. Κατανομή ανά οικογένεια hardware
```
GET /statistics/by-hardware-family
```
Ίδιο σχήμα με το D1, αλλά ομαδοποιημένο ανά `hardware_family`.

### D4. Κατανομή ανά ημέρες αδράνειας
```
GET /statistics/idle-distribution
```
Υπολογίστε πόσες μέρες πέρασαν από το `last_call_stamp` κάθε terminal μέχρι
σήμερα, και ομαδοποιήστε σε buckets:
`Σήμερα`, `1-7 μέρες`, `8-30 μέρες`, `31-90 μέρες`, `90+ μέρες`.
```json
{
  "generated_at": "2026-07-01T10:00:00",
  "data": [
    {"range": "1-7 μέρες", "count": 15},
    {"range": "8-30 μέρες", "count": 18}
  ]
}
```

---

## Τεχνικές Απαιτήσεις (ισχύουν σε όλα τα Features)

1. **Logging**: όλα τα logs στο **stdout** (όχι σε αρχεία), με timestamp,
   log level, και μήνυμα.
2. **Error Handling**: `try/except` σε κάθε database ή Redis operation.
   Ποτέ silent failures — κάθε exception πρέπει να γίνεται `logger.error()`
   και να επιστρέφει `500` με `{"error": "database error"}` (ή ανάλογο).
3. **Parameterized Queries**: **Ποτέ** string concatenation/f-string μέσα σε
   SQL με user input — πάντα bind parameters.
4. **Secrets σε `.env`**: ποτέ credentials hardcoded στον κώδικα.
5. **Health Check Endpoint** (`GET /health`): πρέπει να ελέγχει **και** τη
   βάση **και** το Redis ξεχωριστά, και να επιστρέφει `200` αν όλα είναι ok
   ή `503` αν κάτι είναι degraded, με λεπτομέρεια ανά component.

---

## Αξιολόγηση

| Κριτήριο                                         | Βαρύτητα |
|---------------------------------------------------|----------|
| Feature A (terminals, flag, decommission)          | 30%      |
| Feature B (templates + create-from-template)       | 20%      |
| Feature C (Redis caching — hit/miss + invalidation)| 20%      |
| Feature D (statistics με Pandas)                   | 15%      |
| Docker (Compose με 3 services λειτουργούν σωστά)   | 15%      |

**Bonus (+5% έκαστο):**
- Αυτόματο cron script που καθαρίζει το `decommission_queue` κάθε βράδυ
  μέσα σε ξεχωριστό container (βλ. παρακάτω)
- Daily CSV report (endpoint που παράγει `terminals_basic.csv`)
- Unit tests (pytest) για τουλάχιστον 3 functions
- `/health` endpoint σε κάθε service

---


## Bonus (Προαιρετικό) — Cron Script Decommission Cleanup

Φτιάξτε ένα **ξεχωριστό container** που τρέχει κάθε βράδυ και διαγράφει
terminals με `delete_after < NOW()` από τον πίνακα `decommission_queue`
(και το αντίστοιχο terminal από το `terminals`).

> ⚠️ Προσοχή — πιθανό εμπόδιο: το `decommission_queue.tid` έχει
> `FOREIGN KEY REFERENCES terminals(tid)`. Σκεφτείτε με ποια **σειρά**
> πρέπει να γίνουν τα δύο `DELETE` ώστε να μη σκάσει η βάση με foreign key
> constraint error.



# Οδηγίες παράδοσης.
θα φτιάξετε ένα github repository. 

Μέσα στο Readme θα μου γράψετε ότι θέλετε να γνωρίζω για το project σας.

Οταν το ολοκληρώσετε, θα με κάνετε contributor για να μπορώ να το δώ, με το mail **saragasmixalis@gmail.com**