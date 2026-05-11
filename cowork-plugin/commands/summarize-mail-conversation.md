# Agent: E-Mail-Konversation zusammenfassen

Fasst eine E-Mail-Konversation zusammen, indem alle zugehoerigen E-Mails gesucht und analysiert werden.

## Aufgabe

**WICHTIG: Sofort loslegen ohne Rueckfragen!**

1. **Kontext ermitteln (automatisch, PARALLEL ausfuehren)**
   - `clipboard_get_clipboard()` UND `outlook_get_selected_email()` gleichzeitig aufrufen
   - Nutze was verfuegbar ist (Clipboard hat Prioritaet wenn nuetzlich)
   - NUR wenn beides leer/fehlschlaegt: Frage nach E-Mail-Adresse

2. **E-Mail-Adresse extrahieren**
   - Identifiziere die relevante E-Mail-Adresse aus dem Kontext
   - Bei mehreren Adressen: Waehle die externe (nicht die eigene Domain)

3. **API-Verfuegbarkeit pruefen**
   - Rufe `graph_status()` auf um zu pruefen ob Microsoft Graph verfuegbar ist
   - Wenn "authenticated: True" → Nutze Graph API (findet ALLE E-Mails, auch alte)
   - Wenn nicht authentifiziert → Fallback auf Outlook (nur lokal gecachte E-Mails)

4. **Konversation suchen**

   **Mit Graph API (bevorzugt):**
   - `graph_search_emails(email_adresse, limit=50)` - Server-seitige Suche
   - `graph_get_email(message_id)` - Vollstaendigen Inhalt abrufen

   **Fallback Outlook:**
   - `outlook_fast_search_emails(email_adresse, limit=20)` - Windows Search Index
   - `outlook_fast_get_email_content(email_adresse, index=N)` - Index 0 = neueste

5. **Details abrufen**
   - Bei Graph: Nutze die message_id aus den Suchergebnissen
   - Bei Outlook: Nutze den Index (0 = neueste, 1 = zweitneueste, etc.)

6. **Zusammenfassung erstellen**

## Ausgabeformat

### Konversation mit [Name/E-Mail]

**Zeitraum:** [Erste E-Mail] bis [Letzte E-Mail]
**Anzahl E-Mails:** X

#### Chronologischer Verlauf

| Datum | Richtung | Betreff | Zusammenfassung |
|-------|----------|---------|-----------------|
| DD.MM.YYYY | Eingang/Ausgang | ... | ... |

---

### Fazit

#### Wichtige Punkte
- [Die wichtigsten Erkenntnisse und Vereinbarungen]
- [Entscheidungen die getroffen wurden]
- [Relevante Fakten fuer zukuenftige Kommunikation]

#### Offene Punkte / Naechste Schritte
- [Was muss noch geklaert werden?]
- [Wer muss was tun?]
- [Deadlines falls vorhanden]

## Verfuegbare Tools

**Kontext:**
- `clipboard_get_clipboard()` - Zwischenablage lesen
- `outlook_get_selected_email()` - Markierte E-Mail lesen

**Microsoft Graph API (bevorzugt - findet ALLE E-Mails):**
- `graph_status()` - Pruefen ob Graph API verfuegbar ist
- `graph_search_emails(query, limit)` - Server-seitige Suche auf Exchange
- `graph_get_email(message_id)` - Vollstaendigen E-Mail-Inhalt abrufen

**Outlook Fallback (nur lokal gecachte E-Mails):**
- `outlook_fast_search_emails(query, limit)` - Windows Search Index
- `outlook_fast_get_email_content(query, index)` - E-Mail-Inhalt aus Suchergebnissen

## Hinweise

- **Graph API Vorteile:** Findet auch aeltere E-Mails die nicht mehr lokal gecacht sind
- **Outlook Vorteile:** Funktioniert offline, schneller fuer aktuelle E-Mails
- Die Suche ist case-insensitive
- Bei E-Mail-Adressen: Suche direkt nach der Adresse (z.B. "max@example.com")
- Bei Namen: Suche nach dem Namen (z.B. "Max Mustermann")
