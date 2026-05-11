#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Chart MCP Server
================
MCP Server for creating Apache ECharts visualizations in the agent chat.
Charts are rendered in the WebUI frontend (interactive, theme-aware, exportable).

The agent learns chart structure from detailed tool docstrings.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config

mcp = FastMCP("chart")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "bar_chart",
    "color": "#ff9800"  # Orange for charts
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "Charts",
    "icon": "bar_chart",
    "color": "#ff9800",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}

# No high-risk tools - chart operations don't return untrusted content
HIGH_RISK_TOOLS = set()

# Not destructive - charts are read-only displays
DESTRUCTIVE_TOOLS = set()

# Default color palette for auto-generation
DEFAULT_COLORS = [
    "#4285f4",  # Google Blue
    "#ea4335",  # Google Red
    "#fbbc04",  # Google Yellow
    "#34a853",  # Google Green
    "#ff6d01",  # Orange
    "#46bdc6",  # Cyan
    "#7baaf7",  # Light Blue
    "#f07b72",  # Light Red
    "#fcd04f",  # Light Yellow
    "#81c784",  # Light Green
]


def is_configured() -> bool:
    """Chart MCP is always available (frontend rendering).

    Can be disabled via chart.enabled in config.
    """
    config = load_config()
    mcp_config = config.get("chart", {})
    return mcp_config.get("enabled", True) is not False


@mcp.tool()
def chart_create(
    chart_type: str,
    labels: list[str],
    datasets: list[dict],
    title: str = "",
    options: Optional[dict] = None
) -> str:
    """Create a chart to visualize data. Use proactively when presenting
    numerical data, comparisons, trends, or distributions.

    Args:
        chart_type: Chart type to use:
            - "bar": Compare categories (sales by region, survey results)
            - "line": Show trends over time (monthly growth, stock prices)
            - "pie": Show parts of whole (market share, budget)
            - "radar": Compare multiple variables (skill assessment)
        labels: X-axis labels, e.g. ["Jan", "Feb", "Mar"] or ["Product A", "Product B"]
        datasets: List of data series. Each dataset is a dict:
            {
                "label": "Series name",           # Legend label
                "data": [10, 20, 30],             # Values (must match labels count)
                "color": "#4285f4"                # Optional - auto-generated if omitted
            }
        title: Optional chart title displayed above the chart
        options: Optional ECharts options to override defaults (rarely needed)

    Returns:
        Chart marker for WebUI rendering + human-readable summary

    Examples:
        # Simple bar chart:
        chart_create("bar", ["Q1", "Q2", "Q3"], [{"label": "Revenue", "data": [100, 150, 120]}])

        # Multi-series line chart:
        chart_create("line", ["Jan", "Feb", "Mar"], [
            {"label": "Sales", "data": [50, 80, 65]},
            {"label": "Costs", "data": [30, 45, 40]}
        ], title="Q1 Performance")

        # Pie chart:
        chart_create("pie", ["Desktop", "Mobile", "Tablet"],
                     [{"label": "Traffic", "data": [60, 35, 5]}])
    """
    # Validate chart type
    valid_types = ["bar", "line", "pie", "radar", "scatter"]
    if chart_type not in valid_types:
        return f"Error: Invalid chart type '{chart_type}'. Valid types: {', '.join(valid_types)}"

    # Validate inputs
    if not labels:
        return "Error: labels cannot be empty"
    if not datasets:
        return "Error: datasets cannot be empty"

    # Validate each dataset
    for i, ds in enumerate(datasets):
        if not isinstance(ds, dict):
            return f"Error: Dataset {i} must be a dict, got {type(ds).__name__}"
        if "data" not in ds:
            return f"Error: Dataset {i} missing 'data' field"
        if not isinstance(ds["data"], list):
            return f"Error: Dataset {i} 'data' must be a list"
        # Check data length (except for scatter which has different structure)
        if chart_type not in ["scatter"]:
            if len(ds["data"]) != len(labels):
                return f"Error: Dataset {i} has {len(ds['data'])} values but {len(labels)} labels"

    # Build ECharts option object
    option = {
        "tooltip": {},
        "legend": {}
    }

    # Add title if provided
    if title:
        option["title"] = {
            "text": title,
            "left": "center"
        }

    # Pie chart: position legend below title to avoid overlap
    if chart_type == "pie":
        option["legend"] = {
            "top": 40 if title else 10,
            "left": "center"
        }

    # Build series data
    series = []
    for i, ds in enumerate(datasets):
        series_item = {
            "name": ds.get("label", f"Series {i+1}"),
            "type": chart_type,
            "data": ds["data"]
        }

        # Add color if provided, otherwise use default palette
        color = ds.get("color") or ds.get("backgroundColor")
        if color:
            series_item["itemStyle"] = {"color": color}
        elif not color and i < len(DEFAULT_COLORS):
            series_item["itemStyle"] = {"color": DEFAULT_COLORS[i]}

        # Pie chart specific settings
        if chart_type == "pie":
            series_item["radius"] = "55%"
            series_item["center"] = ["50%", "58%"]  # Shift down to make room for legend
            # For pie charts, we need to format data as [{name, value}]
            # Each segment gets its own color from the palette
            series_item["data"] = [
                {
                    "name": labels[j],
                    "value": ds["data"][j],
                    "itemStyle": {"color": DEFAULT_COLORS[j % len(DEFAULT_COLORS)]}
                }
                for j in range(len(labels))
            ]
            # Remove series-level itemStyle (individual segment colors take precedence)
            if "itemStyle" in series_item:
                del series_item["itemStyle"]
            # Smart label layout to avoid overlap
            series_item["label"] = {
                "show": True,
                "formatter": "{b}: {d}%"  # Name: Percentage
            }
            series_item["labelLayout"] = {
                "hideOverlap": True,  # Auto-hide overlapping labels
                "moveOverlap": "shiftY"  # Shift labels vertically to reduce overlap
            }
            series_item["emphasis"] = {
                "label": {"show": True, "fontWeight": "bold"},
                "itemStyle": {
                    "shadowBlur": 10,
                    "shadowOffsetX": 0,
                    "shadowColor": "rgba(0, 0, 0, 0.5)"
                }
            }

        series.append(series_item)

    option["series"] = series

    # For non-pie charts, add axes
    if chart_type not in ["pie", "radar"]:
        label_count = len(labels)
        max_label_len = max(len(str(lbl)) for lbl in labels) if labels else 0

        # Use ECharts built-in auto-layout features
        axis_label = {
            "hideOverlap": True,  # ECharts 5+ auto-hides overlapping labels
            "interval": 0,  # Try to show all labels (hideOverlap handles overflow)
        }

        # Determine rotation: more labels or longer labels = steeper angle
        if label_count > 8 or max_label_len > 10:
            # Rotate labels for better fit - 45° is a good default
            axis_label["rotate"] = 45
            if label_count > 15 or max_label_len > 15:
                # Very crowded - go vertical
                axis_label["rotate"] = 90

        # Auto-scale font size based on label count
        if label_count > 25:
            axis_label["fontSize"] = 9
        elif label_count > 15:
            axis_label["fontSize"] = 10
        elif label_count > 10:
            axis_label["fontSize"] = 11
        # Default is 12px (ECharts standard)

        option["xAxis"] = {
            "type": "category",
            "data": labels,
            "axisLabel": axis_label
        }
        option["yAxis"] = {
            "type": "value"
        }

        # containLabel: true makes grid auto-adjust to fit rotated labels
        option["grid"] = {
            "containLabel": True,
            "left": 10,
            "right": 10,
            "bottom": 10
        }

    # For radar charts, add radar indicator
    if chart_type == "radar":
        option["radar"] = {
            "indicator": [{"name": label} for label in labels]
        }
        # Radar data format is different: [[values]]
        for series_item in series:
            series_item["data"] = [{"value": series_item["data"]}]

    # Apply custom options if provided
    if options:
        option.update(options)

    # Serialize option to JSON
    option_json = json.dumps(option, ensure_ascii=False)

    # Create human-readable summary
    summary_parts = [f"Chart: {chart_type.capitalize()} chart"]
    if title:
        summary_parts.append(f'"{title}"')
    summary_parts.append(f"with {len(datasets)} dataset(s) and {len(labels)} data points")
    summary = " ".join(summary_parts)

    # Return marker + summary
    # Use [/CHART] end marker for reliable extraction (nested JSON)
    return f"[CHART:{option_json}[/CHART]]\n\n{summary}"


@mcp.tool()
def chart_from_table(
    headers: list[str],
    rows: list[list],
    chart_type: str = "bar",
    title: str = "",
    label_column: int = 0
) -> str:
    """Convert tabular data to chart. First column becomes labels by default.

    Useful when you have data in table format (e.g., from a spreadsheet or database).
    Charts are exportable as PNG via the download button in the chart toolbar.

    Args:
        headers: Column headers, e.g. ["Month", "Revenue", "Costs"]
        rows: Table rows as nested lists, e.g. [["Jan", 100, 60], ["Feb", 120, 70]]
        chart_type: Chart type (default: "bar"). See chart_create for options.
        title: Optional chart title
        label_column: Which column to use as labels (default: 0, first column)

    Returns:
        Chart marker for WebUI rendering (with export button)

    Example:
        chart_from_table(
            ["Month", "Revenue", "Costs"],
            [["Jan", 100, 60], ["Feb", 120, 70], ["Mar", 150, 80]],
            chart_type="line",
            title="Q1 Financials"
        )
    """
    # Validate inputs
    if not headers:
        return "Error: headers cannot be empty"
    if not rows:
        return "Error: rows cannot be empty"
    if label_column >= len(headers):
        return f"Error: label_column {label_column} out of range (headers has {len(headers)} columns)"

    # Extract labels from specified column
    labels = []
    for row in rows:
        if label_column < len(row):
            labels.append(str(row[label_column]))
        else:
            labels.append("")

    # Create datasets from other columns
    datasets = []
    for col_idx, header in enumerate(headers):
        if col_idx == label_column:
            continue  # Skip label column

        data = []
        for row in rows:
            if col_idx < len(row):
                val = row[col_idx]
                # Try to convert to number
                if isinstance(val, (int, float)):
                    data.append(val)
                elif isinstance(val, str):
                    # Try parsing as number
                    try:
                        cleaned = val.replace(',', '.').replace(' ', '')
                        data.append(float(cleaned))
                    except ValueError:
                        data.append(0)
                else:
                    data.append(0)
            else:
                data.append(0)

        datasets.append({
            "label": header,
            "data": data
        })

    # Delegate to chart_create
    return chart_create(chart_type, labels, datasets, title)


if __name__ == "__main__":
    mcp.run()
