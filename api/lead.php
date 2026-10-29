<?php
/**
 * OurBnb — φόρμα «Πόσα μπορεί να βγάλει το σπίτι σου;»
 * Στέλνει το αίτημα με email. Τρέχει σε κάθε hosting με PHP 8 (π.χ. Hostinger).
 */
declare(strict_types=1);

// ---- Ρυθμίσεις ----------------------------------------------------------
const TO_EMAIL   = 'petrospikionis@gmail.com';   // πού έρχονται τα αιτήματα
const FROM_EMAIL = 'no-reply@ourbnb.gr';          // email του domain (φτιάξ' το στο hPanel → Emails)
const SITE_NAME  = 'OurBnb';
// --------------------------------------------------------------------------

date_default_timezone_set('Europe/Athens');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

$wantsJson = strpos($_SERVER['HTTP_ACCEPT'] ?? '', 'application/json') !== false;

function respond(bool $ok, string $message, int $status, bool $wantsJson): void
{
    http_response_code($status);
    if ($wantsJson) {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['ok' => $ok, 'message' => $message], JSON_UNESCAPED_UNICODE);
    } else {
        header('Location: /?lead=' . ($ok ? 'ok' : 'error') . '#ektimisi', true, 303);
    }
    exit;
}

function clean(string $value, int $max): string
{
    $value = trim((string) preg_replace('/[\r\n\t\x00-\x1F\x7F]+/u', ' ', $value));
    return function_exists('mb_substr') ? mb_substr($value, 0, $max) : substr($value, 0, $max);
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    respond(false, 'Μη έγκυρο αίτημα.', 405, $wantsJson);
}

// Anti-spam: κρυφό πεδίο και χρόνος συμπλήρωσης. Στα bots απαντάμε «ok» χωρίς να στείλουμε τίποτα.
if (!empty($_POST['website'])) {
    respond(true, 'ok', 200, $wantsJson);
}
$ts = isset($_POST['ts']) ? (int) $_POST['ts'] : 0;
if ($ts > 0 && (time() - $ts) < 3) {
    respond(true, 'ok', 200, $wantsJson);
}

$areas = ['Κως (πόλη)', 'Ψαλίδι', 'Λάμπη', 'Τιγκάκι', 'Μαρμάρι', 'Μαστιχάρι', 'Καρδάμαινα',
          'Κέφαλος', 'Ζηπάρι', 'Αντιμάχεια', 'Πυλί', 'Άλλη περιοχή'];
$bedroomsAllowed = ['1', '2', '3', '4', '5+'];
$onlineLabels = ['no' => 'Όχι ακόμα', 'one' => 'Ναι, σε ένα', 'both' => 'Ναι, και στα δύο'];

$name     = clean((string) ($_POST['name'] ?? ''), 100);
$phone    = clean((string) ($_POST['phone'] ?? ''), 30);
$area     = clean((string) ($_POST['area'] ?? ''), 40);
$bedrooms = clean((string) ($_POST['bedrooms'] ?? ''), 4);
$online   = clean((string) ($_POST['online'] ?? ''), 4);

if ($name === '' || $phone === '' || !preg_match('/^[0-9+()\-\s]{6,30}$/', $phone)) {
    respond(false, 'Συμπλήρωσε όνομα και ένα σωστό τηλέφωνο.', 422, $wantsJson);
}
if (!in_array($area, $areas, true)) {
    $area = 'Δεν δηλώθηκε';
}
if (!in_array($bedrooms, $bedroomsAllowed, true)) {
    $bedrooms = '-';
}
$onlineText = $onlineLabels[$online] ?? '-';

$subject = 'Νέο αίτημα εκτίμησης: ' . $area;
$body = "Νέο αίτημα εκτίμησης από το ourbnb.gr\n\n"
      . "Όνομα: {$name}\n"
      . "Τηλέφωνο: {$phone}\n"
      . "Περιοχή: {$area}\n"
      . "Υπνοδωμάτια: {$bedrooms}\n"
      . "Ήδη σε Booking.com ή Airbnb: {$onlineText}\n\n"
      . 'Ημερομηνία: ' . date('d/m/Y H:i') . "\n";

$headers = implode("\r\n", [
    'From: ' . SITE_NAME . ' <' . FROM_EMAIL . '>',
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: 8bit',
]);
$encodedSubject = '=?UTF-8?B?' . base64_encode($subject) . '?=';

$sent = @mail(TO_EMAIL, $encodedSubject, $body, $headers, '-f' . FROM_EMAIL);
if (!$sent) {
    // Κάποιοι servers δεν επιτρέπουν το -f· δοκίμασε χωρίς αυτό.
    $sent = @mail(TO_EMAIL, $encodedSubject, $body, $headers);
}

if ($sent) {
    respond(true, 'Ευχαριστούμε! Θα σε πάρουμε τηλέφωνο σύντομα.', 200, $wantsJson);
}
respond(false, 'Κάτι πήγε στραβά. Πάρε μας τηλέφωνο στο 694 803 4055.', 500, $wantsJson);
