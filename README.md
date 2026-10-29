# ourbnb.gr

Η βιτρίνα του OurBnb: διαχείριση Airbnb, Booking.com και Expedia στην Κω.

Είναι στατικό site, χωρίς build και χωρίς βάση δεδομένων. Ανεβαίνει όπως είναι σε οποιοδήποτε hosting με PHP (για τη φόρμα).

## Τι έχει μέσα

| Αρχείο | Τι κάνει |
|---|---|
| `index.html` | Η αρχική, με όλες τις ενότητες του design |
| `aporrito.html` | Πολιτική απορρήτου (προσχέδιο) |
| `404.html` | Σελίδα «δεν βρέθηκε» |
| `api/lead.php` | Η φόρμα «Πόσα μπορεί να βγάλει το σπίτι σου;». Στέλνει email |
| `assets/css/styles.css` | Όλο το στυλ. Χρώματα και γραμματοσειρές στο `:root` |
| `assets/js/main.js` | Μενού στο κινητό, αποστολή φόρμας |
| `assets/fonts/` | Geologica και Noto Serif Display, τοπικά (όχι από Google Fonts) |
| `assets/img/` | Logo, εικονίδια, `og-image.jpg` για social/WhatsApp |
| `.htaccess` | HTTPS, www → χωρίς www, cache, headers ασφαλείας |

## Ανέβασμα στο Hostinger (μία φορά)

1. **Domain.** Στο hPanel πρόσθεσε το `ourbnb.gr` (Websites → Add website). Αν το domain είναι σε άλλον registrar, βάλε εκεί τους nameservers που σου δείχνει το Hostinger.
2. **Άδειασε το `public_html`.** Σβήσε το `default.php` που βάζει το Hostinger.
3. **Git.** Πήγαινε hPanel → Advanced → Git και συμπλήρωσε:
   - Repository: `git@github.com:pikionis/ourbnb.git`
   - Branch: `main`
   - Directory: κενό (έτσι μπαίνει στο `public_html`)

   Επειδή το repo είναι ιδιωτικό, αντέγραψε το SSH key που δείχνει εκεί το hPanel. Πρόσθεσέ το στο GitHub: repo → Settings → Deploy keys → Add deploy key, χωρίς write access. Μετά πάτα Create και Deploy.
4. **Αυτόματο ανέβασμα.** Στο ίδιο σημείο του hPanel ενεργοποίησε το Auto Deployment και αντέγραψε το Webhook URL. Στο GitHub: repo → Settings → Webhooks → Add webhook, και βάλε αυτό το URL στο Payload URL. Από εκεί και πέρα, κάθε push στο `main` ανεβαίνει μόνο του.
5. **SSL.** hPanel → Security → SSL: εγκατάστησε το δωρεάν SSL για `ourbnb.gr` και `www.ourbnb.gr`.
6. **Email της φόρμας.** Φτιάξε το mailbox `no-reply@ourbnb.gr` στο hPanel → Emails. Η φόρμα το χρησιμοποιεί ως αποστολέα. Τα αιτήματα πάνε στο `petrospikionis@gmail.com`. Και τα δύο αλλάζουν στην αρχή του `api/lead.php`.
7. **Δοκιμή.** Στείλε μια φόρμα από το κινητό σου. Την πρώτη φορά κοίτα και στα Spam του Gmail.

Αν δεν θέλεις Git: GitHub → Code → Download ZIP, και ανέβασε τα αρχεία στο `public_html` από το File Manager.

Ο φάκελος `.git` που αφήνει το Git deploy μέσα στο `public_html` είναι κλειδωμένος από το `.htaccess`.

## Πριν το ανακοινώσεις

- [ ] Επωνυμία ΙΚΕ, ΑΦΜ και ΓΕΜΗ στο footer (`index.html`, σημείο `TODO`) και στο `aporrito.html`
- [ ] Να δει την πολιτική απορρήτου λογιστής ή δικηγόρος. Συμπλήρωσε και το διάστημα διατήρησης δεδομένων ([12 μήνες])
- [ ] Φωτογραφίες για την ενότητα «Από την Κω»: εσύ με την ομάδα και τα Arangia
- [ ] Μια πραγματική κριτική επισκέπτη από Booking.com ή Airbnb
- [ ] Google Search Console (με το `sitemap.xml`) και Google Business Profile

## Αλλαγές

- Τα κείμενα είναι όλα στο `index.html`.
- Χρώματα και γραμματοσειρές είναι στο `assets/css/styles.css`, στην ενότητα `:root`.
- Τοπικά: `php -S localhost:8000` μέσα στον φάκελο, και άνοιξε `http://localhost:8000`.
- Όταν αλλάζεις CSS ή JS, ανέβασε το `?v=1` σε `?v=2` στα `<link>` και `<script>`, ώστε να μη μένει η παλιά έκδοση στην cache.

## Επόμενα

- Αγγλική έκδοση (EN)
- Διαμονές και σελίδα σπιτιού (απευθείας κρατήσεις)
- Portal ιδιοκτήτη, admin και app καθαρισμού (ξεχωριστό project, π.χ. `app.ourbnb.gr`)

Το design είναι στο canvas «OurBnb — Ταυτότητα & Website» στο Claude.
