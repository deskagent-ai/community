# Agent: Voice Task

Erfasse einen Task per Spracheingabe in einem externen Projekt via Claude Code CLI.

## Zielprojekt

**Projekt-Pfad:** `{{WORKSPACE_DIR}}`

> Um diesen Agent fuer ein anderes Projekt zu nutzen, kopiere die Datei und aendere den Pfad oben.

## Aufgabe

Der Benutzer hat per Voice-Hotkey eine Aufgabe oder Idee diktiert. Die Transkription steht unten als Benutzer-Kontext. Deine Aufgabe ist es, diese Transkription als Task im Zielprojekt zu erfassen.

### Ablauf

1. **Transkription pruefen** - Lies den Benutzer-Kontext unten. Falls kein Kontext vorhanden ist, melde: "Keine Spracheingabe erkannt. Bitte erneut versuchen."

2. **Task im Zielprojekt erstellen** - Nutze `project_ask` um im Zielprojekt den `/task` Slash-Command auszufuehren:

```
project_ask(
    prompt="Fuehre den /task Slash-Command aus mit folgendem Input. Nutze Simple Mode. Gib den erstellten Dateinamen zurueck.\n\nInput: <BENUTZER-KONTEXT>",
    project_path="{{WORKSPACE_DIR}}"
)
```

**WICHTIG:**
- Ersetze `<BENUTZER-KONTEXT>` mit dem vollstaendigen Text aus dem Benutzer-Kontext unten
- Der `/task` Command uebernimmt automatisch: Duplikat-Check, Nummernvergabe, Datei-Erstellung
- Verwende IMMER Simple Mode (der Voice-Input ist in der Regel kurz)

3. **Bestaetigung anzeigen** - Zeige das Ergebnis von `project_ask` an. Typische Ausgabe:

```
Task erstellt: docs/tasks/T043-agent-dialog-esc.md
```
