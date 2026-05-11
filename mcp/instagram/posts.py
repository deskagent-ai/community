# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Instagram MCP - Posts Module
============================
Tools for creating and managing Instagram posts, stories, and reels.
"""

from instagram.base import (
    mcp, instagram_tool, require_auth,
    api_request, get_instagram_account_id, get_credentials
)
from _mcp_api import mcp_log


@mcp.tool()
@instagram_tool
@require_auth
def instagram_create_image_post(
    image_url: str,
    caption: str = "",
    location_id: str = None
) -> str:
    """Create a new Instagram image post.

    This is a two-step process:
    1. Create a media container with the image
    2. Publish the container

    Args:
        image_url: Public URL to the image (must be accessible by Instagram servers)
        caption: Post caption (optional, max 2200 characters)
        location_id: Facebook Location Page ID (optional)

    Returns:
        Post creation result with media ID and permalink

    Note:
        - Image must be publicly accessible via HTTPS
        - Supported formats: JPEG, PNG
        - Recommended size: 1080x1080 (square), 1080x1350 (portrait), 1080x566 (landscape)
        - Maximum file size: 8MB
    """
    ig_id = get_instagram_account_id()

    # Step 1: Create media container
    mcp_log("[Instagram] Creating image container for post...")

    container_params = {
        "image_url": image_url,
        "caption": caption[:2200] if caption else "",
    }

    if location_id:
        container_params["location_id"] = location_id

    container_result = api_request(
        f"{ig_id}/media",
        method="POST",
        params=container_params
    )

    container_id = container_result.get("id")
    if not container_id:
        return "ERROR: Failed to create media container"

    mcp_log(f"[Instagram] Container created: {container_id}, publishing...")

    # Step 2: Publish the container
    publish_result = api_request(
        f"{ig_id}/media_publish",
        method="POST",
        params={"creation_id": container_id}
    )

    media_id = publish_result.get("id")
    if not media_id:
        return f"ERROR: Failed to publish post. Container ID: {container_id}"

    # Get the published post details
    try:
        post_details = api_request(
            media_id,
            params={"fields": "id,permalink,timestamp,media_type"}
        )
        permalink = post_details.get("permalink", "")
    except Exception:
        permalink = ""

    return f"""Post created successfully!

Media ID: {media_id}
URL: {permalink}

The post is now live on your Instagram profile."""


@mcp.tool()
@instagram_tool
@require_auth
def instagram_create_carousel_post(
    image_urls: list[str],
    caption: str = "",
    location_id: str = None
) -> str:
    """Create a carousel post with multiple images.

    Args:
        image_urls: List of public URLs to images (2-10 images)
        caption: Post caption (optional, max 2200 characters)
        location_id: Facebook Location Page ID (optional)

    Returns:
        Post creation result with media ID and permalink

    Note:
        - All images must be publicly accessible via HTTPS
        - Minimum 2 images, maximum 10 images
        - All images should have consistent aspect ratios
    """
    if not image_urls or len(image_urls) < 2:
        return "ERROR: Carousel posts require at least 2 images"

    if len(image_urls) > 10:
        return "ERROR: Carousel posts can have maximum 10 images"

    ig_id = get_instagram_account_id()

    # Step 1: Create containers for each image
    mcp_log(f"[Instagram] Creating {len(image_urls)} image containers for carousel...")

    children_ids = []
    for i, url in enumerate(image_urls):
        container_result = api_request(
            f"{ig_id}/media",
            method="POST",
            params={
                "image_url": url,
                "is_carousel_item": "true",
            }
        )

        child_id = container_result.get("id")
        if not child_id:
            return f"ERROR: Failed to create container for image {i + 1}"

        children_ids.append(child_id)
        mcp_log(f"[Instagram] Created container {i + 1}/{len(image_urls)}: {child_id}")

    # Step 2: Create carousel container
    mcp_log("[Instagram] Creating carousel container...")

    carousel_params = {
        "media_type": "CAROUSEL",
        "caption": caption[:2200] if caption else "",
        "children": ",".join(children_ids),
    }

    if location_id:
        carousel_params["location_id"] = location_id

    carousel_result = api_request(
        f"{ig_id}/media",
        method="POST",
        params=carousel_params
    )

    carousel_id = carousel_result.get("id")
    if not carousel_id:
        return "ERROR: Failed to create carousel container"

    # Step 3: Publish the carousel
    mcp_log(f"[Instagram] Publishing carousel: {carousel_id}...")

    publish_result = api_request(
        f"{ig_id}/media_publish",
        method="POST",
        params={"creation_id": carousel_id}
    )

    media_id = publish_result.get("id")
    if not media_id:
        return f"ERROR: Failed to publish carousel. Container ID: {carousel_id}"

    # Get the published post details
    try:
        post_details = api_request(
            media_id,
            params={"fields": "id,permalink,timestamp,media_type"}
        )
        permalink = post_details.get("permalink", "")
    except Exception:
        permalink = ""

    return f"""Carousel post created successfully!

Media ID: {media_id}
Images: {len(image_urls)}
URL: {permalink}

The carousel is now live on your Instagram profile."""


@mcp.tool()
@instagram_tool
@require_auth
def instagram_create_video_post(
    video_url: str,
    caption: str = "",
    cover_url: str = None,
    share_to_feed: bool = True,
    location_id: str = None
) -> str:
    """Create a new Instagram video post (Reel).

    Args:
        video_url: Public URL to the video (must be accessible by Instagram servers)
        caption: Post caption (optional, max 2200 characters)
        cover_url: Public URL to custom thumbnail image (optional)
        share_to_feed: Whether to share to feed (default True)
        location_id: Facebook Location Page ID (optional)

    Returns:
        Post creation result with media ID and permalink

    Note:
        - Video must be publicly accessible via HTTPS
        - Supported format: MP4 (H.264 codec)
        - Duration: 3 seconds to 15 minutes for Reels
        - Recommended aspect ratio: 9:16 (vertical)
        - Maximum file size: 1GB
    """
    ig_id = get_instagram_account_id()

    # Step 1: Create video container
    mcp_log("[Instagram] Creating video container for Reel...")

    container_params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200] if caption else "",
        "share_to_feed": str(share_to_feed).lower(),
    }

    if cover_url:
        container_params["cover_url"] = cover_url

    if location_id:
        container_params["location_id"] = location_id

    container_result = api_request(
        f"{ig_id}/media",
        method="POST",
        params=container_params
    )

    container_id = container_result.get("id")
    if not container_id:
        return "ERROR: Failed to create video container"

    mcp_log(f"[Instagram] Container created: {container_id}, checking status...")

    # Step 2: Wait for video processing (videos take time to process)
    import time
    max_attempts = 30
    for attempt in range(max_attempts):
        status_result = api_request(
            container_id,
            params={"fields": "status_code,status"}
        )

        status_code = status_result.get("status_code")
        status = status_result.get("status", "")

        mcp_log(f"[Instagram] Video status ({attempt + 1}/{max_attempts}): {status_code}")

        if status_code == "FINISHED":
            break
        elif status_code == "ERROR":
            return f"ERROR: Video processing failed: {status}"
        elif status_code in ["EXPIRED", "PUBLISHED"]:
            return f"ERROR: Unexpected status: {status_code}"

        time.sleep(10)  # Wait 10 seconds between checks
    else:
        return "ERROR: Video processing timeout. The video may still be processing."

    # Step 3: Publish the container
    mcp_log(f"[Instagram] Publishing video: {container_id}...")

    publish_result = api_request(
        f"{ig_id}/media_publish",
        method="POST",
        params={"creation_id": container_id}
    )

    media_id = publish_result.get("id")
    if not media_id:
        return f"ERROR: Failed to publish video. Container ID: {container_id}"

    # Get the published post details
    try:
        post_details = api_request(
            media_id,
            params={"fields": "id,permalink,timestamp,media_type"}
        )
        permalink = post_details.get("permalink", "")
    except Exception:
        permalink = ""

    return f"""Video/Reel created successfully!

Media ID: {media_id}
URL: {permalink}
Shared to feed: {share_to_feed}

The Reel is now live on your Instagram profile."""


@mcp.tool()
@instagram_tool
@require_auth
def instagram_create_story(
    media_url: str,
    media_type: str = "image"
) -> str:
    """Create an Instagram Story.

    Args:
        media_url: Public URL to the image or video
        media_type: "image" or "video" (default "image")

    Returns:
        Story creation result with media ID

    Note:
        - Stories disappear after 24 hours
        - Recommended aspect ratio: 9:16 (1080x1920)
        - Videos should be 1-60 seconds
    """
    ig_id = get_instagram_account_id()

    mcp_log(f"[Instagram] Creating story ({media_type})...")

    # Create story container
    if media_type.lower() == "video":
        container_params = {
            "media_type": "STORIES",
            "video_url": media_url,
        }
    else:
        container_params = {
            "media_type": "STORIES",
            "image_url": media_url,
        }

    container_result = api_request(
        f"{ig_id}/media",
        method="POST",
        params=container_params
    )

    container_id = container_result.get("id")
    if not container_id:
        return "ERROR: Failed to create story container"

    # For videos, wait for processing
    if media_type.lower() == "video":
        import time
        max_attempts = 30
        for attempt in range(max_attempts):
            status_result = api_request(
                container_id,
                params={"fields": "status_code"}
            )

            status_code = status_result.get("status_code")
            if status_code == "FINISHED":
                break
            elif status_code == "ERROR":
                return "ERROR: Video processing failed"

            time.sleep(5)
        else:
            return "ERROR: Video processing timeout"

    # Publish the story
    mcp_log(f"[Instagram] Publishing story: {container_id}...")

    publish_result = api_request(
        f"{ig_id}/media_publish",
        method="POST",
        params={"creation_id": container_id}
    )

    media_id = publish_result.get("id")
    if not media_id:
        return f"ERROR: Failed to publish story. Container ID: {container_id}"

    return f"""Story created successfully!

Media ID: {media_id}
Type: {media_type}

The story is now live and will be visible for 24 hours."""


@mcp.tool()
@instagram_tool
@require_auth
def instagram_check_container_status(container_id: str) -> str:
    """Check the status of a media container.

    Useful for checking if a video is still processing before publishing.

    Args:
        container_id: The container ID from create_video_post

    Returns:
        Container status information
    """
    result = api_request(
        container_id,
        params={"fields": "id,status_code,status"}
    )

    status_code = result.get("status_code", "UNKNOWN")
    status = result.get("status", "")

    status_descriptions = {
        "EXPIRED": "Container expired (not published within 24 hours)",
        "ERROR": f"Processing failed: {status}",
        "FINISHED": "Ready to publish",
        "IN_PROGRESS": "Still processing (video/reel)",
        "PUBLISHED": "Already published",
    }

    description = status_descriptions.get(status_code, f"Unknown status: {status_code}")

    return f"""Container Status: {status_code}

Container ID: {container_id}
Status: {description}

{"Ready to publish with instagram_create_video_post or instagram_create_story." if status_code == "FINISHED" else ""}"""
