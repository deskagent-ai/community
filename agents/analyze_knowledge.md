---
{
  "name": "Knowledge analysieren",
  "category": "system",
  "description": "Analysiert die Knowledge Base auf Eignung, Struktur und Token-Effizienz",
  "icon": "analytics",
  "input": ":folder: Knowledge-Verzeichnis",
  "output": ":description: Analyse-Report mit Verbesserungsvorschlaegen",
  "allowed_mcp": "filesystem",
  "tool_mode": "read_only",
  "knowledge": "",
  "order": 87,
  "enabled": true,
  "anonymize": false
}
---

# Agent: Analyze Knowledge

Analysiert die Knowledge Base auf Eignung, Struktur und Token-Effizienz.

## Aufgabe

Analysiere das Knowledge-Verzeichnis und erstelle einen Report mit:
1. Strukturanalyse
2. Eignungsbewertung
3. Token-Effizienz
4. Verbesserungsvorschlaege

## Ablauf

### Phase 1: Dateien erfassen

```
fs_list_directory("{{KNOWLEDGE_DIR}}")
```

Fuer jeden gefundenen Ordner rekursiv:
```
fs_list_directory("{{KNOWLEDGE_DIR}}/[ordner]")
```

### Phase 2: Dateien analysieren

Fuer jede `.md` Datei:
```
fs_read_file("{{KNOWLEDGE_DIR}}/[datei]")
fs_get_file_info("{{KNOWLEDGE_DIR}}/[datei]")
```

Erfasse pro Datei:
- Dateiname und Pfad
- Groesse in Bytes
- Anzahl Zeilen
- Hauptthemen (H1/H2 Ueberschriften)
- Inhaltstyp (Produkt, FAQ, Technisch, Prozess, etc.)

### Phase 3: Analyse durchfuehren

**Strukturanalyse:**
| Kriterium | Bewertung |
|-----------|-----------|
| Klare Ordnerstruktur | Gibt es logische Unterordner? |
| Konsistente Benennung | Sind Dateinamen einheitlich? |
| Angemessene Granularitaet | Zu viele kleine oder zu wenige grosse Dateien? |
| Markdown-Qualitaet | Ueberschriften, Listen, Tabellen korrekt? |

**Eignungsbewertung:**
| Kriterium | Bewertung |
|-----------|-----------|
| Relevanz | Sind alle Inhalte fuer Agents nuetzlich? |
| Aktualitaet | Gibt es veraltete Informationen? |
| Vollstaendigkeit | Fehlen wichtige Themen? |
| Konsistenz | Widersprechen sich Informationen? |

**Token-Effizienz:**
| Kriterium | Bewertung |
|-----------|-----------|
| Duplikate | Gleiche Information in mehreren Dateien? |
| Redundanz | Unnoetige Wiederholungen? |
| Kompaktheit | Koennte Text kuerzer sein ohne Informationsverlust? |
| Format-Overhead | Zu viel Prose statt Tabellen/Listen? |

### Phase 4: Report erstellen

## Ausgabe-Format

```
=== Knowledge Base Analyse ===

Datum: {{TODAY}}
Verzeichnis: {{KNOWLEDGE_DIR}}

--- Uebersicht ---

| Metrik | Wert |
|--------|------|
| Dateien gesamt | X |
| Gesamtgroesse | X KB |
| Geschaetzte Tokens | ~X |
| Unterordner | X |

--- Datei-Inventar ---

| Datei | Groesse | Themen | Typ |
|-------|---------|--------|-----|
| [name] | X KB | [themen] | [typ] |

--- Strukturanalyse ---

Bewertung: [GUT / AKZEPTABEL / VERBESSERUNGSWUERDIG]

Staerken:
- [Staerke 1]
- [Staerke 2]

Schwaechen:
- [Schwaeche 1]
- [Schwaeche 2]

--- Eignungsbewertung ---

Bewertung: [GUT / AKZEPTABEL / VERBESSERUNGSWUERDIG]

[Detaillierte Bewertung nach Kriterien]

--- Token-Effizienz ---

Bewertung: [EFFIZIENT / AKZEPTABEL / INEFFIZIENT]

Potenzielle Einsparung: ~X% (~X Tokens)

Gefundene Probleme:
- [Problem 1]: [Beschreibung]
- [Problem 2]: [Beschreibung]

--- Verbesserungsvorschlaege ---

Prioritaet HOCH:
1. [Vorschlag]: [Begruendung]
   - Aktion: [Konkrete Massnahme]
   - Erwartete Einsparung: ~X Tokens

Prioritaet MITTEL:
2. [Vorschlag]: [Begruendung]

Prioritaet NIEDRIG:
3. [Vorschlag]: [Begruendung]

--- Zusammenfassung ---

[2-3 Saetze Gesamtbewertung mit wichtigster Empfehlung]
```

## Bewertungsmassstab

**Token-Schaetzung:**
- ~1 Token = ~4 Zeichen (Englisch)
- ~1 Token = ~2-3 Zeichen (Deutsch)
- Tabellen effizienter als Fliesstext (~30% weniger Tokens)

**Grenzwerte:**
| Metrik | Gut | Akzeptabel | Problematisch |
|--------|-----|------------|---------------|
| Knowledge gesamt | <20 KB | 20-50 KB | >50 KB |
| Einzeldatei | <5 KB | 5-10 KB | >10 KB |
| Duplikat-Anteil | <5% | 5-15% | >15% |

## Hinweise

- Zeige konkrete Beispiele fuer gefundene Probleme
- Gib umsetzbare Empfehlungen (was genau aendern)
- Priorisiere nach Impact (Token-Einsparung)
- Bei guter Knowledge Base: Kurze Bestaetigung genuegt
