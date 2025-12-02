import os
from typing import List

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from prompts import SHEET_AGENT_SYSTEM_PROMPT
from schema import BaseAgentState, SheetAgentState, Step
from tools import (
    browse,
    create_sheet,
    delete_sheet,
    list_sheets,
    read_sheet,
    search,
    update_cell,
    write_todo,
)
from utils import format_todo_xml

load_dotenv()


def create_agent[S: BaseAgentState](
    state_cls: type[S], system_prompt: str, tools: List[BaseTool]
):
    llm = init_chat_model(
        model="deepseek-chat", api_key=os.getenv("DEEPSEEK_API_KEY")
    ).bind_tools(tools)

    def invoke_llm(
        messages: List[BaseMessage], state: S, max_retries: int = 3
    ) -> AIMessage:
        for _ in range(max_retries):
            try:
                ai_message = llm.invoke(messages)
                if ai_message.invalid_tool_calls:
                    raise Exception(
                        f"Invalid tool calls: {ai_message.invalid_tool_calls}"
                    )
                return ai_message
            except Exception as e:
                print(f"Error invoking LLM, retrying...: {e}")
                continue
        raise Exception(f"Failed to invoke LLM after {max_retries} retries")

    def agent(state: S, config: RunnableConfig) -> dict:
        if len(state["messages"]) == 0:  # At the beginning of the conversation
            human_message = HumanMessage(
                content=state["question"]
                + "\n\n<system_reminder>There is no todo list created yet. If you you are working on a task that requires multiple steps, you should create a todo list first using `write_todo` tool.</system_reminder>"
            )
            ai_message = invoke_llm(
                [
                    SystemMessage(content=system_prompt),
                    human_message,
                ],
                state,
            )
            return {
                "messages": [human_message, ai_message],
                "current_step": state["current_step"] + 1,
                "steps": [
                    Step(
                        step_number=state["current_step"] + 1,
                        reasoning=[ai_message.content],
                        actions=[],
                    )
                ],
            }
        else:
            no_todo_flag = len(state["todo_list"]) == 0
            has_in_progress_todo_flag = (
                len([todo for todo in state["todo_list"] if todo[1] == "in_progress"])
                > 0
            )
            has_pending_todo_flag = (
                len([todo for todo in state["todo_list"] if todo[1] == "pending"]) > 0
            )
            if no_todo_flag:
                system_reminder = "<system_reminder>There is no todo list created yet. If you you are working on a task that requires multiple steps, you should create a todo list first using `write_todo` tool.</system_reminder>"
            elif has_in_progress_todo_flag:
                system_reminder = f"<system_reminder>Here is the current todo list:\n{format_todo_xml(state['todo_list'])}\nYou have some in_progress todos. If you have completed this task, please use `write_todo` tool to mark this todo as done, and work on next todo, otherwise, please continue to work on this todo.</system_reminder>"
            elif has_pending_todo_flag:
                system_reminder = f"<system_reminder>Here is the current todo list:\n{format_todo_xml(state['todo_list'])}\nYou have some pending todos. Please use `write_todo` tool to mark one of the todos as in_progress, and work on this todo.</system_reminder>"
            else:
                system_reminder = f"<system_reminder>Here is the current todo list:\n{format_todo_xml(state['todo_list'])}\nYou have completed all todos. Please verify your work done (such as using `read_sheet` tool). If you are sure that you have completed all tasks perfectly, please use `write_todo` tool to clear the todo list. Otherwise, please use `write_todo` tool to create a new todo list if you are still working on some tasks.</system_reminder>"

            ai_message = invoke_llm(
                [
                    SystemMessage(content=system_prompt),
                    *state["messages"],
                    HumanMessage(content=system_reminder),
                ],
                state,
            )
            return {
                "messages": [ai_message],
                "current_step": state["current_step"] + 1,
                "steps": [
                    Step(
                        step_number=state["current_step"] + 1,
                        reasoning=[ai_message.content],
                        actions=[],
                    )
                ],
            }

    return (
        StateGraph(state_cls)
        .add_node("agent", agent)
        .add_node("tools", ToolNode(tools))
        .add_edge(START, "agent")
        .add_conditional_edges("agent", tools_condition)
        .add_edge("tools", "agent")
        .compile(checkpointer=InMemorySaver())
    )


def create_sheet_agent():
    return create_agent(
        SheetAgentState,
        SHEET_AGENT_SYSTEM_PROMPT,
        [
            read_sheet,
            update_cell,
            write_todo,
            list_sheets,
            search,
            browse,
            create_sheet,
            delete_sheet,
        ],
    )
