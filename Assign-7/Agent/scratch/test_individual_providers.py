import os
import sys
import asyncio
from dotenv import load_dotenv

# Add the directory to sys.path so we can import llm_gatewayV3 modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "llm_gatewayV3"))

from llm_gatewayV3.providers import (
    GeminiProvider, NvidiaProvider, GroqProvider, CerebrasProvider,
    OpenRouterProvider, GitHubProvider, OllamaProvider
)
from llm_gatewayV3.cache import GeminiCache

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

async def test_provider(name, provider_inst):
    print(f"\n==================================================")
    print(f"Testing Provider: {name.upper()}")
    print(f"Model: {provider_inst.model}")
    print(f"Base URL: {getattr(provider_inst, 'base_url', 'N/A')}")
    print(f"==================================================")
    
    messages = [{"role": "user", "content": "Say 'OK' if you can read this."}]
    try:
        # Call provider.chat
        resp = await provider_inst.chat(
            messages=messages,
            max_tokens=50,
            temperature=0.0
        )
        print(f"🟢 SUCCESS!")
        print(f"Response: {resp.get('text', '').strip()}")
        print(f"Latency: {resp.get('latency_ms', 'N/A')} ms")
        print(f"Input Tokens: {resp.get('input_tokens')}, Output Tokens: {resp.get('output_tokens')}")
        return True
    except Exception as exc:
        print(f"🔴 FAILED!")
        print(f"Error Type: {type(exc).__name__}")
        print(f"Details: {exc}")
        return False

async def main():
    cache = GeminiCache()
    tests = []
    
    # 1. Gemini
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
        tests.append(("gemini", GeminiProvider(gemini_key, model, cache)))
    else:
        print("⚠️ GEMINI_API_KEY not found in .env")
        
    # 2. Nvidia
    nvidia_key = os.getenv("NVIDIA_API_KEY")
    if nvidia_key:
        model = os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-pro")
        tests.append(("nvidia", NvidiaProvider(nvidia_key, model)))
    else:
        print("⚠️ NVIDIA_API_KEY not found in .env")
        
    # 3. Groq
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        tests.append(("groq", GroqProvider(groq_key, model)))
    else:
        print("⚠️ GROQ_API_KEY not found in .env")
        
    # 4. Cerebras
    cerebras_key = os.getenv("CEREBRAS_API_KEY")
    if cerebras_key:
        model = os.getenv("CEREBRAS_MODEL", "qwen-3-235b-a22b-instruct-2507")
        tests.append(("cerebras", CerebrasProvider(cerebras_key, model)))
    else:
        print("⚠️ CEREBRAS_API_KEY not found in .env")
        
    # 5. OpenRouter
    openrouter_key = os.getenv("OPEN_ROUTER_API_KEY")
    if openrouter_key:
        model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
        tests.append(("openrouter", OpenRouterProvider(openrouter_key, model)))
    else:
        print("⚠️ OPEN_ROUTER_API_KEY not found in .env")
        
    # 6. GitHub
    github_key = os.getenv("GITHUB_ACCESS_TOKEN")
    if github_key:
        model = os.getenv("GITHUB_MODEL", "openai/gpt-4.1-mini")
        tests.append(("github", GitHubProvider(github_key, model)))
    else:
        print("⚠️ GITHUB_ACCESS_TOKEN not found in .env")
        
    # 7. Ollama
    ollama_model = os.getenv("OLLAMA_MODEL")
    if ollama_model:
        url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        tests.append(("ollama", OllamaProvider(ollama_model, url)))
    else:
        print("⚠️ OLLAMA_MODEL not found in .env")

    print(f"\nStarting individual reachability tests for {len(tests)} configured providers...")
    results = {}
    for name, provider_inst in tests:
        success = await test_provider(name, provider_inst)
        results[name] = success
        # Small sleep between tests to prevent concurrent port bind/collision or rapid rate-limiting
        await asyncio.sleep(1.0)
        
    print("\n==================================================")
    print("FINAL SUMMARY OF PROVIDER REACHABILITY")
    print("==================================================")
    for name, success in results.items():
        status = "🟢 ACTIVE & REACHABLE" if success else "🔴 REACHABILITY/AUTH ERROR"
        print(f"- {name.upper()}: {status}")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(main())
