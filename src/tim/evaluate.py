import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from pprint import pprint

from agent import create_browse_agent, create_raw_agent, create_search_agent
from schema import BaseAgentState
from tqdm import tqdm

RECURSION_LIMIT = 50
MAX_STEPS = 20
PROJECT_ROOT = Path(__file__).parent.parent.parent
INPUT_FILE = PROJECT_ROOT / "data" / "nq_test_100.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "results" / "tim"


def evaluate_single_question(
    id: str,
    question: str,
    ground_truths: list[str],
    agent_type: Literal["search", "browse", "raw"] = "browse",
    enable_streaming: bool = False,
):
    if agent_type == "search":
        agent = create_search_agent()
    elif agent_type == "raw":
        agent = create_raw_agent()
    elif agent_type == "browse":
        agent = create_browse_agent()
    else:
        raise ValueError(f"Invalid agent type: {agent_type}")

    init_state = BaseAgentState(
        messages=[],
        current_step=0,
        question=question,
        answer=None,
        steps=[],
    )

    config = {
        "configurable": {"thread_id": id, "max_steps": MAX_STEPS},
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
                    for msg in chunk["tools"]["messages"]:
                        msg.pretty_print()
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
        "ground_truths": ground_truths,
        "trajectory": {
            "question": question,
            "steps": state["steps"],
            "final_answer": state["answer"],
            "total_search_steps": len(state["steps"]),
        },
    }

    prediction = {
        "id": id,
        "question": question,
        "answers": ground_truths,
        "llm_response": state["answer"],
    }

    return trajectory, prediction


def evaluate_batch_questions(
    questions: list[dict[Literal["id", "question", "answers"], str]],
    agent_type: Literal["search", "raw"] = "search",
):
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [
            executor.submit(
                evaluate_single_question,
                question["id"],
                question["question"],
                question["answers"],
                agent_type,
            )
            for question in questions
        ]
        results = [
            future.result() for future in tqdm(futures, desc="Evaluating questions")
        ]
    return results


def load_questions(
    input_file: str,
) -> list[dict[Literal["id", "question", "answers"], str]]:
    with open(input_file, "r") as f:
        return [json.loads(line) for line in f.readlines()]


def save_results(results: list[tuple[dict, dict]], output_dir: str, run_name: str):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trajectory_file = output_dir / f"trajectories_{run_name}.jsonl"
    prediction_file = output_dir / f"prediction_{run_name}.jsonl"

    with trajectory_file.open("w") as t, prediction_file.open("w") as p:
        for trajectory, prediction in results:
            t.write(json.dumps(trajectory) + "\n")
            p.write(json.dumps(prediction) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run_name", type=str, required=True)
    parser.add_argument("--agent_type", type=str, required=True)
    args = parser.parse_args()

    questions = load_questions(INPUT_FILE)
    results = evaluate_batch_questions(questions, args.agent_type)
    save_results(results, OUTPUT_DIR / args.run_name, args.run_name)

    subprocess.run(
        [
            "uv",
            "run",
            "eval.py",
            "--run_name",
            args.run_name,
        ]
    )
