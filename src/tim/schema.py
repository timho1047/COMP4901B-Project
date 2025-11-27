from typing import Annotated, Literal, TypedDict

from langgraph.graph import MessagesState


class Action(TypedDict):
    action: str


class Step(TypedDict):
    step_number: int
    actions: list[Action]


def step_reducer(old_steps: list[Step], new_steps: list[Step]):
    merged_steps = list[Step]()
    mapping = dict[int, list[Action]]()
    for old_step in old_steps:
        mapping.setdefault(old_step["step_number"], []).extend(old_step["actions"])
    for new_step in new_steps:
        mapping.setdefault(new_step["step_number"], []).extend(new_step["actions"])

    for step_number in sorted(list(mapping.keys())):
        merged_steps.append(Step(step_number=step_number, actions=mapping[step_number]))

    return merged_steps


class BaseAgentState(MessagesState):
    current_step: int
    steps: Annotated[list[Step], step_reducer]
    question: str
    answer: str | None


class SearchEntry(TypedDict):
    title: str
    link: str
    snippet: str


class SearchAction(Action):
    action: Literal["search"]
    query: str
    num_docs_requested: int
    retrieved_documents: list[SearchEntry]

class BrowseAction(Action):
    action: Literal["browse"]
    url: str
    browsed_content: str