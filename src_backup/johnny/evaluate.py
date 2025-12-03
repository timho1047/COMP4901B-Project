import argparse
import subprocess

import json
import os
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage,AIMessage,ToolMessage

from prompt import BASELINE_SYSTEM_PROMPT
# Import the raw model and agent
from agent import llm, agent
from tools import AgentOutput

from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm


PROJECT_ROOT=Path(__file__).parent.parent.parent
INPUT_FILE=PROJECT_ROOT/"data"/"nq_test_100.jsonl"
OUTPUT_DIR=PROJECT_ROOT/"results"/"Johnny"

def load_questions(filepath)-> list[dict[Literal["id", "question", "answers"], str]]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Data file not found at: {filepath}")
    with open(filepath, 'r') as f:
        return [json.loads(line) for line in f.readlines()]
    
# Appends a single prediction entry to the specified JSONL file
def save_jsonl(results: list[dict], outputpath: str):
    with open(outputpath, "w", encoding="utf-8") as f:
            for entry in results:
                f.write(json.dumps(entry) + "\n")

# Reconstructs the 'trajectory' object from the message history
def parse_trajectory(messages, original_question):
 
    steps=[]
    step_count=0
    final_answer=""
    
    # Iterate through messages to pair ToolCalls (Action) with ToolMessages (Observation)
    # We skip the first message (User input)
    for i, msg in enumerate(messages):

        # 1. Identify an ACTION (AIMessage with tool_calls)
        if isinstance(msg, AIMessage) and msg.tool_calls:
            step_count += 1
            tool_call=msg.tool_calls[0]
            # Extract arguments (query)
            # Sometimes args are dict, sometimes string JSON
            args=tool_call.get("args", {})
            query=args.get("query", "Unknown Query")
            
            # Look ahead for the corresponding ToolMessage (Observation)
            retrieved_docs=[]
            if i + 1 < len(messages) and isinstance(messages[i+1], ToolMessage):
                tool_output=messages[i+1].content
                try:
                    # Parse the JSON string we created in tool.py
                    docs_data = json.loads(tool_output)
                    # Ensure it matches the requested format
                    for doc in docs_data:
                        retrieved_docs.append({
                            "title": doc.get("title", ""),
                            "snippet": doc.get("snippet", "")
                        })
                except:
                    # Fallback if parsing fails
                    retrieved_docs=[{"title": "Error", "snippet": str(tool_output)[:100]}]

            steps.append({
                "step_number": step_count,
                "action": "search",
                "query": query,
                "num_docs_requested": 3,
                "retrieved_documents": retrieved_docs
            })

        # 2. Identify FINAL ANSWER (AIMessage with NO tool_calls)
        elif isinstance(msg, AIMessage) and not msg.tool_calls:
            final_answer=msg.content

    return {
        "question": original_question,
        "steps": steps,
        "final_answer": final_answer,
        "total_search_steps": len(steps)
    }

def run_evaluation_single_question_agent(id: str, question: str, answers: list):
    # print(f"--- Question: {question} ---")
    
    inputs = {
        "messages": [HumanMessage(content=question)], 
        "question": question
    }
    output_state=agent.invoke(inputs)
    
    # Get the last message which should be the AgentResponse tool call
    last_msg=output_state["messages"][-1]
    
    if last_msg.tool_calls and last_msg.tool_calls[0]["name"]=="AgentOutput":
        args = last_msg.tool_calls[0]["args"]
        # Convert to Pydantic for validation/dot-notation access
        final_structure=AgentOutput(**args)

        agent_response_text=final_structure.answer.strip()
        # print(f"\n[Structured Output (Agent)]: \n{final_structure.answer}")
    else:
        print("The agent did not return a structured response.")
        print(f"Raw Output: {last_msg.content}")
        agent_response_text=last_msg.content.strip()

    messages=output_state["messages"]
    trajectory_data=parse_trajectory(messages, question)

    trajectory = {
        "id": id,
        "question": question,
        "ground_truths": answers,
        "trajectory": trajectory_data
    }

    prediction = {
        "id": id,
        "question": question,
        "answers": answers,
        "llm_response": agent_response_text,
    }

    return trajectory, prediction

def run_evaluation_single_question_base(id: str, question: str, answers: list):
    try:
        baseline_msg=llm.invoke(
            [SystemMessage(content=BASELINE_SYSTEM_PROMPT),
            HumanMessage(content=question)]
        )
        baseline_response_text=baseline_msg.content.strip()
        # print(f"\n[BASELINE (No Search) {id}]: \n{baseline_response_text}")
    except Exception as e:
        print(f"Baseline Failed: {e}")

    return {
        "id": id,
        "question": question,
        "answers": answers,
        "llm_response": baseline_response_text
    }

def evaluate_batch_questions_base(
    questions: list[dict[Literal["id", "question", "answers"], str]],
):
    results=[]
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [
            executor.submit(
                run_evaluation_single_question_base,
                question["id"],
                question["question"],
                question["answers"],
            )
            for question in questions
        ]
        for future in tqdm(futures, desc="Evaluating Baseline"):
            results.append(future.result())
    return results

def evaluate_batch_questions_agent(
    questions: list[dict[Literal["id", "question", "answers"], str]],
):
    trajectories=[]
    predictions=[]
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [
            executor.submit(
                run_evaluation_single_question_agent,
                question["id"],
                question["question"],
                question["answers"],
            )
            for question in questions
        ]
    for future in tqdm(futures, desc="Evaluating Agent"):
            try:
                traj, pred=future.result()
                trajectories.append(traj)
                predictions.append(pred)
            except Exception as e:
                print(f"Error executing agent task: {e}")
    return trajectories, predictions

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run_name", type=str, required=True)
    args = parser.parse_args()

    questions=load_questions(INPUT_FILE)

    if args.run_name=="nosearch":
        result_base=evaluate_batch_questions_base(questions)
        save_jsonl(result_base, OUTPUT_DIR/args.run_name/f"predictions_{args.run_name}.jsonl")

    if args.run_name=="search":
        trajectories_agent, predictions_agent=evaluate_batch_questions_agent(questions)
        save_jsonl(predictions_agent, OUTPUT_DIR/args.run_name/f"predictions_{args.run_name}.jsonl")
        save_jsonl(trajectories_agent, OUTPUT_DIR/args.run_name/f"agent_trajectories.jsonl")

        
    subprocess.run(
        [
            "uv",
            "run",
            "eval.py",
            "--run_name",
            args.run_name,
            "--result_dir",
            OUTPUT_DIR.as_posix(),
        ]
    )

        