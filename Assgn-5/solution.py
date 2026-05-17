import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv

# Load root .env
ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:latest")
RULES_PATH = Path(__file__).parent / "prompt_rules.txt"

def call_ollama(system_prompt: str, user_prompt: str):
    """Simple wrapper to call Ollama's chat API."""
    url = f"{OLLAMA_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.1 # Low temp for evaluation
        }
    }
    
    try:
        response = httpx.post(url, json=payload, timeout=60.0)
        response.raise_for_status()
        return response.json()["message"]["content"]
    except Exception as e:
        return f"Error calling Ollama: {str(e)}"

def extract_json(text: str):
    """Extracts JSON from a markdown code block if present."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return text.strip()

def evaluate_prompt(prompt_to_test: str):
    """Step 1: Use gemma4 to evaluate the prompt based on rules."""
    with open(RULES_PATH, "r") as f:
        eval_system_prompt = f.read()
    
    print(f"🔍 Evaluating prompt against rules using {OLLAMA_MODEL}...")
    result_raw = call_ollama(eval_system_prompt, f"Please evaluate this prompt:\n\n{prompt_to_test}")
    
    try:
        json_str = extract_json(result_raw)
        return json.loads(json_str)
    except Exception as e:
        print(f"⚠️ Failed to parse evaluation JSON. Raw response:\n{result_raw}")
        return None

def run_guarded_prompt(user_prompt: str):
    """Main solution loop."""
    print("═" * 60)
    print(f"User Prompt: {user_prompt}")
    print("═" * 60)
    
    # Step 1: Evaluation
    report = evaluate_prompt(user_prompt)
    
    if not report:
        print("❌ Technical error during evaluation.")
        return

    # Define success criteria
    # We require at least the basic reasoning and structure flags to be true
    critical_flags = [
        "explicit_reasoning", 
        "structured_output", 
        "tool_separation"
    ]
    
    passed = all(report.get(flag, False) for flag in critical_flags)
    
    print("\n📊 Evaluation Report:")
    print(json.dumps(report, indent=2))
    
    if passed:
        print("\n✅ Criteria met! Processing prompt...")
        # Step 2: Actual Execution
        final_answer = call_ollama("You are a helpful assistant.", user_prompt)
        print("\n🚀 LLM Response:")
        print("─" * 60)
        print(final_answer)
        print("─" * 60)
    else:
        print("\n🛑 Prompt Rejected.")
        print(f"Reasoning: {report.get('overall_clarity', 'Does not meet reasoning standards.')}")
        print("Please improve your prompt to include explicit reasoning and structure.")

if __name__ == "__main__":
    print("🛡️  Guarded LLM Prompt System (Ollama/Gemma4)")
    print("Enter your prompt below (Type 'exit' to quit or Ctrl+C):")
    
    while True:
        try:
            user_input = input("\n📝 Prompt > ").strip()
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input:
                continue
                
            run_guarded_prompt(user_input)
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except EOFError:
            break
