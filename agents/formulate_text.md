---
{
  "category": "kommunikation",
  "description": "Formuliert Text basierend auf Voice-Input und/oder Zwischenablage",
  "icon": "edit_note",
  "input": ":mic: Voice-Kontext / :assignment: Clipboard",
  "output": ":assignment: Formulierter Text eingefuegt",
  "allowed_mcp": "clipboard",
  "order": 35,
  "enabled": true
}
---

# Text formulieren

Formuliere Text basierend auf Voice-Input und/oder Zwischenablage und füge ihn direkt ein.

## Eingabe

- **Voice-Kontext** (optional): `{{INPUT._context}}` - Anweisungen/Wünsche des Benutzers
- **Zwischenablage**: Text als Grundlage (kann leer sein)

## Ablauf

1. **Zwischenablage lesen** - `clipboard_get_clipboard()`
2. **Kontext analysieren**:
   - Voice-Input = Anweisungen/Wünsche des Benutzers
   - Clipboard = Rohmaterial/Grundlage (falls vorhanden)
3. **Text formulieren** basierend auf:
   - Voice-Anweisungen (z.B. "mach das formeller", "kürze das", "schreibe eine E-Mail daraus")
   - Clipboard-Inhalt als Ausgangsmaterial
4. **Ergebnis in Zwischenablage** - `clipboard_set_clipboard(text)`
5. **Text einfügen** - `clipboard_paste_clipboard()` - fügt automatisch in die aktive Anwendung ein

## Regeln

- Halte den Output fokussiert und prägnant
- Behalte die Sprache des Inputs bei (Deutsch/Englisch)
- Falls kein Clipboard: Formuliere nur basierend auf Voice-Input
- Falls kein Voice-Input: Verbessere/formatiere den Clipboard-Text

## Ausgabe

- Zeige den formulierten Text kurz an
- Schreibe ihn in die Zwischenablage
- Füge ihn automatisch ein (Ctrl+V)
- Kurze Bestätigung: "✅ Text eingefügt"
