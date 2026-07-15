# Terminal Management System (TMS)

## 1. Σκοπός της εργασίας

Στην εργασία αυτή δημιούργησα ένα **Terminal Management System**. Πρόκειται για ένα API που διαχειρίζεται POS terminals: μπορεί να εμφανίζει τα στοιχεία τους, να τα σημειώνει για αναβάθμιση, να τα απενεργοποιεί και να δημιουργεί νέα terminals από έτοιμα templates.

Η εφαρμογή δεν είναι ένα απλό πρόγραμμα που τρέχει στον υπολογιστή. Χρησιμοποιεί τρία συνεργαζόμενα containers Docker:

1. **tms-api**: το Flask πρόγραμμα που δέχεται τα HTTP requests.
2. **mysql**: η βάση δεδομένων, όπου αποθηκεύονται merchants, templates και terminals.
3. **redis**: μια γρήγορη προσωρινή μνήμη (cache), ώστε συχνά requests να μη διαβάζουν συνεχώς τη βάση.

## 2. Τεχνολογίες που χρησιμοποίησα

- **Python / Flask**: για να υλοποιήσω το REST API.
- **MySQL**: για τη μόνιμη αποθήκευση των δεδομένων.
- **SQLAlchemy και PyMySQL**: για ασφαλή σύνδεση και παραμετροποιημένα SQL queries προς τη MySQL.
- **Redis**: για caching των λιστών terminals και των στατιστικών.
- **Pandas**: για τους υπολογισμούς και την ομαδοποίηση στατιστικών δεδομένων.
- **Docker Compose**: για να ξεκινούν και οι τρεις υπηρεσίες με μία εντολή.

## 3. Δομή φακέλων

```text
Final_assignment/
│  docker-compose.yml      # Συνδέει τα 3 Docker services
│  .env.example            # Παράδειγμα μεταβλητών περιβάλλοντος
│  .gitignore              # Αποτρέπει την αποθήκευση του .env στο Git
│  README.md                # Η παρούσα τεκμηρίωση
│
├─ app/
│  │  main.py              # Ο κώδικας του Flask API
│  │  Dockerfile           # Οδηγίες δημιουργίας του API image
│  │  requirements.txt     # Python βιβλιοθήκες που χρειάζεται το API
│
└─ init/
   │  01_schema.sql        # Δημιουργία των αρχικών πινάκων
   │  02_seed.sql          # Δοκιμαστικά δεδομένα
```

## 4. Πώς ξεκινά η εφαρμογή, βήμα-βήμα

1. Εγκαθιστώ και ανοίγω το Docker Desktop.
2. Ανοίγω τον φάκελο `Final_assignment` στο VS Code.
3. Αντιγράφω το `.env.example` και ονομάζω το αντίγραφό του `.env`.
4. Στο `.env` επιλέγω τοπικούς κωδικούς για τη MySQL. Το αρχείο αυτό δεν το ανεβάζω στο Git, γιατί περιέχει μυστικά.
5. Στο ενσωματωμένο terminal του VS Code εκτελώ:

```bash
docker compose up --build
```

6. Το Docker δημιουργεί τα images, ξεκινά πρώτα MySQL και Redis και μετά το Flask API. Η MySQL εκτελεί αυτόματα τα αρχεία του φακέλου `init/` μόνο την πρώτη φορά που δημιουργείται ο δίσκος δεδομένων της.
7. Ανοίγω στο browser τη διεύθυνση `http://localhost:5000/health`. Αν όλα λειτουργούν, λαμβάνω απάντηση με `database: ok` και `redis: ok`.

Για να σταματήσω την εφαρμογή, πατάω `Ctrl+C` στο terminal και έπειτα εκτελώ:

```bash
docker compose down
```

Αν θέλω να διαγράψω και τα δεδομένα της βάσης και να γίνει ξανά seed από την αρχή, εκτελώ:

```bash
docker compose down -v
docker compose up --build
```

## 5. Βάση δεδομένων και πρόσθετοι πίνακες

Τα αρχεία που δόθηκαν στην εκφώνηση δημιουργούν τους πίνακες `merchants`, `templates` και `terminals`.

- Κάθε **merchant** είναι ένα κατάστημα και έχει μοναδικό `mid`.
- Κάθε **terminal** ανήκει σε έναν merchant μέσω του `merchant_id`.
- Τα **templates** περιγράφουν ένα πρότυπο hardware, από το οποίο μπορώ να δημιουργήσω νέο terminal.

Κατά την εκκίνηση του API, ο κώδικας ελέγχει αν υπάρχει η στήλη `updated_on` στον πίνακα `terminals`. Αν δεν υπάρχει, την προσθέτει. Ο έλεγχος αυτός κάνει τη διαδικασία ασφαλή σε επανεκκίνηση της εφαρμογής.

Δημιουργείται επίσης ο πίνακας `decommission_queue`. Όταν ένα terminal αποσύρεται, παραμένει στη βάση αλλά καταγράφεται σε αυτόν τον πίνακα με ημερομηνία διαγραφής τρεις ημέρες αργότερα.

## 6. Cache με Redis

Το cache λειτουργεί με το μοτίβο **cache-aside**:

1. Όταν ζητείται η λίστα terminals ή ένα στατιστικό, το API ελέγχει πρώτα το Redis.
2. Αν υπάρχει αποθηκευμένη απάντηση, επιστρέφεται αμέσως (*cache HIT*).
3. Αν δεν υπάρχει, το API διαβάζει από MySQL, επιστρέφει το αποτέλεσμα και το αποθηκεύει στο Redis (*cache MISS*).
4. Κάθε αλλαγή δεδομένων (flag, unflag, decommission ή δημιουργία terminal) καθαρίζει το cache, ώστε το επόμενο request να διαβάσει φρέσκα δεδομένα.

Η λίστα terminals έχει διάρκεια cache 30 δευτερόλεπτα και τα στατιστικά 60 δευτερόλεπτα. Αν το Redis δεν είναι διαθέσιμο, το API συνεχίζει να λειτουργεί απευθείας με τη MySQL και καταγράφει το πρόβλημα στα logs.

## 7. Endpoints

| Method | Path | Τι κάνει |
|---|---|---|
| GET | `/health` | Ελέγχει ξεχωριστά MySQL και Redis. Επιστρέφει `200` ή `503`. |
| GET | `/terminals` | Εμφανίζει όλα τα terminals. |
| GET | `/terminals?enabled=true` | Εμφανίζει μόνο ενεργά terminals. |
| GET | `/terminals?enabled=false` | Εμφανίζει μόνο ανενεργά terminals. |
| GET | `/terminals/<tid>` | Εμφανίζει όλα τα στοιχεία ενός terminal. |
| GET | `/terminals/flagged` | Εμφανίζει terminals με `scenario_number` διαφορετικό από `0`. |
| POST | `/terminals/<tid>/flag` | Ορίζει `scenario_number` και ενημερώνει `updated_on`. |
| POST | `/terminals/<tid>/unflag` | Επαναφέρει το `scenario_number` σε `"0"`. |
| POST | `/terminals/<tid>/decommission` | Απενεργοποιεί terminal και το βάζει στην ουρά διαγραφής. |
| GET | `/terminals/decommissioned` | Εμφανίζει την ουρά διαγραφής και τις ημέρες που απομένουν. |
| GET | `/templates` | Εμφανίζει όλα τα templates. |
| GET | `/templates/<id>` | Εμφανίζει τα στοιχεία ενός template. |
| POST | `/terminals/from-template` | Δημιουργεί νέο terminal από template για έναν merchant. |
| GET | `/statistics/by-hardware` | Εμφανίζει πλήθος terminals ανά hardware model. |
| GET | `/statistics/by-hardware-family` | Εμφανίζει πλήθος terminals ανά hardware family. |
| GET | `/statistics/by-state` | Εμφανίζει ενεργά, ανενεργά και σύνολο terminals. |
| GET | `/statistics/idle-distribution` | Ομαδοποιεί terminals ανά ημέρες από το τελευταίο call. |

## 8. Παραδείγματα δοκιμών

Μπορώ να χρησιμοποιήσω Postman, Insomnia ή το terminal. Παρακάτω φαίνονται ενδεικτικά requests με `curl`.

```bash
# Έλεγχος ότι λειτουργούν όλα τα services
curl http://localhost:5000/health

# Λίστα ενεργών terminals
curl "http://localhost:5000/terminals?enabled=true"

# Σημείωση ενός terminal για scenario 5
curl -X POST http://localhost:5000/terminals/T0101001/flag \
  -H "Content-Type: application/json" \
  -d '{"scenario_number":"5"}'

# Δημιουργία νέου terminal από template
curl -X POST http://localhost:5000/terminals/from-template \
  -H "Content-Type: application/json" \
  -d '{"template_id":1,"mid":"MID000101"}'
```

## 9. Χειρισμός σφαλμάτων και ασφάλεια

- Τα SQL queries χρησιμοποιούν bind parameters και όχι ένωση κειμένου με δεδομένα του χρήστη. Έτσι μειώνεται ο κίνδυνος SQL injection.
- Αν ένα TID ή template δεν υπάρχει, επιστρέφεται `404 Not Found`.
- Αν ένα terminal είναι ήδη απενεργοποιημένο και ζητηθεί ξανά decommission, επιστρέφεται `409 Conflict`.
- Αν λείπουν υποχρεωτικά πεδία από JSON body, επιστρέφεται `400 Bad Request`.
- Σε σφάλμα βάσης, το API γράφει το σφάλμα στα logs και επιστρέφει `500`.
- Τα credentials διαβάζονται από το `.env` και δεν γράφονται στον κώδικα.

## 10. Συμπέρασμα

Με αυτή την εφαρμογή υλοποιείται ένα μικρό αλλά ολοκληρωμένο σύστημα διαχείρισης POS terminals. Η χρήση Docker επιτρέπει να εκκινεί όλο το περιβάλλον με μία εντολή, η MySQL διατηρεί τα δεδομένα, το Redis επιταχύνει συχνές αναγνώσεις και το Pandas παρέχει συγκεντρωτικά στατιστικά.
