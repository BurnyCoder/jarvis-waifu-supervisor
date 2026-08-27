# LLM-generated feedback messages (requirement 4): the words spoken to the
# user are never canned — a text model writes each good-luck, nudge, praise,
# break acknowledgment, and temporary-access transition from live context.
# One shared generate() path = no duplicated call code.
# Responses API text generation: https://github.com/openai/openai-python

import logging

from deepwork.storage import ResultsStore

log = logging.getLogger(__name__)

# One template per message kind; {placeholders} are filled by build_prompt.
# Short spoken output, but RICHLY grounded input: every template ends with
# the {session_context} block (topic, elapsed time, streak, allowance,
# recent concrete observations) so the voice can reference real specifics.
_CONTEXT_SUFFIX = (
    "\n\nFull session context — ground what you say in these specifics:\n"
    "{session_context}"
)

_TEMPLATES = {
    "good_luck": (
        "A user is starting a deep-work session on the topic: {topic!r}. "
        "Write one short, warm, motivating spoken sentence wishing them good "
        "luck on that topic. No emojis, it will be read aloud."
    ),
    "nudge": (
        "A user working on {topic!r} was just seen being unproductive. The "
        "monitor's judgment: {reason!r}. What was concretely on their screens: "
        "{observed!r}. Write one or two gentle, kind spoken sentences nudging "
        "them back to work without guilt-tripping — MENTION concretely what "
        "they were seen doing (name the site/app/content from the observation) "
        "so they know you actually saw it. No emojis, it will be read aloud."
    ),
    "praise": (
        "A user working on {topic!r} has stayed focused for 30 minutes "
        "straight. The monitor's judgment: {reason!r}. What was concretely on "
        "their screens: {observed!r}. Write one or two sincere spoken "
        "sentences congratulating them — name the focused work you saw them "
        "doing. No emojis, it will be read aloud."
    ),
    "agent_running": (
        "A user's AI coding agent just started working on their task, so "
        "they're free to relax or browse until it finishes — the monitor "
        "said: {reason!r}. Write one short, friendly spoken sentence telling "
        "them the agent is running and they can take it easy for a bit. "
        "No emojis, it will be read aloud."
    ),
    "agent_done": (
        "A user's AI coding agent has just FINISHED and is waiting for their "
        "review — the monitor said: {reason!r}. Non-task websites were just "
        "re-blocked; any website/app access groups explicitly required for "
        "the task remain available. Write one short, upbeat spoken sentence "
        "telling them the agent is done and it's time to come back and review "
        "its work. No emojis, it will be read aloud."
    ),
    "break_ack": (
        "A user is taking a {minutes}-minute break for: {purpose!r}. Write one "
        "short, friendly spoken sentence acknowledging the break and saying "
        "you'll see them back after it. No emojis, it will be read aloud."
    ),
    "break_end_ack": (
        "A user has ended their break for {purpose!r} after "
        "{charged_minutes} charged minute(s). Focus enforcement has resumed. "
        "Write one short, upbeat spoken sentence welcoming them back and "
        "encouraging them to return to their current task. No emojis, it will "
        "be read aloud."
    ),
    # State the goal, affected access groups, and transition constraint explicitly;
    # OpenAI's current model guidance recommends outcome-focused prompts with
    # concrete goals, relevant context, constraints, and success criteria:
    # https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices
    "goal_access_start": (
        "A user has started a temporary goal-scoped exception for website/app "
        "access for the explicit goal: {goal!r}. Its selected access groups "
        "are: {group_labels!r}. The access duration is "
        "{duration_description}. Starting this exception does not imply that "
        "every selected group was blocked immediately beforehand, because "
        "another active policy may already permit one. Write one short, "
        "friendly spoken sentence confirming only the temporary exception "
        "and reminding them to use it specifically for that goal. No emojis, "
        "it will be read aloud."
    ),
    "goal_access_end": (
        "The temporary goal-scoped exception for website/app access for the "
        "explicit goal {goal!r} has ended. Its selected access groups were: "
        "{group_labels!r}. The exception ended because: {end_reason!r}. This "
        "removes only this grant's permission; it does not claim that every "
        "selected group is now blocked, because another active policy may "
        "still permit one. Write one short, supportive spoken sentence "
        "acknowledging the outcome and directing the user back to their "
        "current task without overstating effective enforcement. No emojis, "
        "it will be read aloud."
    ),
    "verdict_correction": (
        "The user {correction_action} for the latest productivity evaluation "
        "from {from_label!r} to {to_label!r}. Write one short, neutral spoken "
        "sentence confirming that the saved evaluation will count as "
        "{to_label!r}. Do not praise, do not nudge, do not challenge the "
        "correction, and do not reassess or reinterpret the visual evidence. "
        "No emojis, it will be read aloud."
    ),
}


def build_prompt(kind: str, **context) -> str:
    # str.format_map fills only the placeholders the template mentions:
    # https://docs.python.org/3/library/stdtypes.html#str.format_map
    # session_context defaults to a stub so ad-hoc calls never KeyError.
    context.setdefault("session_context", "(no session context available)")
    return (_TEMPLATES[kind] + _CONTEXT_SUFFIX).format_map(context)


class MessageGenerator:
    def __init__(
        self,
        client,
        model: str,
        store: ResultsStore,
        reasoning_effort: str = "medium",
    ):
        self.client = client                      # openai.OpenAI or test fake
        self.model = model
        self.store = store
        self.reasoning_effort = reasoning_effort

    def generate(self, kind: str, **context) -> str:
        """Build the prompt for `kind`, call the text model, log + persist the
        full exchange, and return the sentence to speak."""
        prompt = build_prompt(kind, **context)
        # Log the complete request prompt and active quality settings in one
        # timestamped record; the logging formatter supplies the timestamp.
        log.info(
            "message request (%s): model=%s reasoning=%s prompt=%s",
            kind,
            self.model,
            self.reasoning_effort,
            prompt,
        )
        # responses.create is the current plain-text generation call;
        # reasoning.effort is the documented quality control, while
        # output_text concatenates the model's text parts:
        # https://developers.openai.com/api/docs/guides/reasoning#get-started-with-reasoning
        # https://github.com/openai/openai-python#usage
        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            input=prompt,
        )
        text = response.output_text.strip()
        log.info("message output (%s): %s", kind, text)     # full output, uncut
        self.store.save_llm_exchange(
            "message",
            {
                "model": self.model,
                "reasoning": {"effort": self.reasoning_effort},
                "kind": kind,
                "input": prompt,
            },
            response.model_dump(),
        )
        return text
