from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse  
from typing import Optional
import time

# --- Callback to Save LLM Generated Plot as Artifact ---
async def save_llm_generated_plot_artifact_callback_async(
    callback_context: CallbackContext,
    llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """
    Saves all image parts in the response as artifacts and updates state with a LIST of files.
    """
    agent_name = callback_context.agent_name
    print(f"🎨 PLOT CALLBACK: Triggered for agent: {agent_name}")

    saved_artifact_details = []
    
    # 1. Initialize State Lists if they don't exist
    current_plots = callback_context.state.get("last_generated_plot_artifact", [])
    current_names = callback_context.state.get("last_generated_plot_original_name", [])
    
    # Handle case where state might be a single string from previous runs (legacy cleanup)
    if isinstance(current_plots, str): current_plots = [current_plots]
    if isinstance(current_names, str): current_names = [current_names]

    if llm_response.content and llm_response.content.parts:
        for i, part in enumerate(llm_response.content.parts):
            
            # Check for Image Mime Type
            if part.inline_data and part.inline_data.mime_type and part.inline_data.mime_type.startswith("image/"):
                mime_type = part.inline_data.mime_type
                original_filename = "plot.png" # Default

                # 2. Smarter Filename Extraction
                # Look at previous part for text like "saved it as my_plot.png"
                if i > 0:
                    prev_part = llm_response.content.parts[i-1]
                    if hasattr(prev_part, 'text') and prev_part.text:
                        text_prev = prev_part.text.lower()
                        # Simple heuristic to grab the word ending in .png
                        words = text_prev.split()
                        for word in reversed(words):
                            clean_word = word.strip("`'\".,:()")
                            if clean_word.endswith(".png") or clean_word.endswith(".jpg"):
                                original_filename = clean_word
                                break
                
                # 3. Create Unique Artifact Name
                timestamp = int(time.time())
                safe_name = "".join(c if c.isalnum() or c in ('.', '_', '-') else '_' for c in original_filename)
                artifact_filename = f"plot_{timestamp}_p{i}_{safe_name}"

                try:
                    # 4. Save to Artifact Service (The Heavy Lifting)
                    version = await callback_context.save_artifact(artifact_filename, part)
                    
                    # 5. Update Local Variables
                    current_plots.append(artifact_filename)
                    current_names.append(original_filename)
                    
                    saved_artifact_details.append({
                        "artifact": artifact_filename,
                        "original": original_filename,
                        "version": version
                    })
                    print(f"   ✅ Saved Artifact: {artifact_filename}")

                except Exception as e:
                    print(f"   ❌ Error saving plot artifact: {e}")

    # 6. Persist List to State (Only once per callback execution)
    if saved_artifact_details:
        callback_context.state["last_generated_plot_artifact"] = current_plots
        callback_context.state["last_generated_plot_original_name"] = current_names
        print(f"   📊 Total Plots Saved in Session: {len(current_plots)}")

    return None