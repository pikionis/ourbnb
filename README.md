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

## Πώς δουλεύουμε
1. Νέο session Claude Code → `/phase 0`
2. Διάβασε το πλάνο, ρώτα, έγκρινε.
3. Στο τέλος: `make check` πράσινο → πες «τρέξε τον architecture-reviewer» → commit.
4. Νέο session για την επόμενη φάση. **Μία φάση ανά session.**
5. Αλλάζει κάτι στην επιχείρηση; `/domain-change ...` — ποτέ κατευθείαν στον κώδικα.

Αντιστοιχία με το βιβλίο: Phase 1 → κεφ. 2, 6, 8, 13 · Phase 4 → κεφ. 1, 7 · Phase 5 → κεφ. 4, 9.
