import json
from pathlib import Path
from pprint import pprint

from agent import create_sheet_agent
from schema import BaseAgentState

RECURSION_LIMIT = 100


PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "results" / "tim" / "sheet"


def evaluate_single_question(
    id: str,
    question: str,
    spreadsheet_id: str,
    enable_streaming: bool = False,
    save_output: bool = False,
):
    agent = create_sheet_agent()

    init_state = BaseAgentState(
        messages=[],
        current_step=0,
        question=question,
        steps=[],
        todo_list=[],
    )

    config = {
        "configurable": {"thread_id": id, "spreadsheet_id": spreadsheet_id},
        "recursion_limit": RECURSION_LIMIT,
    }

    state: BaseAgentState

    try:
        if enable_streaming:
            for chunk in agent.stream(init_state, config=config, stream_mode="updates"):
                if "agent" in chunk:
                    if "current_step" in chunk["agent"]:
                        print("=======================")
                        print(f"=Current step: {chunk['agent']['current_step']}")
                        print("=======================")
                    for msg in chunk["agent"]["messages"]:
                        msg.pretty_print()

                if "tools" in chunk:
                    tool_update = chunk["tools"]
                    if isinstance(tool_update, dict) and "messages" in tool_update:
                        for msg in tool_update["messages"]:
                            msg.pretty_print()
                    elif isinstance(tool_update, list):
                        for msg in tool_update:
                            if hasattr(msg, "pretty_print"):
                                msg.pretty_print()
                            else:
                                print(msg)
            state = agent.get_state(config=config).values
        else:
            state = agent.invoke(init_state, config=config)
    except Exception as e:
        state = agent.get_state(config=config).values
        print("================================================")
        pprint(state)
        print("================================================")
        print(f"Error: \n{e}\n")
        raise e

    trajectory = {
        "id": id,
        "question": question,
        "trajectory": {
            "question": question,
            "steps": state["steps"],
            "total_steps": len(state["steps"]),
        },
    }

    if save_output:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_DIR / f"{id}.json", "w") as f:
            json.dump(trajectory, f, indent=4)
            print(f"Saved trajectory to {OUTPUT_DIR / f'{id}.json'}")

    return trajectory
