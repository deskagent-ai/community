# Agent: Gehaltsabrechnungen & Lohnsteuerbescheinigung extrahieren

Extrahiert folgende Dokumente für eine bestimmte Person aus PDF-Dateien:
1. **Gehaltsabrechnungen** - "Abrechnung der Brutto/Netto-Bezüge"
2. **Lohnsteuerbescheinigung** - "Ausdruck der elektronischen Lohnsteuerbescheinigung"

## Eingaben

**PDF-Dateien:**
{{INPUT.files}}

**Person:**
{{INPUT.person}}

## Aufgabe

### Schritt 1: PDFs analysieren

Lese alle PDFs mit `fs_read_pdf(pfad)` und suche nach Seiten die BEIDE Kriterien erfüllen:
1. Enthält einen der folgenden Titel:
   - **Gehaltsabrechnung:** "Abrechnung der Brutto/Netto-Bezüge" (oder "Gehaltsabrechnung", "Entgeltabrechnung")
   - **Lohnsteuerbescheinigung:** "Ausdruck der elektronischen Lohnsteuerbescheinigung"
2. Enthält den Namen der Person: **{{INPUT.person}}**

**WICHTIG - Mehrseitige Dokumente:**
- Beide Dokumenttypen können 1-2 Seiten umfassen
- Wenn Seite N einen der Titel enthält, prüfe ob Seite N+1 auch dazugehört (Fortsetzung, gleiche Person, kein neuer Dokumenttitel)
- Extrahiere dann BEIDE Seiten zusammen (z.B. "3-4" statt nur "3")

**Notiere für jeden Treffer:**
- Welche PDF-Datei
- Welche Seitennummer(n) - einzeln oder Bereich (z.B. "5" oder "5-6")
- Welcher Monat/Zeitraum (falls erkennbar aus dem Dokument)
- Welcher Dokumenttyp (Gehaltsabrechnung oder Lohnsteuerbescheinigung)

**WICHTIG - Duplikate vermeiden:**
- Prüfe vor dem Export ob ein Dokument mit gleichem Typ UND Monat/Jahr bereits gefunden wurde
- Wenn dasselbe Dokument in mehreren PDFs vorkommt → nur EINMAL exportieren
- Vergleiche anhand: Dokumenttyp + Monat + Jahr + Person

### Schritt 2: Seiten extrahieren

Für jeden EINZIGARTIGEN Treffer (keine Duplikate):
1. Extrahiere die relevante(n) Seite(n) mit `extract_pages()`
   - Bei 1 Seite: `pages="5"`
   - Bei 2 Seiten: `pages="5-6"`
2. Speichere in `exports/` mit sprechendem Namen

**Dateinamens-Format (ohne Unterstriche):**

Für Gehaltsabrechnungen:
`Gehaltsabrechnung<Nachname><Monat><Jahr>.pdf`

Für Lohnsteuerbescheinigung:
`Lohnsteuerbescheinigung<Nachname><Jahr>.pdf`

Beispiele:
- `GehaltsabrechnungMustermannJanuar2025.pdf`
- `GehaltsabrechnungMustermannFebruar2025.pdf`
- `LohnsteuerbescheinigungMustermann2025.pdf`

### Schritt 3: Zusammenfassung

Gib eine detaillierte Übersicht aus:

---

**Extrahierte Dokumente für {{INPUT.person}}:**

| Quelldatei | Quellseiten | → | Zieldatei | Zielseiten |
|------------|-------------|---|-----------|------------|
| Lohnabrechnung_2025.pdf | 3-4 | → | GehaltsabrechnungMustermannJanuar2025.pdf | 1-2 |
| Lohnabrechnung_2025.pdf | 7-8 | → | GehaltsabrechnungMustermannFebruar2025.pdf | 1-2 |
| Lohnabrechnung_2025.pdf | 15 | → | LohnsteuerbescheinigungMustermann2025.pdf | 1 |

**Statistik:**
- Gehaltsabrechnungen: 2 Dokumente
- Lohnsteuerbescheinigungen: 1 Dokument
- Gesamt: 3 Dokumente exportiert

**Übersprungene Duplikate:** (falls vorhanden)
- Archiv_2025.pdf Seite 5: Gehaltsabrechnung Januar 2025 (bereits aus Lohnabrechnung_2025.pdf exportiert)

**Speicherort:** `exports/`

---

### Fehlerbehandlung

- **Keine Treffer:** Melde dass keine Gehaltsabrechnung oder Lohnsteuerbescheinigung für diese Person gefunden wurde
- **PDF nicht lesbar:** Überspringe und melde welche Datei nicht gelesen werden konnte
- **Mehrere Personen auf einer Seite:** Extrahiere trotzdem (Seite enthält den gesuchten Namen)
