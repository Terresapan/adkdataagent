"""
Backend logic for Streamlit Data Agent
Fixes the 'list_artifacts' crash by relying on direct stream interception.
"""

import asyncio
import queue
import threading
import base64
# import inspect # Removed introspection
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.code_executors import BuiltInCodeExecutor
from google.adk.planners import BuiltInPlanner
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types
import google.genai.types as genai_types

# Keep your excellent callback
# from tools import save_llm_generated_plot_artifact_callback_async

_global_runner = None
# _workspace_dir = "temp_workspace" # Not needed for memory watcher

def initialize_backend(api_key: str, model_name: str = "gemini-2.5-flash"):
    global _global_runner
    try:
        session_service = InMemorySessionService()
        artifact_service = InMemoryArtifactService()
        
        # --- DEBUG INTROSPECTION REMOVED ---
        
        agent = LlmAgent(
            model=model_name,
            name="data_agent",
            planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=True)),
            instruction="""
            You are a data analysis agent.

            **CORE PROCESS:**
            1. **ANALYZE:** processing the data to find insights.
            2. **VISUALIZE:** Create plots to support your analysis.
            3. **REPORT:** Generate a comprehensive PDF report.
            4. **SUMMARIZE:** Output a final text summary for the user. not only put the summary in the thinking process but also print it to standard output (stdout).
            
            **VISUALIZATION RULES:**
            1. **ONE PLOT PER TURN**: Create one plot at a time.
            2. **USE `plt.show()`**: You MUST call `plt.show()` to generate the image data.
            3. **MANDATORY SLEEP**: After calling `plt.show()`, you MUST call `time.sleep(1)` to ensure unique artifact timestamps.
            
            **PDF REPORTING RULES:**
            - The PDF MUST contain:
              - **Title**: A clear title for the report.
              - **Executive Summary**: A text summary of the findings.
              - **Analysis**: Detailed text explaining the data and trends for each chart.
              - **Charts**: All generated charts embedded in the document text analysis.
              - **Conclusion**: A final conclusion summarizing the key insights.
            - Use `reportlab` to generate the PDF.
            
            **FINAL OUTPUT:**
            - After generating the PDF, you MUST print a **Final Analysis Summary** to standard output (stdout).
            - This summary should be formatted in Markdown and explain the key findings to the user directly in the chat.
            
            **DATA LOADING:**
            - Use absolute paths if provided in [System Note].
            """,
            code_executor=BuiltInCodeExecutor(),
            # Keep the callback - it ensures persistence!
            # after_model_callback=[save_llm_generated_plot_artifact_callback_async]
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                session_service.create_session(app_name="agents", user_id="user", session_id="session1")
            )
        finally:
            loop.close()

        _global_runner = Runner(
            agent=agent,
            app_name="agents",
            session_service=session_service,
            artifact_service=artifact_service
        )
        
        return True
    except Exception as e:
        print(f"Backend initialization error: {e}")
        return False


async def run_streaming_async(user_message: str | list, data_queue: queue.Queue):
    global _global_runner
    
    if _global_runner is None:
        data_queue.put(("error", "Backend not initialized."))
        data_queue.put(("done", None))
        return
        
    try:
        if isinstance(user_message, str):
            msg = genai_types.Content(role="user", parts=[genai_types.Part(text=user_message)])
        elif isinstance(user_message, list):
            msg = genai_types.Content(role="user", parts=user_message)
        else:
            data_queue.put(("error", "Invalid message type."))
            data_queue.put(("done", None))
            return
        
        # --- Track Seen Artifacts ---
        seen_artifact_ids = set()
        # Pre-fill with existing artifacts to avoid re-sending old ones on new turns
        try:
             # Use verified method name: list_artifact_keys with REQUIRED args
             existing_keys = await _global_runner.artifact_service.list_artifact_keys(
                 app_name="agents", user_id="user", session_id="session1"
             )
             for key in existing_keys:
                 seen_artifact_ids.add(key)
        except:
            pass

        async for event in _global_runner.run_async(user_id="user", session_id="session1", new_message=msg):
            
            # --- 1. ARTIFACT WATCHER (The Memory Heist) ---
            try:
                # Use verified method name: list_artifact_keys with REQUIRED args
                current_keys = await _global_runner.artifact_service.list_artifact_keys(
                    app_name="agents", user_id="user", session_id="session1"
                )
                
                for artifact_id in current_keys:
                    if artifact_id not in seen_artifact_ids:
                        # NEW ARTIFACT FOUND!
                        seen_artifact_ids.add(artifact_id)
                        print(f"DEBUG: New artifact detected: ID={artifact_id}")
                        
                        # Retrieve content using verified signature: load_artifact(..., filename=...)
                        try:
                            loaded_part = await _global_runner.artifact_service.load_artifact(
                                app_name="agents", user_id="user", session_id="session1", 
                                filename=artifact_id
                            )
                            
                            file_bytes = None
                            filename_hint = str(artifact_id).lower()
                            
                            if loaded_part:
                                # Extract data from types.Part object
                                inline_data = getattr(loaded_part, "inline_data", getattr(loaded_part, "inlineData", None))
                                if inline_data:
                                    raw_data = getattr(inline_data, "data", None)
                                    if raw_data:
                                        file_bytes = raw_data
                                        # Decode if base64 string
                                        if isinstance(raw_data, str):
                                            try:
                                                file_bytes = base64.b64decode(raw_data)
                                            except:
                                                pass

                            if file_bytes:
                                # Sniff Magic Bytes for accurate type detection
                                if file_bytes.startswith(b'%PDF'):
                                    print("DEBUG: Sniffed PDF magic bytes.")
                                    data_queue.put(("pdf", file_bytes))
                                elif file_bytes.startswith(b'\x89PNG') or file_bytes.startswith(b'\xff\xd8'):
                                    print("DEBUG: Sniffed Image magic bytes.")
                                    data_queue.put(("image", file_bytes))
                                else:
                                    # Fallback to filename hint
                                    if filename_hint.endswith(".pdf"):
                                        data_queue.put(("pdf", file_bytes))
                                    elif filename_hint.endswith(".png") or filename_hint.endswith(".jpg"):
                                        data_queue.put(("image", file_bytes))
                                    else:
                                        print(f"DEBUG: Unknown artifact type for ID {artifact_id}. Start: {file_bytes[:10]}")
                            else:
                                print(f"DEBUG: Loaded artifact {artifact_id} but found no inline_data.")

                        except Exception as err:
                             print(f"ERROR fetching artifact content for {artifact_id}: {err}")

            except Exception as e:
                print(f"DEBUG: Error checking artifacts: {e}")


            # --- 2. STANDARD EVENT PROCESSING ---
            parts_list = []
            if event.content and event.content.parts:
                parts_list.extend(event.content.parts)
            
            for part in parts_list:
                
                # --- RESTORED: Direct Stream Artifact Handler ---
                found_stream_bytes = None
                
                # Check inline_data
                inline_check = getattr(part, "inline_data", getattr(part, "inlineData", None))
                if inline_check:
                    raw_d = getattr(inline_check, "data", None)
                    if raw_d:
                        found_stream_bytes = raw_d
                        if isinstance(raw_d, str):
                            try:
                                found_stream_bytes = base64.b64decode(raw_d)
                            except:
                                pass

                # Check file_data (rare but possible)
                if not found_stream_bytes:
                    file_check = getattr(part, "file_data", getattr(part, "fileData", None))
                    if file_check:
                         # Some SDKs stream data here
                         pass

                if found_stream_bytes and isinstance(found_stream_bytes, bytes):
                    if found_stream_bytes.startswith(b'%PDF'):
                        print("DEBUG: Direct Stream PDF found.")
                        data_queue.put(("pdf", found_stream_bytes))
                        continue
                    elif found_stream_bytes.startswith(b'\x89PNG') or found_stream_bytes.startswith(b'\xff\xd8'):
                        print("DEBUG: Direct Stream Image found.")
                        data_queue.put(("image", found_stream_bytes))
                        continue

                # ------------------------------------------------


                # Pass Thoughts
                if getattr(part, "thought", False):
                     if hasattr(part, "text") and part.text:
                        data_queue.put(("thought", part.text))
                     continue

                # Pass Text
                if hasattr(part, "text") and part.text:
                    text_val = part.text.strip()
                    # Filter out the specific "Saved as artifact" message to avoid clutter
                    if "Saved as artifact" not in text_val:
                        if text_val:
                            data_queue.put(("text", text_val))

                # Pass Code
                if hasattr(part, "executable_code") and part.executable_code:
                    code_block = f"```python\n{part.executable_code.code}\n```\n"
                    data_queue.put(("code", code_block))
                
                # Pass Code Output
                if hasattr(part, "code_execution_result") and part.code_execution_result:
                     raw_output = part.code_execution_result.output
                     if isinstance(raw_output, str):
                         output = f"```\n{raw_output}\n```\n"
                         data_queue.put(("code_output", output))
                     # Fallback for direct bytes in output (Legacy/Fallback)
                     elif isinstance(raw_output, bytes):
                         if raw_output.startswith(b'%PDF'):
                             print("DEBUG: Code Output PDF found.")
                             data_queue.put(("pdf", raw_output))
                         elif raw_output.startswith(b'\x89PNG') or raw_output.startswith(b'\xff\xd8'):
                             print("DEBUG: Code Output Image found.")
                             data_queue.put(("image", raw_output))

        data_queue.put(("done", None))
        
    except Exception as e:
        import traceback
        traceback.print_exc() 
        data_queue.put(("error", f"Streaming error: {e}"))
        data_queue.put(("done", None))


def process_user_message(user_message: str, data_queue: queue.Queue):
    def run_async_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_streaming_async(user_message, data_queue))
        finally:
            loop.close()
    
    thread = threading.Thread(target=run_async_in_thread)
    thread.start()
    return thread

def is_backend_initialized():
    return _global_runner is not None