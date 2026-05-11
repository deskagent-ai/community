# Agent: E-Mails nach Absender suchen

Dieser Agent sucht in deinem Postfach nach E-Mails von einem bestimmten Absender aus den letzten 7 Tagen.

## Schritt 1: Zeitraum festlegen

- **Startdatum:** {{TODAY|sub:7d}}
- **Enddatum:** 

## Schritt 2: E-Mails suchen

Ich suche jetzt über die Microsoft Graph API nach E-Mails, die von '{{INPUT.sender_name}}' im festgelegten Zeitraum gesendet wurden.

```
msgraph_search_emails(
  query="from:{{INPUT.sender_name}}",
  date_from="{{TODAY|sub:7d}}",
  date_to="",
  limit=25
)
```

## Schritt 3: Ergebnisse anzeigen

Die gefundenen E-Mails werden hier aufgelistet. Wenn keine E-Mails gefunden wurden, informiere ich dich darüber.
