# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Setup-Hinweise fuer MCP-Server (Schema-basierter Wrapper).

Laedt Setup-Hints aus INTEGRATION_SCHEMA der einzelnen MCPs.
Die fruehere zentrale MCP_HINTS-Konstante wurde in plan-047 durch
das `setup`-Feld in INTEGRATION_SCHEMA ersetzt.

Dieses Modul bleibt als API-stabiler Wrapper erhalten:
- get_mcp_hint(mcp_name) -> dict | None
- needs_configuration(mcp_name) -> bool
- get_setup_message(missing_mcps) -> str
- get_mcp_names() -> list[str]
"""

# Fallback: MCPs that never need configuration (auth_type="none").
# Used when schema loading fails (e.g. _mcp_api unavailable in dev env).
_NO_CONFIG_MCPS = frozenset({
    "filesystem", "clipboard", "chart", "desk", "pdf",
    "datastore", "excel", "browser", "project",
})


def get_mcp_hint(mcp_name: str) -> dict | None:
    """Holt Setup-Hint fuer einen MCP aus INTEGRATION_SCHEMA.

    Args:
        mcp_name: Name des MCP-Servers

    Returns:
        Dict mit name, description, requirement, setup_steps, alternative
        oder None wenn kein Setup noetig
    """
    from .integration_schema import get_schema_for_mcp

    schema = get_schema_for_mcp(mcp_name)
    if not schema:
        # No schema available - no-config MCPs definitely don't need setup
        return None

    setup = schema.get("setup")
    if setup:
        return {
            "name": schema.get("name", mcp_name.title()),
            "description": setup.get("description", ""),
            "requirement": setup.get("requirement", "Konfiguration erforderlich"),
            "setup_steps": setup.get("setup_steps", []),
            "alternative": setup.get("alternative"),
        }

    # No setup field and auth_type "none" -> no config needed
    if schema.get("auth_type", "none") == "none":
        return None

    # Has auth requirement but no setup hints -> generate minimal hint
    return {
        "name": schema.get("name", mcp_name.title()),
        "description": schema.get("description", ""),
        "requirement": "Konfiguration erforderlich",
        "setup_steps": [],
        "alternative": None,
    }


def get_setup_message(missing_mcps: list[str]) -> str:
    """Erstellt eine formatierte Nachricht fuer fehlende MCPs.

    Args:
        missing_mcps: Liste der fehlenden MCP-Namen

    Returns:
        Formatierte Nachricht fuer UI-Anzeige
    """
    if not missing_mcps:
        return ""

    lines = ["Die folgenden Dienste sind nicht konfiguriert:\n"]
    for mcp in missing_mcps:
        hint = get_mcp_hint(mcp)
        if hint is None:
            # Unbekannter MCP mit Konfigurationsbedarf
            lines.append(f"**{mcp}**: Konfiguration fehlt")
        else:
            lines.append(f"**{hint['name']}**: {hint.get('requirement', 'Setup erforderlich')}")
            if hint.get("alternative"):
                lines.append(f"  Alternative: {hint['alternative']}")

    lines.append("\nDer Agent kann trotzdem gestartet werden, aber einige Funktionen sind eingeschraenkt.")
    return "\n".join(lines)


def needs_configuration(mcp_name: str) -> bool:
    """Prueft ob ein MCP Konfiguration benoetigt.

    Args:
        mcp_name: Name des MCP-Servers

    Returns:
        True wenn Konfiguration noetig, False wenn immer verfuegbar
    """
    from .integration_schema import get_schema_for_mcp

    schema = get_schema_for_mcp(mcp_name)
    if not schema:
        # Schema loading failed - use hardcoded fallback
        return mcp_name not in _NO_CONFIG_MCPS
    return schema.get("auth_type", "none") != "none"


def get_mcp_names() -> list[str]:
    """Gibt Liste aller konfigurierbaren MCP-Namen zurueck.

    Filtert MCPs mit auth_type="none" heraus, da diese
    keine Konfigurationspruefung benoetigen.

    Returns:
        Liste von MCP-Namen die Prerequisites haben koennten
        z.B. ["outlook", "msgraph", "gmail", "billomat", ...]
    """
    from .integration_schema import get_all_integration_schemas

    schemas = get_all_integration_schemas()
    return [
        name
        for name, schema in schemas.items()
        if schema.get("auth_type", "none") != "none"
    ]
