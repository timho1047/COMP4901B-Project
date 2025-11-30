from typing import Annotated, Literal, TypedDict

from langgraph.graph import MessagesState


class Action(TypedDict):
    action: str


class Step(TypedDict):
    step_number: int
    reasoning: list[str]
    actions: list[Action]


def step_reducer(old_steps: list[Step], new_steps: list[Step]):
    merged_steps = list[Step]()
    mapping = dict[int, tuple[list[str], list[Action]]]()
    for old_step in old_steps:
        value = mapping.setdefault(
            old_step["step_number"], (list[str](), list[Action]())
        )
        value[1].extend(old_step["actions"])
        value[0].extend(old_step["reasoning"])
    for new_step in new_steps:
        value = mapping.setdefault(
            new_step["step_number"], (list[str](), list[Action]())
        )
        value[1].extend(new_step["actions"])
        value[0].extend(new_step["reasoning"])

    for step_number in sorted(list(mapping.keys())):
        merged_steps.append(
            Step(
                step_number=step_number,
                reasoning=mapping[step_number][0],
                actions=mapping[step_number][1],
            )
        )

    return merged_steps


class BaseAgentState(MessagesState):
    current_step: int
    steps: Annotated[list[Step], step_reducer]
    question: str


class SheetAgentState(BaseAgentState):
    todo_list: list[tuple[str, Literal["pending", "in_progress", "done"]]]


class ReadSheetAction(Action):
    action: Literal["read_sheet"]
    sheet: str
    sheet_content: str

class Cell(TypedDict):
    name: str
    content: str | int | float | bool | None
    formatting: list[str] | None

class UpdateCellAction(Action):
    action: Literal["update_cell"]
    cell_data: list[Cell]


class WriteTodoAction(Action):
    action: Literal["write_todo"]
    todo_list: list[tuple[str, Literal["pending", "in_progress", "done"]]]


class ListSheetsAction(Action):
    action: Literal["list_sheets"]
    sheets: list[str]


class CreateSheetAction(Action):
    action: Literal["create_sheet"]
    sheet_title: str


class DeleteSheetAction(Action):
    action: Literal["delete_sheet"]
    sheet_title: str


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
