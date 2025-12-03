import os
from typing import TypedDict, Annotated, Literal

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from dotenv import load_dotenv

from tools import tools_list

from prompt import AGENT_SYSTEM_PROMPT
from langchain.messages import HumanMessage, SystemMessage

# Load environment variables from .env
load_dotenv()

# Initiate the Model 
llm=ChatOpenAI(
    model="deepseek-chat", 
    temperature=0,
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


# Bind tools to the model
# llm_with_tools=llm.bind_tools(tools_list+[AgentOutput])
llm_with_tools=llm.bind_tools(tools_list)

# Define the Agent State
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    question: str

# Define the Agent Node
def agent_node(state: AgentState):
    # LLM generate response based on messages
    response=llm_with_tools.invoke(
        [SystemMessage(content=AGENT_SYSTEM_PROMPT),
        *state["messages"],
        HumanMessage(content=state["question"]),]
        )     
    return {"messages": [response]}

# Define the Tool Node
tool_node=ToolNode(tools_list)

# Define the agent loop logic
def should_continue(state: AgentState) -> Literal["tools", END]:
    if state["messages"][-1].tool_calls:
        return "tools"
    return END

# Define the Workflow
workflow=StateGraph(AgentState)

# Add Nodes to the workflow
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

# Add Edges
workflow.set_entry_point("agent")

workflow.add_conditional_edges("agent",should_continue)

workflow.add_edge("tools", "agent")

# Compile
coordinator_agent=workflow.compile()