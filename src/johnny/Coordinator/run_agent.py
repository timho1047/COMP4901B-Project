from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent import coordinator_agent
from pathlib import Path
import json
import os

PROJECT_ROOT=Path(__file__).parent.parent.parent.parent
OUTPUT_DIR=PROJECT_ROOT/"results"/"Johnny"/"coordinator"

RECURSION_LIMIT=50
MAX_STEPS=20

def save_trajectory(messages, filename=OUTPUT_DIR / "coordinator_trajectories.jsonl"):
    trajectory_steps=[]
    final_answer=""
    question=""

    # Map tool_call_id to the step info so we can pair Action with Observation
    pending_tool_calls={}

    for msg in messages:
        # Capture User Question
        if isinstance(msg, HumanMessage):
            question=msg.content

        # Capture AI Actions (Tool Calls)
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                call_id=tool_call["id"]
                step_info={
                    "step": len(trajectory_steps)+1,
                    "tool": tool_call["name"],
                    "args": tool_call["args"],
                    "output": None
                }
                pending_tool_calls[call_id]=step_info
                trajectory_steps.append(step_info)

        # Capture Tool Outputs 
        elif isinstance(msg, ToolMessage):
            call_id=msg.tool_call_id
            # Find the pending step and fill in the output
            if call_id in pending_tool_calls:
                pending_tool_calls[call_id]["output"]=msg.content

        # Capture Final Answer
        elif isinstance(msg, AIMessage) and not msg.tool_calls:
            final_answer=msg.content

    # format each step record
    record = {
        "question": question,
        "steps": trajectory_steps,
        "final_answer": final_answer
    }

    # Save to file
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
        
    print(f"\n Trajectory saved to {filename}")

def running_agent(user_request: str):

    config={
    "configurable": {"thread_id": id, "max_steps": MAX_STEPS},
    "recursion_limit": RECURSION_LIMIT,
    }

    initial_input={
        "messages": [HumanMessage(content=user_request)], 
        "question": user_request
    }
    
    final_state=None

    print(f"User: {user_request}\n")

    # Run the Agent
    for event in coordinator_agent.stream(initial_input,config=config, stream_mode="values"):
        last_message=event["messages"][-1]
        # Keep tracking the state
        final_state=event 
        
        # Output the tool calls at real-time
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            tool_name=last_message.tool_calls[0]['name']
            print(f"Agent decided to call: {tool_name}")

    # Extract the results
    if final_state:
        last_msg=final_state["messages"][-1]
        if last_msg.content:
            print("\nOUTPUT:\n")
            print(last_msg.content)
        
        # Call the helper function to save the trajectory
        save_trajectory(final_state["messages"])

if __name__ == "__main__":
    user_request = (
        "I am in my Home Hoi Lai Estate. Read my calendar for tomorrow, "
        "check the weather, plan my route between meetings, "
        "suggest when I should eat lunch and dinner, and remind me if I need an umbrella."
    )
    running_agent(user_request)