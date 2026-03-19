"""Tests for YouTube transcript tool."""

from unittest.mock import MagicMock, patch

from conftest import MockState, MockToolContext

from agent.tools import _extract_video_id, get_youtube_transcript


class TestExtractVideoId:
    """Tests for _extract_video_id helper function."""

    def test_extract_from_standard_url(self) -> None:
        """Test extracting video ID from standard YouTube URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = _extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_from_short_url(self) -> None:
        """Test extracting video ID from short youtu.be URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        result = _extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_from_embed_url(self) -> None:
        """Test extracting video ID from embed URL."""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        result = _extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_from_raw_video_id(self) -> None:
        """Test that raw video ID is returned as-is."""
        video_id = "dQw4w9WgXcQ"
        result = _extract_video_id(video_id)
        assert result == "dQw4w9WgXcQ"

    def test_extract_returns_none_for_invalid_url(self) -> None:
        """Test that invalid URL returns None."""
        url = "https://example.com/not-a-youtube-video"
        result = _extract_video_id(url)
        assert result is None


class TestGetYoutubeTranscript:
    """Tests for get_youtube_transcript tool."""

    def test_invalid_url_returns_error(self) -> None:
        """Test that invalid URL returns error status."""
        state = MockState({})
        tool_context = MockToolContext(state=state)

        result = get_youtube_transcript(
            tool_context,  # type: ignore
            video_url="https://example.com/not-youtube",
        )

        assert result["status"] == "error"
        assert "Could not extract video ID" in result["message"]

    def test_successful_transcript_retrieval(self) -> None:
        """Test successful transcript retrieval."""
        # Setup mock transcript
        mock_transcript = MagicMock()
        mock_transcript.language_code = "en"
        mock_transcript.language = "English"
        mock_transcript.is_generated = True
        mock_fetched = MagicMock()
        mock_fetched.to_raw_data.return_value = [
            {"text": "Hello", "duration": 2.0},
            {"text": "world", "duration": 1.5},
        ]
        mock_transcript.fetch.return_value = mock_fetched

        # Setup mock transcript list
        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__ = lambda self: iter([mock_transcript])

        # Setup mock API instance
        mock_api = MagicMock()
        mock_api.list.return_value = mock_transcript_list

        with patch.dict(
            "sys.modules",
            {
                "youtube_transcript_api": MagicMock(
                    YouTubeTranscriptApi=MagicMock(return_value=mock_api),
                    VideoUnavailable=Exception,
                    TranscriptsDisabled=Exception,
                    NoTranscriptFound=Exception,
                ),
            },
        ):
            state = MockState({})
            tool_context = MockToolContext(state=state)

            result = get_youtube_transcript(
                tool_context,  # type: ignore
                video_url="dQw4w9WgXcQ",
            )

            assert result["status"] == "success"
            assert result["transcript"] == "Hello world"
            assert result["entry_count"] == 2
            assert result["video_id"] == "dQw4w9WgXcQ"
            assert result["language"] == "en"

    def test_transcript_with_language(self) -> None:
        """Test transcript retrieval with specific language."""
        # Setup mock transcript
        mock_transcript = MagicMock()
        mock_transcript.language_code = "es"
        mock_transcript.language = "Spanish"
        mock_transcript.is_generated = False
        mock_fetched = MagicMock()
        mock_fetched.to_raw_data.return_value = [
            {"text": "Hola", "duration": 1.0},
        ]
        mock_transcript.fetch.return_value = mock_fetched

        # Setup mock transcript list
        mock_transcript_list = MagicMock()
        mock_transcript_list.find_transcript.return_value = mock_transcript

        # Setup mock API instance
        mock_api = MagicMock()
        mock_api.list.return_value = mock_transcript_list

        with patch.dict(
            "sys.modules",
            {
                "youtube_transcript_api": MagicMock(
                    YouTubeTranscriptApi=MagicMock(return_value=mock_api),
                    VideoUnavailable=Exception,
                    TranscriptsDisabled=Exception,
                    NoTranscriptFound=Exception,
                ),
            },
        ):
            state = MockState({})
            tool_context = MockToolContext(state=state)

            result = get_youtube_transcript(
                tool_context,  # type: ignore
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                language="es",
            )

            assert result["status"] == "success"
            assert result["language"] == "es"
            mock_transcript_list.find_transcript.assert_called_once_with(["es"])

    def test_video_unavailable_error(self) -> None:
        """Test handling of error during transcript fetch."""
        from youtube_transcript_api import VideoUnavailable

        mock_api = MagicMock()
        mock_api.list.side_effect = VideoUnavailable("video_id")

        with patch.dict(
            "sys.modules",
            {
                "youtube_transcript_api": MagicMock(
                    YouTubeTranscriptApi=MagicMock(return_value=mock_api),
                    VideoUnavailable=VideoUnavailable,
                    TranscriptsDisabled=Exception,
                    NoTranscriptFound=Exception,
                ),
            },
        ):
            state = MockState({})
            tool_context = MockToolContext(state=state)

            result = get_youtube_transcript(
                tool_context,  # type: ignore
                video_url="dQw4w9WgXcQ",
            )

            assert result["status"] == "error"
            assert "unavailable" in result["message"].lower()
