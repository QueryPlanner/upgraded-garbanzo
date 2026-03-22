"""Agent lifecycle callback functions for monitoring and memory.

This module provides callback functions that execute at various stages of the
agent lifecycle. These callbacks enable comprehensive logging, session
memory persistence, and Telegram notifications for tool usage.
"""

import logging
from collections import defaultdict
from time import perf_counter
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool

logger = logging.getLogger(__name__)


def _coerce_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _llm_usage_token_counts(
    llm_response: LlmResponse,
) -> tuple[int | None, int | None, int | None]:
    """Token counts from ``LlmResponse.usage_metadata`` (Gemini-style fields)."""
    usage = llm_response.usage_metadata
    if usage is None:
        return None, None, None
    prompt = _coerce_non_negative_int(getattr(usage, "prompt_token_count", None))
    completion = _coerce_non_negative_int(
        getattr(usage, "candidates_token_count", None)
    )
    total = _coerce_non_negative_int(getattr(usage, "total_token_count", None))
    return prompt, completion, total


def _log_llm_call_metrics(
    target_logger: logging.Logger,
    *,
    agent_name: str,
    invocation_id: str,
    elapsed_s: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
) -> None:
    """Emit one INFO line with latency, token counts, and tokens per second."""
    parts: list[str] = [
        f"agent={agent_name!s}",
        f"invocation_id={invocation_id!s}",
    ]

    if elapsed_s is None:
        parts.append("duration_s=n/a")
    else:
        parts.append(f"duration_s={elapsed_s:.3f}")
        has_positive_duration = elapsed_s > 0.0
        if has_positive_duration and completion_tokens is not None:
            parts.append(
                f"output_tokens_per_s={completion_tokens / elapsed_s:.2f}",
            )
        if has_positive_duration and total_tokens is not None:
            parts.append(f"total_tokens_per_s={total_tokens / elapsed_s:.2f}")

    if prompt_tokens is not None:
        parts.append(f"prompt_tokens={prompt_tokens}")
    if completion_tokens is not None:
        parts.append(f"completion_tokens={completion_tokens}")
    if total_tokens is not None:
        parts.append(f"total_tokens={total_tokens}")

    target_logger.info("llm.metrics %s", " ".join(parts))


async def add_session_to_memory(callback_context: CallbackContext) -> None:
    """Automatically save completed sessions to memory bank.

    This callback checks if the invocation context has a memory service.
    If so, it saves the session to memory for future retrieval.

    Args:
        callback_context: The callback context with access to invocation context
    """
    logger.info("*** Starting add_session_to_memory callback ***")
    try:
        await callback_context.add_session_to_memory()
    except ValueError as e:
        logger.warning(e)
    except Exception as e:
        logger.warning(f"Failed to add session to memory: {type(e).__name__}: {e}")

    return None


class LoggingCallbacks:
    """Provides comprehensive logging callbacks for ADK agent lifecycle events.

    This class groups all agent lifecycle callback methods together and supports
    logger injection following the strategy pattern. All callbacks are
    non-intrusive and return None.

    Attributes:
        logger: Logger instance for recording agent lifecycle events.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """Initialize logging callbacks with optional logger.

        Args:
            logger: Optional logger instance. If not provided, creates one
                   using the module name.
        """
        if logger is None:
            logger = logging.getLogger(self.__class__.__module__)
        self.logger = logger
        self._llm_perf_starts: defaultdict[str, list[float]] = defaultdict(list)

    def before_agent(self, callback_context: CallbackContext) -> None:
        """Callback executed before agent processing begins.

        Args:
            callback_context (CallbackContext): Context containing agent name,
                invocation ID, state, and user content.
        """
        self.logger.info(
            f"*** Starting agent '{callback_context.agent_name}' "
            f"with invocation_id '{callback_context.invocation_id}' ***"
        )
        self.logger.debug(f"State keys: {callback_context.state.to_dict().keys()}")

        if user_content := callback_context.user_content:
            content_data = user_content.model_dump(exclude_none=True, mode="json")
            self.logger.debug(f"User Content: {content_data}")

        return None

    def after_agent(self, callback_context: CallbackContext) -> None:
        """Callback executed after agent processing completes.

        Args:
            callback_context (CallbackContext): Context containing agent name,
                invocation ID, state, and user content.
        """
        self.logger.info(
            f"*** Leaving agent '{callback_context.agent_name}' "
            f"with invocation_id '{callback_context.invocation_id}' ***"
        )
        self.logger.debug(f"State keys: {callback_context.state.to_dict().keys()}")

        if user_content := callback_context.user_content:
            content_data = user_content.model_dump(exclude_none=True, mode="json")
            self.logger.debug(f"User Content: {content_data}")

        return None

    def before_model(
        self,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> None:
        """Callback executed before LLM model invocation.

        Args:
            callback_context (CallbackContext): Context containing agent name,
                invocation ID, state, and user content.
            llm_request (LlmRequest): The request being sent to the LLM model
                containing message contents.
        """
        self.logger.info(
            f"*** Before LLM call for agent '{callback_context.agent_name}' "
            f"with invocation_id '{callback_context.invocation_id}' ***"
        )
        self.logger.debug(f"State keys: {callback_context.state.to_dict().keys()}")

        if user_content := callback_context.user_content:
            content_data = user_content.model_dump(exclude_none=True, mode="json")
            self.logger.debug(f"User Content: {content_data}")

        self.logger.debug(f"LLM request contains {len(llm_request.contents)} messages:")
        for i, content in enumerate(llm_request.contents, start=1):
            self.logger.debug(
                f"Content {i}: {content.model_dump(exclude_none=True, mode='json')}"
            )

        inv_id = callback_context.invocation_id
        self._llm_perf_starts[inv_id].append(perf_counter())

        return None

    def after_model(
        self,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> None:
        """Callback executed after LLM model responds.

        Args:
            callback_context (CallbackContext): Context containing agent name,
                invocation ID, state, and user content.
            llm_response (LlmResponse): The response received from the LLM model.
        """
        self.logger.info(
            f"*** After LLM call for agent '{callback_context.agent_name}' "
            f"with invocation_id '{callback_context.invocation_id}' ***"
        )
        self.logger.debug(f"State keys: {callback_context.state.to_dict().keys()}")

        if user_content := callback_context.user_content:
            content_data = user_content.model_dump(exclude_none=True, mode="json")
            self.logger.debug(f"User Content: {content_data}")

        if llm_content := llm_response.content:
            response_data = llm_content.model_dump(exclude_none=True, mode="json")
            self.logger.debug(f"LLM response: {response_data}")

        inv_id = callback_context.invocation_id
        stack = self._llm_perf_starts.get(inv_id)
        elapsed_s: float | None = None
        if stack:
            t0 = stack.pop()
            elapsed_s = perf_counter() - t0
            if not stack:
                del self._llm_perf_starts[inv_id]
        else:
            self.logger.debug(
                "llm.metrics missing duration (after_model without before_model): "
                "invocation_id=%s",
                inv_id,
            )

        prompt_t, completion_t, total_t = _llm_usage_token_counts(llm_response)
        _log_llm_call_metrics(
            self.logger,
            agent_name=callback_context.agent_name,
            invocation_id=inv_id,
            elapsed_s=elapsed_s,
            prompt_tokens=prompt_t,
            completion_tokens=completion_t,
            total_tokens=total_t,
        )

        return None

    def before_tool(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> None:
        """Callback executed before tool invocation.

        Args:
            tool (BaseTool): The tool being invoked.
            args (dict[str, Any]): Arguments being passed to the tool.
            tool_context (ToolContext): Context containing agent name, invocation ID,
                state, user content, and event actions.
        """
        self.logger.info(
            f"*** Before invoking tool '{tool.name}' in agent "
            f"'{tool_context.agent_name}' with invocation_id "
            f"'{tool_context.invocation_id}' ***"
        )
        self.logger.debug(f"State keys: {tool_context.state.to_dict().keys()}")

        if content := tool_context.user_content:
            self.logger.debug(
                f"User Content: {content.model_dump(exclude_none=True, mode='json')}"
            )

        actions_data = tool_context.actions.model_dump(exclude_none=True, mode="json")
        self.logger.debug(f"EventActions: {actions_data}")
        self.logger.debug(f"args: {args}")

        return None

    def after_tool(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: dict[str, Any],
    ) -> None:
        """Callback executed after tool invocation completes.

        Args:
            tool (BaseTool): The tool that was invoked.
            args (dict[str, Any]): Arguments that were passed to the tool.
            tool_context (ToolContext): Context containing agent name, invocation ID,
                state, user content, and event actions.
            tool_response (dict[str, Any]): The response returned by the tool.
        """
        self.logger.info(
            f"*** After invoking tool '{tool.name}' in agent "
            f"'{tool_context.agent_name}' with invocation_id "
            f"'{tool_context.invocation_id}' ***"
        )
        self.logger.debug(f"State keys: {tool_context.state.to_dict().keys()}")

        if content := tool_context.user_content:
            self.logger.debug(
                f"User Content: {content.model_dump(exclude_none=True, mode='json')}"
            )

        actions_data = tool_context.actions.model_dump(exclude_none=True, mode="json")
        self.logger.debug(f"EventActions: {actions_data}")
        self.logger.debug(f"args: {args}")
        self.logger.debug(f"Tool response: {tool_response}")

        return None


async def notify_tool_call(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> None:
    """Log tool invocation and send Telegram notification.

    This async callback provides logging for tool calls and notifies users
    in real-time when the agent invokes a tool.

    Args:
        tool: The tool being invoked.
        args: Arguments being passed to the tool.
        tool_context: Context containing agent name, invocation ID,
            state, user content, and event actions.
    """
    from .telegram.notifications import get_notification_service

    # Log tool invocation (same as LoggingCallbacks.before_tool)
    logger.info(
        f"*** Before invoking tool '{tool.name}' in agent "
        f"'{tool_context.agent_name}' with invocation_id "
        f"'{tool_context.invocation_id}' ***"
    )
    logger.debug(f"State keys: {tool_context.state.to_dict().keys()}")

    if content := tool_context.user_content:
        logger.debug(
            f"User Content: {content.model_dump(exclude_none=True, mode='json')}"
        )

    actions_data = tool_context.actions.model_dump(exclude_none=True, mode="json")
    logger.debug(f"EventActions: {actions_data}")
    logger.debug(f"args: {args}")

    # Get user_id from session state (set by TelegramHandler)
    user_id = tool_context.state.get("user_id")
    if not user_id:
        # Log at INFO level to catch this issue in production
        logger.info(
            f"No user_id in session state for tool '{tool.name}', "
            f"session keys: {list(tool_context.state.to_dict().keys())}, "
            "skipping tool notification"
        )
        return None

    try:
        notification_service = get_notification_service()
        await notification_service.notify_tool_call(
            chat_id=user_id,
            tool_name=tool.name,
            args=args if args else None,
        )
    except Exception:
        logger.exception("Failed to send tool notification")

    return None
