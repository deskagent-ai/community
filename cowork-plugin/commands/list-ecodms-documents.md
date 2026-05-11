# Agent: ecoDMS Dokumente auflisten

Listet die neuesten Dokumente aus dem ecoDMS-Archiv auf.

## Ablauf

### Schritt 1: Verbindung pruefen

```
test_connection()
```

Falls Fehler -> Melde dem User:
> "ecoDMS-Verbindung fehlgeschlagen. Bitte pruefe die Konfiguration in `config/apis.json`."

### Schritt 2: Dokumente abrufen

Suche die neuesten 20 Dokumente:

```
search_documents(limit=20)
```

### Schritt 3: Ergebnis formatieren

Zeige die Dokumente als Tabelle mit klickbaren Links:

```
## Neueste Dokumente in ecoDMS

| # | ID | Datum | Typ | Ordner | Bemerkung | Link |
|---|-----|-------|-----|--------|-----------|------|
| 1 | 123 | 2024-12-29 | Rechnung | Eingang | Rechnung Lieferant | [Dok](thumbnail_url) |
...

**Gesamt:** [count] Dokumente gefunden
```

**Hinweis:**
- Thumbnail-URL (Dok) erfordert Basic Auth im Browser
- Thumbnails verbrauchen keine API-Connects

### Optional: Details anzeigen

Falls der User Details zu einem Dokument moechte:

```
get_document_info(doc_id)
```

### Optional: Dokument herunterladen

Falls der User ein Dokument herunterladen moechte:

> "HINWEIS: Jeder Download verbraucht 1 API-Connect!"

```
download_document(doc_id, save_path=".temp")
```
