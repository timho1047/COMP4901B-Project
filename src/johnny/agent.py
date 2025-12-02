import os
from typing import TypedDict, Annotated, Literal

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from dotenv import load_dotenv

from tools import tools_list, AgentOutput

from prompt import AGENT_SYSTEM_PROMPT
from langchain.messages import HumanMessage, SystemMessage, ToolMessage

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
llm_with_tools=llm.bind_tools(tools_list+[AgentOutput])

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
def should_continue(state: AgentState) -> Literal["tools", "final_processing", END]:
    messages=state["messages"]
    last_message = messages[-1]

    # If no tools called, just end
    if not last_message.tool_calls:
        return END
    
    # Check which tool was called
    tool_name=last_message.tool_calls[0]["name"]
    
    if tool_name == "AgentOutput":
        return "final_processing"
    
    # Otherwise it is search tool
    return "tools"

# Extracts the structured output from the tool call
def processing_node(state: AgentState):
    last_message=state["messages"][-1]
    tool_call=last_message.tool_calls[0]
    
    # Parse the arguments into Pydantic model
    try:
        response_data=tool_call["args"]
        final_output=AgentOutput(**response_data)
        
        # Append ToolMessage
        return {"messages": []}
        
    except Exception as e:
        return {"messages": [ToolMessage(tool_call_id=tool_call["id"], content=f"Error parsing structure: {e}")]}

# Define the Workflow
workflow=StateGraph(AgentState)

# Add Nodes to the workflow
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)
workflow.add_node("final_processing", processing_node)

# Add Edges
workflow.set_entry_point("agent")

workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "final_processing": "final_processing",
        END: END
    }
)

workflow.add_edge("tools", "agent")
workflow.add_edge("final_processing", END)

# Compile
agent=workflow.compile()