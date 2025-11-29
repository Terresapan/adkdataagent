# Google ADK Limitations & Architectural Workarounds

*Date: November 28, 2025*

This document summarizes the architectural challenges encountered while building a Streamlit Data Agent using the Google Agent Development Kit (ADK) and the specific workarounds implemented to achieve a functional application.

## The Core Problem: "The Disappearing Data"

The primary challenge was displaying generated plots (PNGs) and reports (PDFs) in the Streamlit UI. The ADK's default behavior intercepted these files, making them inaccessible to standard stream processing logic.

### 1. Aggressive Artifact Swallowing
*   **Behavior:** When the Agent runs `plt.show()`, the execution environment generates an image. The ADK Client automatically detects this image, saves it to its internal `InMemoryArtifactService`, and **removes** the raw image data from the response stream. It replaces the image with a text string: `"Saved as artifact: 2025...png"`.
*   **Impact:** The UI receives text saying "I saved it," but never receives the image bytes to display.
*   **Workaround (The "Memory Heist"):** We implemented a logic loop in `main.py` that maintains a reference to the global `ArtifactService`. As the stream flows, we constantly poll `artifact_service.list_artifact_keys()`. When a new key appears, we immediately fetch the content using `load_artifact()`, effectively "stealing" the file back from the ADK's memory to send it to the UI.

### 2. The "Last Output Wins" & Naming Collision
*   **Behavior:** The ADK names artifacts based on a timestamp with **second-level precision** (e.g., `20251128_151425.png`).
*   **Impact:** If the Agent generates multiple plots within the same second (e.g., a Line Chart and a Bar Chart in one code block), the second plot creates an artifact with the *exact same ID* as the first. The `InMemoryArtifactService` uses a dictionary, so the second plot **overwrites** the first.
*   **Result:** The user only ever sees the *last* plot generated.
*   **Workaround:** We updated the Agent's system instructions to strictly mandate `time.sleep(1)` after every plotting command. This artificial delay forces the timestamp to tick over, ensuring unique filenames for each plot.

### 3. Cloud Sandbox Opacity
*   **Behavior:** The `BuiltInCodeExecutor`, when used with the Gemini API, executes code in a managed Google Cloud Sandbox (e.g., `/home/bard/`), not on the local machine running the Streamlit app.
*   **Impact:** We cannot use standard file I/O (`open('plot.png')`) to read files created by the agent, as they exist on a remote server.
*   **Workaround:** We rely entirely on the ADK's data transmission channels (Artifact Service and Output Stream) rather than trying to mount volumes or read from disk.

## Implemented Architecture

To robustly handle these limitations, `main.py` now uses a **Hybrid Architecture**:

1.  **Artifact Watcher:** Polls `InMemoryArtifactService` to catch PNGs that are "swallowed" by the ADK.
2.  **Stream Sniffer:** Watches the standard response stream for `inline_data` (Magic Bytes) to catch PDFs, which interestingly are *not* swallowed by the artifact hook and pass through directly.
3.  **Prompt Engineering:** Enforces `time.sleep(1)` to prevent artifact naming collisions.

## Future ADK Wishlist

For a seamless developer experience, future ADK versions should address:

1.  **Unique IDs:** Use UUIDs or high-precision timestamps for artifacts to prevent overwrites.
2.  **Transparent Streaming:** Allow configuration to disable "Auto-Save" and stream raw bytes for all media types directly to the client.
3.  **Unified Access:** Provide a consistent way to access execution outputs, regardless of whether they are "saved" or "streamed."