import argparse
import os
import subprocess

from dotenv import load_dotenv

load_dotenv()


arg_parser = argparse.ArgumentParser()
arg_parser.add_argument("--run_name", type=str, required=True)
arg_parser.add_argument("--result_dir", type=str, required=True)

args = arg_parser.parse_args()

subprocess.run(
    [
        "uv",
        "run",
        "grade_with_em.py",
        "--input",
        f"{args.result_dir}/{args.run_name}/predictions_{args.run_name}.jsonl",
        "--output",
        f"{args.result_dir}/{args.run_name}/results_{args.run_name}_em.json",
    ]
)

subprocess.run(
    [
        "uv",
        "run",
        "grade_with_llm_judge.py",
        "--model",
        "deepseek-chat",
        "--base_url",
        "https://api.deepseek.com/v1",
        "--api_key",
        os.getenv("DEEPSEEK_API_KEY"),
        "--input",
        f"{args.result_dir}/{args.run_name}/predictions_{args.run_name}.jsonl",
        "--output",
        f"{args.result_dir}/{args.run_name}/results_{args.run_name}_llm_judge.json",
    ]
)
