# Agent: Duplikate finden

Analysiert eine Dateisammlung und findet Duplikate.

## Zu prüfende Dateien/Ordner
{{INPUT.files}}

## Aufgabe

**WICHTIG:** Die oben aufgelisteten Pfade sind bereits die vollständigen Dateipfade. Verwende diese Pfade DIREKT mit den Tools.

### Schritt 1: Dateien sammeln

- Die Pfade oben unter "Zu prüfende Dateien/Ordner" sind Dateien ODER Ordner
- Prüfe jeden Pfad mit `fs_get_file_info(pfad)` → zeigt ob Datei oder Ordner
- Bei Ordner: `fs_list_directory(pfad)` → sammle alle enthaltenen Dateien
- Bei Datei: Direkt `fs_get_file_info(pfad)` für Größe/Metadaten

### Schritt 2: Duplikate identifizieren

Prüfe auf Duplikate anhand von:
- **Exakte Duplikate**: Gleicher Dateiname UND gleiche Größe
- **Namens-Duplikate**: Gleicher Dateiname, unterschiedliche Größe (verschiedene Versionen?)
- **Größen-Duplikate**: Unterschiedlicher Name, gleiche Größe (potentielle Kopien)

### Schritt 3: Inhalt bei Größen-Duplikaten vergleichen

**WICHTIG:** Bei Dateien mit gleicher Größe aber unterschiedlichem Namen:
- Verwende `fs_read_pdf(pfad)` für PDF-Dateien um den Textinhalt zu extrahieren
- Verwende `fs_read_file(pfad)` für Textdateien
- Vergleiche die ersten ~500 Zeichen des Inhalts
- Markiere als **echtes Duplikat** wenn der Inhalt identisch ist
- Markiere als **möglicherweise unterschiedlich** wenn der Inhalt abweicht

### Schritt 4: Ergebnis ausgeben

Zeige das Ergebnis im folgenden Format:

---

### Zusammenfassung
- X Dateien geprüft
- Y echte Duplikate gefunden (identischer Inhalt)
- Z Namens-Duplikate (verschiedene Versionen)

### Echte Duplikate (identischer Inhalt)

| Original | Duplikate (können gelöscht werden) |
|----------|-----------------------------------|
| Pfad1 (behalten) | Pfad2, Pfad3 |

### Namens-Duplikate (gleicher Name, andere Größe)

| Dateiname | Varianten |
|-----------|-----------|
| ... | Pfad1 (1.2MB), Pfad2 (1.5MB) |

### Größen-Gleich aber unterschiedlicher Inhalt

| Größe | Dateien (NICHT löschen) |
|-------|------------------------|
| ... | Pfad1, Pfad2 |

---

### Schritt 5: Löschen anbieten

Wenn echte Duplikate gefunden wurden, biete am Ende das Löschen an:

```
QUESTION_NEEDED: {
  "question": "Sollen die Duplikate gelöscht werden?",
  "options": [
    {"value": "delete_all", "label": "Alle Duplikate löschen"},
    {"value": "delete_none", "label": "Nichts löschen"}
  ],
  "allow_custom": false
}
```

### Schritt 6: Bei "delete_all" - Dateien löschen

Wenn der User "delete_all" wählt:
1. Lösche alle als Duplikat markierten Dateien mit `fs_delete_file(pfad)`
2. Gib eine Bestätigung aus welche Dateien gelöscht wurden
3. Bei Fehlern: Fehler anzeigen aber mit anderen Dateien fortfahren

**WICHTIG:** Lösche NUR die Duplikate, NICHT die Originale!
