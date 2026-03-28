"""YouTube transcript tool for the ADK agent."""

import logging
import re
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats.

    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/v/VIDEO_ID

    Args:
        url: YouTube URL or video ID.

    Returns:
        The video ID string, or None if extraction failed.
    """
    # If it's already just a video ID (11 characters, alphanumeric + - and _)
    if re.match(r"^[\w-]{11}$", url):
        return url

    # Try various URL patterns
    patterns = [
        r"(?:youtube\.com\/watch\?v=)([\w-]{11})",
        r"(?:youtu\.be\/)([\w-]{11})",
        r"(?:youtube\.com\/embed\/)([\w-]{11})",
        r"(?:youtube\.com\/v\/)([\w-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def get_youtube_transcript(
    tool_context: ToolContext,  # noqa: ARG001
    video_url: str,
    language: str | None = None,
) -> dict[str, Any]:
    """Get the transcript from a YouTube video.

    Fetches the transcript/captions from a YouTube video using the
    youtube-transcript-api library. Supports multiple languages if available.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        video_url: YouTube video URL or video ID. Supports formats like:
            - https://www.youtube.com/watch?v=VIDEO_ID
            - https://youtu.be/VIDEO_ID
            - Just the video ID (11 characters)
        language: Preferred language code (e.g., "en", "es", "fr").
            If not specified, returns the first available transcript.

    Returns:
        A dictionary with status, transcript text, and metadata.
    """
    from youtube_transcript_api import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeTranscriptApi,
    )

    # Extract video ID from URL
    video_id = _extract_video_id(video_url)
    if not video_id:
        return {
            "status": "error",
            "message": f"Could not extract video ID from URL: {video_url}",
        }

    try:
        # Create API instance and get transcript list
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Find the appropriate transcript
        if language:
            transcript = transcript_list.find_transcript([language])
        else:
            # Get first available transcript
            transcript = next(iter(transcript_list))

        # Fetch the actual transcript data
        fetched = transcript.fetch()
        entries = fetched.to_raw_data()

        # Combine transcript entries into full text
        full_text = " ".join(entry["text"] for entry in entries)

        # Get metadata
        total_duration = sum(entry.get("duration", 0) for entry in entries)

        logger.info(
            f"Retrieved transcript for video {video_id}: {len(full_text)} chars"
        )

        return {
            "status": "success",
            "video_id": video_id,
            "transcript": full_text,
            "entry_count": len(entries),
            "duration_seconds": int(total_duration),
            "duration_minutes": round(total_duration / 60, 1),
            "language": transcript.language_code,
            "language_name": transcript.language,
            "is_generated": transcript.is_generated,
            "message": f"Retrieved transcript ({len(full_text)} characters, "
            f"{round(total_duration / 60, 1)} minutes)",
        }

    except VideoUnavailable:
        return {
            "status": "error",
            "message": f"Video {video_id} is unavailable or does not exist.",
        }
    except TranscriptsDisabled:
        return {
            "status": "error",
            "message": f"Transcripts are disabled for video {video_id}.",
        }
    except NoTranscriptFound:
        return {
            "status": "error",
            "message": f"No transcript found for video {video_id}"
            + (f" in language '{language}'." if language else "."),
        }
    except StopIteration:
        return {
            "status": "error",
            "message": f"No transcripts available for video {video_id}.",
        }
    except Exception as e:
        logger.exception(f"Failed to get transcript for video {video_id}")
        return {
            "status": "error",
            "message": f"Failed to retrieve transcript: {e}",
        }


__all__ = ["get_youtube_transcript"]
