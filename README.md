# Property Management — Kos (KosPM)

Πλατφόρμα διαχείρισης ακινήτων βραχυχρόνιας μίσθωσης: κρατήσεις από iCal, πρόγραμμα καθαρισμών,
WhatsApp, λινά, επισκέπτες, εκκαθαρίσεις ιδιοκτητών, δηλώσεις ΑΑΔΕ.

## Έγγραφα
| Αρχείο | Τι είναι |
|---|---|
| `CLAUDE.md` | Κανόνες για το Claude Code (αρχιτεκτονική, TDD, πότε ρωτάει) |
| `docs/DOMAIN.md` | Business logic — η μία αλήθεια |
| `docs/BUILD_PLAN.md` | Φάσεις v1 / v2 / v3 με checkboxes |
| `docs/adr/` | Αρχιτεκτονικές αποφάσεις (γράφονται στη Phase 0) |
| `docs/design/` | Design briefs για τις σελίδες χρηστών (π.χ. onboarding ιδιοκτητών) |

## Εργαλεία Claude Code (`.claude/`)
| | Χρήση |
|---|---|
| `/phase 0` | Ξεκινά ή συνεχίζει μια φάση: πλάνο → έγκριση → TDD → `make check` |
| `/explain <κάτι>` | Εξήγηση στα ελληνικά με βάση DDD / Cosmic Python, χωρίς αλλαγές |
| `/domain-change <κανόνας>` | Αλλαγή κανόνα: πρώτα DOMAIN.md, μετά tests, μετά κώδικας |
| agent `architecture-reviewer` | Ανεξάρτητος έλεγχος στο τέλος κάθε φάσης |
| skill `ddd-hexagonal` | Οδηγός για το πού μπαίνει κάθε κομμάτι κώδικα |
| `settings.json` | Ξεκινά σε **plan mode**, απαγορεύει ανάγνωση `.env` και `git push` |

## Πριν ξεκινήσεις (μία φορά)
1. Εγκατάσταση: Docker Desktop, Python 3.12, `uv`, VS Code με το Claude Code extension.
2. `git init` έχει ήδη γίνει. Προαιρετικά: private repo στο GitHub και `git remote add origin ...`.
3. Άνοιξε **αυτόν τον φάκελο** στο VS Code (File → Open Folder).

## Τοπική εγκατάσταση (Windows, χωρίς Docker)
Για υπολογιστή με Windows, Python 3.12, Git και PostgreSQL 18 εγκατεστημένο ως υπηρεσία
(θύρα 5432). Όλες οι εντολές `make` τρέχουν από τη ρίζα του repo, δηλαδή εκεί που είναι το `Makefile`.

1. **Εργαλεία** (μία φορά):
   ```
   pip install uv
   winget install ezwinports.make
   ```
   Μετά **άνοιξε νέο terminal** για να ανανεωθεί το PATH, και έλεγξε με `uv --version` και
   `make --version`. Αν το `make` δεν βρεθεί ούτε στο νέο terminal, πρόσθεσε στο PATH τον φάκελο
   `bin` του πακέτου, κάτω από το `%LOCALAPPDATA%\Microsoft\WinGet\Packages\ezwinports.make_...\`.
2. **Βάση δεδομένων** (μία φορά). Άνοιξε το psql ως `postgres`. Από cmd:
   ```
   "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres
   ```
   Από PowerShell βάλε `&` μπροστά: `& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres`.
   Μετά τρέξε:
   ```sql
   CREATE ROLE kospm LOGIN CREATEDB PASSWORD '...';
   CREATE DATABASE kospm OWNER kospm ENCODING 'UTF8' TEMPLATE template0;
   ```
   Στη θέση του `...` βάλε δικό σου κωδικό, μόνο με γράμματα, ψηφία, `-` και `_`, γιατί μπαίνει
   αυτούσιος στο `DATABASE_URL`. Το `CREATEDB` χρειάζεται για να δημιουργούν τα tests τη βάση
   `test_kospm`.
3. **`.env`**: αντέγραψε το `.env.example` σε `.env` **στη ρίζα του repo**. Από PowerShell:
   `Copy-Item .env.example .env`, από cmd: `copy .env.example .env`. Συμπλήρωσε τα
   `DJANGO_SECRET_KEY`, `DATABASE_URL` και `FERNET_KEYS` με τις εντολές που δίνει το ίδιο το αρχείο,
   και αποθήκευσέ το ως UTF-8. Το `.env` **δεν μπαίνει ποτέ** στο git.
4. **Εγκατάσταση και εκκίνηση**:
   ```
   make install      # uv sync: φτιάχνει το backend/.venv
   make migrate      # δημιουργεί τους πίνακες στη βάση kospm
   make superuser    # δημιουργεί λογαριασμό admin
   make run          # http://localhost:8000/admin/
   make check        # ό,τι τρέχει και το CI· πρέπει να βγει πράσινο
   ```

Με Docker (προαιρετικά): το `make up` ξεκινά Postgres 16 στη θύρα **5433**, γιατί την 5432 την
πιάνει η υπηρεσία των Windows. Σε αυτή την περίπτωση το `DATABASE_URL` δείχνει στο `localhost:5433`.

### Εντολές `make`
| Εντολή | Τι κάνει |
|---|---|
| `make install` | Εγκαθιστά τις εξαρτήσεις στο `backend/.venv` (`uv sync`) |
| `make up` / `make down` | Ξεκινά / σταματά το docker compose (Postgres στη θύρα 5433, backend) |
| `make run` | Ξεκινά τον Django dev server στο http://localhost:8000 |
| `make test` | Τρέχει τα γρήγορα unit tests, χωρίς βάση |
| `make test-all` | Τρέχει όλα τα tests, μαζί με τα integration / e2e σε PostgreSQL |
| `make lint` | Ελέγχει κώδικα και μορφοποίηση με ruff |
| `make fmt` | Διορθώνει αυτόματα ό,τι μπορεί το ruff (π.χ. σειρά imports) και μορφοποιεί τον κώδικα |
| `make typecheck` | Ελέγχει τους τύπους με mypy (strict) |
| `make lint-imports` | Ελέγχει τους κανόνες εξαρτήσεων μεταξύ layers και contexts (import-linter) |
| `make migrations-check` | Αποτυγχάνει αν λείπει κάποιο migration |
| `make check` | lint + typecheck + lint-imports + migrations-check + test-all, ό,τι τρέχει και το CI |
| `make migrate` / `make makemigrations` | Εφαρμόζει / δημιουργεί migrations |
| `make superuser` | Δημιουργεί χρήστη admin |
| `make run-jobs` | Τρέχει μία φορά τις προγραμματισμένες εργασίες (iCal sync, plan tomorrow, outbox), όσες υπάρχουν στην τρέχουσα φάση |

## Πώς δουλεύουμε
1. Νέο session Claude Code → `/phase 0`
2. Διάβασε το πλάνο, ρώτα, έγκρινε.
3. Στο τέλος: `make check` πράσινο → πες «τρέξε τον architecture-reviewer» → commit.
4. Νέο session για την επόμενη φάση. **Μία φάση ανά session.**
5. Αλλάζει κάτι στην επιχείρηση; `/domain-change ...` — ποτέ κατευθείαν στον κώδικα.

Αντιστοιχία με το βιβλίο: Phase 1 → κεφ. 2, 6, 8, 13 · Phase 4 → κεφ. 1, 7 · Phase 5 → κεφ. 4, 9.
