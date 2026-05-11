# Agent: Paperless Export für Steuerberater

Dieser Agent exportiert alle Dokumente, die für den Steuerberater markiert sind und noch nicht exportiert wurden.

## Ablauf

1.  **Custom Field ID finden:** Finde zuerst die ID des benutzerdefinierten Feldes "Steuerberater" mit `paperless.get_custom_fields()`. Du wirst diese ID später zum Aktualisieren der Dokumente benötigen.
2.  **Suchen:** Finde alle Dokumente in Paperless, die das Tag "Steuerberater" haben UND bei denen das benutzerdefinierte Feld "Steuerberater" noch leer ist. Die Suchabfrage dafür lautet: `tag:steuerberater AND custom_field_Steuerberater:null`.
3.  **Verzeichnis prüfen:** Stelle sicher, dass das Export-Verzeichnis `{{EXPORTS_DIR}}/steuerberater/` existiert. Wenn nicht, erstelle es.
4.  **Exportieren & Aktualisieren (Loop):** Gehe jedes gefundene Dokument durch:
    a. Lade das Dokument mit `paperless.export_document_pdf()` in das Zielverzeichnis herunter.
    b. Wenn der Download erfolgreich war, aktualisiere das Dokument mit `paperless.update_document()`. Setze dabei das benutzerdefinierte Feld "Steuerberater" auf das heutige Datum (Format YYYY-MM-DD). Du benötigst hier die ID aus Schritt 1.
5.  **Zusammenfassen:** Gib am Ende eine Zusammenfassung aus, wie viele Dokumente erfolgreich exportiert und aktualisiert wurden.

## Wichtige Hinweise

-   Das Tag in Paperless muss "Steuerberater" heißen.
-   Ein benutzerdefiniertes Feld vom Typ "Date" mit dem Namen "Steuerberater" muss in Paperless existieren.
-   Die `update_document` Funktion erwartet die Custom Field ID, nicht den Namen.
