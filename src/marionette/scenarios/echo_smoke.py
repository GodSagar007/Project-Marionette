"""The echo-smoke scenario: the smallest scenario that exercises the full stack.

Purpose: validate the end-to-end loop (adapter → gateway → tool → trace → adapter)
against a real model with the simplest possible task. The agent is asked to use
the echo tool with a specific phrase; success means the trace records the agent
invoking echo with the right argument, the tool returning, and the agent ending
the conversation.

This is the only scenario in thread one. Future scenarios live as siblings here.
"""

from marionette.runner import Scenario
from marionette.tools.echo import EchoTool

ECHO_SMOKE = Scenario(
    id="echo-smoke",
    system_prompt=(
        "You are testing a tool-calling system. You have access to one tool: "
        "echo, which returns the text you give it. To complete the task, call "
        "echo exactly once with the text 'marionette is online', then briefly "
        "confirm the result. Do not call any tool more than once."
    ),
    initial_user_message=(
        "Please use the echo tool to send the phrase 'marionette is online'."
    ),
    tools=[EchoTool()],
)
