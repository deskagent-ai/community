# Agent: Dokumente im DMS suchen

Dieser Agent durchsucht das DMS (ecoDMS und/oder Paperless) nach einem bestimmten Suchbegriff und listet die gefundenen Dokumente auf.

## Kontext

Der Benutzer gibt einen Suchbegriff an. Der Agent soll eine Volltextsuche in den verfügbaren DMS-Systemen durchführen und die Ergebnisse übersichtlich darstellen.

## Ablauf

1.  **Suchbegriff erhalten**: Der Suchbegriff wird aus dem `{{INPUT.search_term}}` Feld gelesen.
2.  **DMS durchsuchen**: Führe eine Suche in den verfügbaren DMS-Systemen durch.
    - Versuche zuerst `ecodms.search_documents(query=...)`.
    - Wenn das fehlschlägt oder keine Ergebnisse liefert, versuche `paperless.search_documents(query=...)`.
3.  **Ergebnisse aufbereiten**: Formatiere die Ergebnisse der DMS-Suche. Jeder Treffer sollte folgende Informationen enthalten:
    - Titel des Dokuments (als Link, falls verfügbar)
    - Datum des Dokuments
    - Eine kurze Inhaltsvorschau oder relevante Ausschnitte.
4.  **Ausgabe**: Gib die formatierte Liste der Ergebnisse aus. Wenn nichts gefunden wurde, informiere den Benutzer darüber.

## Verfügbare Tools

- `ecodms.search_documents`: Durchsucht ecoDMS.
- `paperless.search_documents`: Durchsucht Paperless-ngx.

## Output Format

```markdown
**Suchergebnisse für "{{INPUT.search_term}}"**

---

### [Titel des Dokuments 1](link/zum/dokument1)
**Datum:** DD.MM.YYYY
> ... kurzer Auszug aus dem Inhalt, in dem der Suchbegriff vorkommt ...

---

### [Titel des Dokuments 2](link/zum/dokument2)
**Datum:** DD.MM.YYYY
> ... kurzer Auszug aus dem Inhalt ...

---
...
```

## Wichtig

- Gib eine klare Rückmeldung, wenn in keinem der Systeme Ergebnisse gefunden wurden.
- Kombiniere die Ergebnisse, falls beide Systeme Treffer liefern.
