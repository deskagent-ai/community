# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Instagram MCP - Insights Module
===============================
Tools for reading Instagram analytics and insights.

Note: Insights are only available for Instagram Business and Creator accounts.
"""

from datetime import datetime, timedelta
from instagram.base import (
    mcp, instagram_tool, require_auth,
    api_request, get_instagram_account_id
)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_profile_insights(period: str = "day") -> str:
    """Get insights for your Instagram profile.

    Args:
        period: Time period - "day", "week", "days_28", or "lifetime"
                (default "day")

    Returns:
        Profile insights including reach, impressions, profile views, etc.
    """
    ig_id = get_instagram_account_id()

    # Define metrics based on period
    # Some metrics are only available for certain periods
    if period == "lifetime":
        metrics = ["audience_city", "audience_country", "audience_gender_age", "audience_locale"]
    else:
        metrics = [
            "impressions",
            "reach",
            "profile_views",
            "website_clicks",
            "email_contacts",
            "get_directions_clicks",
            "phone_call_clicks",
            "text_message_clicks",
        ]

    # Map period to API parameter
    period_map = {
        "day": "day",
        "week": "week",
        "days_28": "days_28",
        "lifetime": "lifetime",
    }
    api_period = period_map.get(period, "day")

    result = api_request(
        f"{ig_id}/insights",
        params={
            "metric": ",".join(metrics),
            "period": api_period,
        }
    )

    insights = result.get("data", [])

    if not insights:
        return f"No insights available for period: {period}"

    output_lines = [f"Instagram Profile Insights ({period}):\n"]

    for insight in insights:
        name = insight.get("name", "unknown")
        title = insight.get("title", name)
        description = insight.get("description", "")
        values = insight.get("values", [])

        # Format the metric name nicely
        display_name = title or name.replace("_", " ").title()

        if values:
            value = values[0].get("value", 0)

            # Handle complex values (like demographics)
            if isinstance(value, dict):
                output_lines.append(f"\n{display_name}:")
                for k, v in sorted(value.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0)[:10]:
                    output_lines.append(f"  - {k}: {v:,}" if isinstance(v, int) else f"  - {k}: {v}")
            else:
                output_lines.append(f"{display_name}: {value:,}" if isinstance(value, int) else f"{display_name}: {value}")

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_media_insights(media_id: str) -> str:
    """Get insights for a specific post.

    Args:
        media_id: The Instagram media ID

    Returns:
        Post insights including reach, impressions, engagement, saves, shares
    """
    # First, get the media type to determine which metrics are available
    media_result = api_request(
        media_id,
        params={"fields": "media_type"}
    )
    media_type = media_result.get("media_type", "IMAGE")

    # Define metrics based on media type
    if media_type == "VIDEO" or media_type == "REELS":
        metrics = [
            "impressions",
            "reach",
            "likes",
            "comments",
            "shares",
            "saved",
            "plays",
            "total_interactions",
        ]
    elif media_type == "CAROUSEL_ALBUM":
        metrics = [
            "carousel_album_impressions",
            "carousel_album_reach",
            "carousel_album_engagement",
            "carousel_album_saved",
        ]
    else:  # IMAGE
        metrics = [
            "impressions",
            "reach",
            "likes",
            "comments",
            "shares",
            "saved",
            "total_interactions",
        ]

    result = api_request(
        f"{media_id}/insights",
        params={
            "metric": ",".join(metrics),
        }
    )

    insights = result.get("data", [])

    if not insights:
        return f"No insights available for media {media_id}"

    output_lines = [f"Media Insights for {media_id} ({media_type}):\n"]

    for insight in insights:
        name = insight.get("name", "unknown")
        title = insight.get("title", name)
        values = insight.get("values", [])

        display_name = title or name.replace("_", " ").replace("carousel album ", "").title()

        if values:
            value = values[0].get("value", 0)
            output_lines.append(f"{display_name}: {value:,}" if isinstance(value, int) else f"{display_name}: {value}")

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_story_insights(story_id: str) -> str:
    """Get insights for a specific story.

    Note: Story insights are only available while the story is active (24 hours).

    Args:
        story_id: The Instagram story media ID

    Returns:
        Story insights including reach, impressions, replies, taps
    """
    metrics = [
        "impressions",
        "reach",
        "replies",
        "taps_forward",
        "taps_back",
        "exits",
    ]

    result = api_request(
        f"{story_id}/insights",
        params={
            "metric": ",".join(metrics),
        }
    )

    insights = result.get("data", [])

    if not insights:
        return f"No insights available for story {story_id}. Story insights are only available for 24 hours."

    output_lines = [f"Story Insights for {story_id}:\n"]

    for insight in insights:
        name = insight.get("name", "unknown")
        title = insight.get("title", name)
        values = insight.get("values", [])

        display_name = title or name.replace("_", " ").title()

        if values:
            value = values[0].get("value", 0)
            output_lines.append(f"{display_name}: {value:,}" if isinstance(value, int) else f"{display_name}: {value}")

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_audience_demographics() -> str:
    """Get audience demographics for your Instagram account.

    Returns breakdown by:
    - Country
    - City
    - Age and gender
    - Locale (language)

    Note: This data is only available if you have at least 100 followers.

    Returns:
        Audience demographic breakdown
    """
    ig_id = get_instagram_account_id()

    metrics = [
        "audience_city",
        "audience_country",
        "audience_gender_age",
        "audience_locale",
    ]

    result = api_request(
        f"{ig_id}/insights",
        params={
            "metric": ",".join(metrics),
            "period": "lifetime",
        }
    )

    insights = result.get("data", [])

    if not insights:
        return "Audience demographics not available. You need at least 100 followers."

    output_lines = ["Instagram Audience Demographics:\n"]

    for insight in insights:
        name = insight.get("name", "")
        title = insight.get("title", name)
        values = insight.get("values", [])

        if not values:
            continue

        value = values[0].get("value", {})
        if not value:
            continue

        # Format section header
        section_name = {
            "audience_city": "Top Cities",
            "audience_country": "Top Countries",
            "audience_gender_age": "Age & Gender",
            "audience_locale": "Top Languages",
        }.get(name, title)

        output_lines.append(f"\n{section_name}:")

        # Sort by value (descending) and show top 10
        sorted_items = sorted(value.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0)

        for k, v in sorted_items[:10]:
            if name == "audience_gender_age":
                # Format gender.age as "F 25-34: 15%"
                parts = k.split(".")
                if len(parts) == 2:
                    gender = "Female" if parts[0] == "F" else "Male" if parts[0] == "M" else parts[0]
                    output_lines.append(f"  - {gender} {parts[1]}: {v:,}")
                else:
                    output_lines.append(f"  - {k}: {v:,}")
            else:
                output_lines.append(f"  - {k}: {v:,}")

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_online_followers() -> str:
    """Get when your followers are most active online.

    Returns hourly breakdown of follower activity for the past week.

    Note: This data is only available if you have at least 100 followers.

    Returns:
        Hourly breakdown of follower activity
    """
    ig_id = get_instagram_account_id()

    result = api_request(
        f"{ig_id}/insights",
        params={
            "metric": "online_followers",
            "period": "lifetime",
        }
    )

    insights = result.get("data", [])

    if not insights:
        return "Online followers data not available. You need at least 100 followers."

    output_lines = ["When Your Followers Are Online:\n"]

    for insight in insights:
        values = insight.get("values", [])

        if not values:
            continue

        value = values[0].get("value", {})
        if not value:
            continue

        # Value is a dict of hour -> count
        # Sort by hour
        for hour in sorted(value.keys(), key=int):
            count = value[hour]
            hour_formatted = f"{int(hour):02d}:00"
            bar = "#" * (count // 100)  # Simple bar chart
            output_lines.append(f"  {hour_formatted}: {count:,} {bar}")

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_content_performance(
    days: int = 30,
    limit: int = 10
) -> str:
    """Get performance summary of your recent content.

    Args:
        days: Look back period in days (default 30)
        limit: Number of top posts to show (default 10)

    Returns:
        Summary of content performance with top performing posts
    """
    ig_id = get_instagram_account_id()
    limit = min(max(1, limit), 25)

    # Get recent media
    result = api_request(
        f"{ig_id}/media",
        params={
            "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
            "limit": 50,  # Get more to filter by date
        }
    )

    media_items = result.get("data", [])

    if not media_items:
        return "No media found."

    # Filter by date and calculate engagement
    cutoff_date = datetime.now() - timedelta(days=days)
    filtered_items = []

    for item in media_items:
        timestamp = item.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if dt.replace(tzinfo=None) >= cutoff_date:
                    likes = item.get("like_count", 0)
                    comments = item.get("comments_count", 0)
                    item["engagement"] = likes + comments
                    filtered_items.append(item)
            except Exception:
                pass

    if not filtered_items:
        return f"No posts found in the last {days} days."

    # Sort by engagement
    filtered_items.sort(key=lambda x: x.get("engagement", 0), reverse=True)

    # Calculate totals
    total_likes = sum(item.get("like_count", 0) for item in filtered_items)
    total_comments = sum(item.get("comments_count", 0) for item in filtered_items)
    total_engagement = total_likes + total_comments

    # Count by type
    type_counts = {}
    for item in filtered_items:
        media_type = item.get("media_type", "UNKNOWN")
        type_counts[media_type] = type_counts.get(media_type, 0) + 1

    output_lines = [f"Content Performance (Last {days} Days):\n"]
    output_lines.append(f"Total Posts: {len(filtered_items)}")
    output_lines.append(f"Total Likes: {total_likes:,}")
    output_lines.append(f"Total Comments: {total_comments:,}")
    output_lines.append(f"Total Engagement: {total_engagement:,}")
    output_lines.append(f"Avg Engagement/Post: {total_engagement / len(filtered_items):.1f}")

    output_lines.append("\nBy Content Type:")
    for media_type, count in sorted(type_counts.items()):
        output_lines.append(f"  - {media_type}: {count}")

    output_lines.append(f"\nTop {min(limit, len(filtered_items))} Performing Posts:")

    for i, item in enumerate(filtered_items[:limit], 1):
        media_type = item.get("media_type", "")
        caption = item.get("caption", "(no caption)")[:50]
        if len(item.get("caption", "")) > 50:
            caption += "..."
        likes = item.get("like_count", 0)
        comments = item.get("comments_count", 0)
        media_id = item.get("id", "")

        output_lines.append(f"\n{i}. [{media_type}] {caption}")
        output_lines.append(f"   Likes: {likes:,} | Comments: {comments:,} | Total: {likes + comments:,}")
        output_lines.append(f"   ID: {media_id}")

    return "\n".join(output_lines)
