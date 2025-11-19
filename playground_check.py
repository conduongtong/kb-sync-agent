"""
Script to verify the Assistant can answer the sample question.
This script can be used to test the assistant or generate output for verification.
"""

import os
import json
import warnings
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Suppress deprecation warning for Assistants API (still the current API)
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*Assistants API.*")

load_dotenv()


def check_assistant(assistant_id: str = None, vector_store_id: str = None):
    """
    Check if assistant can answer the sample question.
    
    If assistant_id is provided, uses that assistant.
    Otherwise, creates a new assistant with the vector store.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Read system prompt
    prompt_file = Path("optibot_system_prompt.txt")
    if not prompt_file.exists():
        print("ERROR: optibot_system_prompt.txt not found")
        return
    
    with open(prompt_file, "r", encoding="utf-8") as f:
        system_prompt = f.read()
    
    # Get or create assistant
    if assistant_id:
        try:
            assistant = client.beta.assistants.retrieve(assistant_id)
            print(f"Using existing assistant: {assistant_id}")
        except Exception as e:
            print(f"Error retrieving assistant: {e}")
            return
    else:
        if not vector_store_id:
            print("ERROR: Either assistant_id or vector_store_id must be provided")
            print("Hint: Check artifacts/last_run.json for vector_store_id")
            return
        
        # Create assistant
        assistant = client.beta.assistants.create(
            name="OptiBot",
            instructions=system_prompt,
            model="gpt-3.5-turbo",
            tools=[{"type": "file_search"}],
            tool_resources={
                "file_search": {
                    "vector_store_ids": [vector_store_id]
                }
            }
        )
        print(f"Created new assistant: {assistant.id}")
        print(f"Vector Store ID: {vector_store_id}")
    
    # Create thread and ask question
    question = "How do I add a YouTube video?"
    print(f"\nQuestion: {question}")
    
    thread = client.beta.threads.create()
    
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=question
    )
    
    # Run assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )
    
    print("Waiting for response...")
    
    # Poll for completion
    import time
    while run.status in ["queued", "in_progress"]:
        time.sleep(1)
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
    
    if run.status == "completed":
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        assistant_message = messages.data[0]
        
        print("\n" + "=" * 60)
        print("Assistant Response:")
        print("=" * 60)
        
        if hasattr(assistant_message.content[0], 'text'):
            response_text = assistant_message.content[0].text.value
            print(response_text)
            
            # Check for citations
            if "Article URL:" in response_text or "article" in response_text.lower():
                print("\n✓ Response includes article citations")
            else:
                print("\n⚠ Response may not include article citations")
        else:
            print("Unexpected response format")
        
        print("\n" + "=" * 60)
        print(f"Assistant ID: {assistant.id}")
        print(f"Thread ID: {thread.id}")
        print("\nTo view in Playground:")
        print(f"1. Go to https://platform.openai.com/playground")
        print(f"2. Create/select Assistant with ID: {assistant.id}")
        print(f"3. Ask: {question}")
        print(f"4. Take a screenshot showing the response with Article URL citations")
    else:
        print(f"Run failed with status: {run.status}")
        if hasattr(run, 'last_error'):
            print(f"Error: {run.last_error}")


if __name__ == "__main__":
    import sys
    
    # Try to get vector_store_id from last_run.json
    artifact_file = Path("artifacts/last_run.json")
    vector_store_id = None
    
    if artifact_file.exists():
        with open(artifact_file, "r") as f:
            artifact = json.load(f)
            vector_store_id = artifact.get("vector_store_id")
    
    # Allow override via command line
    assistant_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    check_assistant(assistant_id=assistant_id, vector_store_id=vector_store_id)

