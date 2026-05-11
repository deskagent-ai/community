# DeskAgent Lizenzierung

Diese Dokumentation beschreibt, wie DeskAgent lizenziert und aktiviert wird.

## Lizenzmodell

DeskAgent verwendet ein **Session-basiertes Lizenzmodell**:

- **Pro Gerät**: Eine Lizenz erlaubt die Nutzung auf einem Gerät gleichzeitig
- **Gerätewechsel**: Lizenz kann deaktiviert und auf einem anderen Gerät aktiviert werden
- **Automatische Wiederaufnahme**: Nach dem Neustart wird die Lizenz automatisch wiederhergestellt

## Aktivierung

### Schritt 1: Einstellungen öffnen

Klicke auf das **Zahnrad-Symbol** (⚙️) oben rechts, um die Einstellungen zu öffnen.

### Schritt 2: Lizenz-Tab wählen

Wähle den **Lizenz**-Tab in der Tab-Leiste.

### Schritt 3: Aktivierungsmethode wählen

Es gibt zwei Aktivierungsmethoden:

#### Per Rechnung

Wenn du DeskAgent über eine Rechnung erworben hast:

1. Wähle **"per Rechnung"**
2. Gib deine **Rechnungsnummer** ein (z.B. `RE-2025-0123`)
3. Gib deine **PLZ** (Postleitzahl der Rechnungsadresse) ein
4. Gib deine **E-Mail-Adresse** ein
5. Klicke **"Aktivieren"**

#### Per Code

Wenn du einen Aktivierungscode erhalten hast (z.B. SUB-Code für Team-Mitglieder):

1. Wähle **"per Code"**
2. Gib deinen **Aktivierungscode** ein (Format: `SUB-XXXX-YYYY-ZZZZ`)
3. Gib deine **E-Mail-Adresse** ein
4. Klicke **"Aktivieren"**

## Lizenzstatus prüfen

Der aktuelle Lizenzstatus wird im Lizenz-Tab angezeigt:

| Status | Bedeutung |
|--------|-----------|
| **AKTIV** (grün) | Lizenz ist gültig und aktiv |
| **OFFLINE** (blau) | Lizenz läuft im Offline-Modus (Server nicht erreichbar) |
| **OFFLINE** (orange) | Warnung: Offline-Zeit läuft bald ab |
| **INAKTIV** (rot) | Keine aktive Lizenz |

### Angezeigte Informationen

- **E-Mail**: Die mit der Lizenz verknüpfte E-Mail-Adresse
- **Gerät**: Name des aktuellen Computers
- **Geräte-ID**: Eindeutige ID zur Geräteidentifikation
- **Gültig bis**: Ablaufdatum der Lizenz (falls zeitlich begrenzt)

## Deaktivierung

Um die Lizenz zu deaktivieren (z.B. für Gerätewechsel):

1. Öffne **Einstellungen** → **Lizenz**
2. Klicke den **"Deaktivieren"**-Button (⊗)
3. Die Lizenz wird vom Server freigegeben

**Hinweis**: Nach der Deaktivierung kann die Lizenz auf einem anderen Gerät aktiviert werden.

## Offline-Modus (Grace Period)

DeskAgent kann auch ohne Internetverbindung betrieben werden:

### Wie es funktioniert

1. Bei jeder erfolgreichen Verbindung zum Lizenzserver wird ein Zeitstempel gespeichert
2. Wenn der Server nicht erreichbar ist, läuft DeskAgent im **Offline-Modus** weiter
3. Nach **48 Stunden** ohne Serververbindung wird DeskAgent blockiert
4. Ab **8 Stunden** verbleibender Zeit wird eine Warnung angezeigt

### Bei Verbindungsproblemen

Wenn der Offline-Modus angezeigt wird:

1. Prüfe deine Internetverbindung
2. Klicke **"Erneut versuchen"** im Warnbanner
3. Sobald die Verbindung wiederhergestellt ist, läuft DeskAgent normal weiter

### Wichtig

- Die Erstaktivierung erfordert eine Internetverbindung
- Nach erfolgreicher Aktivierung ist Offline-Betrieb möglich
- Regelmäßige Verbindungen (mindestens alle 48h) werden empfohlen

## Team-Lizenzen (SUB-Codes)

Für Unternehmen mit mehreren Nutzern:

### SUB-Codes erhalten

1. Der Lizenzinhaber loggt sich im **Kundenportal** ein
2. Navigiert zu **"Team-Lizenzen"**
3. Generiert neue **SUB-Codes** für Team-Mitglieder
4. Die Codes werden per E-Mail verteilt

### SUB-Codes verwenden

Team-Mitglieder aktivieren DeskAgent mit:

1. **"per Code"** wählen
2. Den erhaltenen **SUB-Code** eingeben
3. Eigene **E-Mail-Adresse** eingeben
4. **"Aktivieren"** klicken

**Hinweis**: SUB-Codes zählen gegen das Kontingent des Hauptkontos.

## Fehlerbehebung

### "Server nicht erreichbar"

**Mögliche Ursachen:**
- Keine Internetverbindung
- Firewall blockiert die Verbindung
- Proxy-Einstellungen fehlen

**Lösung:**
1. Internetverbindung prüfen
2. Firewall für DeskAgent freigeben
3. Proxy-Einstellungen in den Systemeinstellungen konfigurieren

### "Ungültige Anmeldedaten"

**Mögliche Ursachen:**
- Rechnungsnummer falsch eingegeben
- PLZ stimmt nicht mit Rechnungsadresse überein
- Code wurde bereits verwendet

**Lösung:**
1. Rechnungsnummer auf der Originalrechnung prüfen
2. PLZ der **Rechnungsadresse** (nicht Lieferadresse) verwenden
3. Bei Code-Problemen: Support kontaktieren

### "Maximale Geräteanzahl erreicht"

**Ursache:** Die Lizenz ist bereits auf einem anderen Gerät aktiv.

**Lösung:**
1. Auf dem anderen Gerät deaktivieren
2. Oder: Im Kundenportal alle Sessions verwalten

## Support

Bei Lizenzproblemen:

- **E-Mail**: support@deskagent.de
- **Kundenportal**: https://portal.deskagent.de
