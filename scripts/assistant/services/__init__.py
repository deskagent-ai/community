# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Services package for DeskAgent.

Business logic and helper services that are decoupled from HTTP routes.
"""

from .ui_builder import (
    ICON_MAP,
    get_icon,
    build_tile_style,
    build_tile,
    build_chat_tile,
    build_web_ui,
)

from .uploads import (
    save_uploaded_files,
)

from .discovery import (
    clear_cache,
    parse_frontmatter,
    load_categories,
    discover_agents,
    discover_skills,
    get_agent_config,
    get_skill_config,
    discover_all,
    get_all_agent_names,
    get_all_skill_names,
)

from .mcp_proxy_manager import (
    start_mcp_proxy,
    stop_mcp_proxy,
    ensure_proxy_running,
    is_proxy_running,
    get_proxy_url,
    get_proxy_status,
    start_hub_if_enabled,
)
