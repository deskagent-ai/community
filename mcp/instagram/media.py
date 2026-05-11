# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Instagram MCP - Media Module
============================
Tools for reading and managing Instagram media, comments, and mentions.
"""

from instagram.base import (
    mcp, instagram_tool, require_auth,
    api_request, get_instagram_account_id, get_credentials,
    format_media_item, format_comment
)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_media(limit: int = 10) -> str:
    """Get recent media posts from your Instagram account.

    Args:
        limit: Maximum number of posts to return (default 10, max 50)

    Returns:
        List of recent posts with captions, likes, comments, and IDs
    """
    ig_id = get_instagram_account_id()
    limit = min(max(1, limit), 50)

    result = api_request(
        f"{ig_id}/media",
        params={
            "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
            "limit": limit,
        }
    )

    media_items = result.get("data", [])

    if not media_items:
        return "No media found on your Instagram account."

    output_lines = [f"Recent Instagram Media ({len(media_items)} posts):\n"]

    for item in media_items:
        output_lines.append(format_media_item(item))
        output_lines.append("-" * 40)

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_media_details(media_id: str) -> str:
    """Get detailed information about a specific media post.

    Args:
        media_id: The Instagram media ID

    Returns:
        Detailed post information including engagement metrics
    """
    result = api_request(
        media_id,
        params={
            "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count,is_comment_enabled,owner",
        }
    )

    media_type = result.get("media_type", "UNKNOWN")
    timestamp = result.get("timestamp", "")
    caption = result.get("caption", "(no caption)")
    likes = result.get("like_count", 0)
    comments = result.get("comments_count", 0)
    permalink = result.get("permalink", "")
    media_url = result.get("media_url", "")
    thumbnail = result.get("thumbnail_url", "")
    comments_enabled = result.get("is_comment_enabled", True)

    # Format timestamp
    if timestamp:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    return f"""Instagram Media Details

ID: {media_id}
Type: {media_type}
Posted: {timestamp}
URL: {permalink}

Caption:
{caption}

Engagement:
- Likes: {likes:,}
- Comments: {comments:,}
- Comments enabled: {comments_enabled}

Media URL: {media_url or thumbnail or "(not available)"}"""


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_comments(media_id: str, limit: int = 20) -> str:
    """Get comments on a specific media post.

    Args:
        media_id: The Instagram media ID
        limit: Maximum number of comments to return (default 20, max 50)

    Returns:
        List of comments with usernames, text, and timestamps
    """
    limit = min(max(1, limit), 50)

    result = api_request(
        f"{media_id}/comments",
        params={
            "fields": "id,text,username,timestamp,like_count,replies{id,text,username,timestamp,like_count}",
            "limit": limit,
        }
    )

    comments = result.get("data", [])

    if not comments:
        return f"No comments found on media {media_id}."

    output_lines = [f"Comments on media {media_id} ({len(comments)} comments):\n"]

    for comment in comments:
        output_lines.append(format_comment(comment))

        # Show replies if any
        replies = comment.get("replies", {}).get("data", [])
        for reply in replies:
            output_lines.append(f"  -> {format_comment(reply)}")

        output_lines.append("")

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_reply_comment(comment_id: str, message: str) -> str:
    """Reply to a comment on your post.

    Args:
        comment_id: The comment ID to reply to
        message: The reply text

    Returns:
        Reply creation result
    """
    if not message or not message.strip():
        return "ERROR: Reply message cannot be empty"

    result = api_request(
        f"{comment_id}/replies",
        method="POST",
        params={"message": message.strip()}
    )

    reply_id = result.get("id")
    if not reply_id:
        return "ERROR: Failed to post reply"

    return f"""Reply posted successfully!

Reply ID: {reply_id}
Message: {message}"""


@mcp.tool()
@instagram_tool
@require_auth
def instagram_delete_comment(comment_id: str) -> str:
    """Delete a comment on your post.

    Args:
        comment_id: The comment ID to delete

    Returns:
        Deletion confirmation
    """
    result = api_request(
        comment_id,
        method="DELETE"
    )

    if result.get("success"):
        return f"Comment {comment_id} deleted successfully."
    else:
        return f"Failed to delete comment {comment_id}."


@mcp.tool()
@instagram_tool
@require_auth
def instagram_hide_comment(comment_id: str, hide: bool = True) -> str:
    """Hide or unhide a comment on your post.

    Args:
        comment_id: The comment ID
        hide: True to hide, False to unhide (default True)

    Returns:
        Update confirmation
    """
    result = api_request(
        comment_id,
        method="POST",
        params={"hide": str(hide).lower()}
    )

    if result.get("success"):
        action = "hidden" if hide else "unhidden"
        return f"Comment {comment_id} {action} successfully."
    else:
        return f"Failed to update comment visibility."


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_mentions(limit: int = 10) -> str:
    """Get posts where you are @mentioned.

    Args:
        limit: Maximum number of mentions to return (default 10)

    Returns:
        List of posts mentioning your account
    """
    ig_id = get_instagram_account_id()
    limit = min(max(1, limit), 50)

    result = api_request(
        f"{ig_id}/tags",
        params={
            "fields": "id,caption,media_type,permalink,timestamp,username,like_count,comments_count",
            "limit": limit,
        }
    )

    mentions = result.get("data", [])

    if not mentions:
        return "No mentions found."

    output_lines = [f"Recent Mentions ({len(mentions)}):\n"]

    for item in mentions:
        username = item.get("username", "unknown")
        output_lines.append(f"By @{username}:")
        output_lines.append(format_media_item(item))
        output_lines.append("-" * 40)

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_tagged_media(limit: int = 10) -> str:
    """Get posts where you are tagged (not just @mentioned).

    This shows posts where your account is tagged in the media itself.

    Args:
        limit: Maximum number of tagged posts to return (default 10)

    Returns:
        List of posts where you are tagged
    """
    ig_id = get_instagram_account_id()
    limit = min(max(1, limit), 50)

    result = api_request(
        f"{ig_id}/tags",
        params={
            "fields": "id,caption,media_type,permalink,timestamp,username,like_count,comments_count",
            "limit": limit,
        }
    )

    tagged = result.get("data", [])

    if not tagged:
        return "No tagged posts found."

    output_lines = [f"Tagged Posts ({len(tagged)}):\n"]

    for item in tagged:
        username = item.get("username", "unknown")
        output_lines.append(f"By @{username}:")
        output_lines.append(format_media_item(item))
        output_lines.append("-" * 40)

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_search_hashtag(hashtag: str, limit: int = 10) -> str:
    """Search for recent media with a specific hashtag.

    Note: This requires the instagram_basic scope and only returns
    public media using the hashtag.

    Args:
        hashtag: The hashtag to search (without #)
        limit: Maximum number of posts to return (default 10)

    Returns:
        List of recent posts with the hashtag
    """
    # Remove # if present
    hashtag = hashtag.lstrip("#").strip()

    if not hashtag:
        return "ERROR: Hashtag cannot be empty"

    ig_id = get_instagram_account_id()
    limit = min(max(1, limit), 30)  # Hashtag search has lower limits

    # First, get the hashtag ID
    hashtag_result = api_request(
        "ig_hashtag_search",
        params={
            "user_id": ig_id,
            "q": hashtag,
        }
    )

    hashtag_data = hashtag_result.get("data", [])
    if not hashtag_data:
        return f"Hashtag #{hashtag} not found."

    hashtag_id = hashtag_data[0].get("id")

    # Get recent media with this hashtag
    media_result = api_request(
        f"{hashtag_id}/recent_media",
        params={
            "user_id": ig_id,
            "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
            "limit": limit,
        }
    )

    media_items = media_result.get("data", [])

    if not media_items:
        return f"No recent posts found with #{hashtag}."

    output_lines = [f"Recent Posts with #{hashtag} ({len(media_items)} posts):\n"]

    for item in media_items:
        output_lines.append(format_media_item(item))
        output_lines.append("-" * 40)

    return "\n".join(output_lines)


@mcp.tool()
@instagram_tool
@require_auth
def instagram_get_stories() -> str:
    """Get your current active stories.

    Returns:
        List of your current stories (visible for 24 hours)
    """
    ig_id = get_instagram_account_id()

    result = api_request(
        f"{ig_id}/stories",
        params={
            "fields": "id,media_type,media_url,timestamp,permalink",
        }
    )

    stories = result.get("data", [])

    if not stories:
        return "No active stories found."

    output_lines = [f"Active Stories ({len(stories)}):\n"]

    for story in stories:
        story_id = story.get("id", "")
        media_type = story.get("media_type", "UNKNOWN")
        timestamp = story.get("timestamp", "")
        permalink = story.get("permalink", "")

        # Format timestamp
        if timestamp:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        output_lines.append(f"[{media_type}] Posted: {timestamp}")
        output_lines.append(f"  ID: {story_id}")
        if permalink:
            output_lines.append(f"  URL: {permalink}")
        output_lines.append("")

    return "\n".join(output_lines)
