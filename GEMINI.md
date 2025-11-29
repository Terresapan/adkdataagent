# Google ADK Data Agent

This project is a Data Analysis Agent built using **Streamlit**, **Google ADK (Agent Development Kit)**, and the **Google GenAI SDK**. It provides a chat interface for users to upload data (CSV/Excel) and ask natural language questions to analyze it, generating plots and reports.

## Project Overview

The agent leverages Gemini (specifically `gemini-2.5-flash`) to plan and execute Python code for data analysis. It includes custom logic to bridge the gap between the isolated execution environment of the ADK and the user interface, particularly for streaming plots and files.

### Key Components

- **`streamlit_app.py`**: The frontend application. Handles user interaction, file uploads, state management, and rendering of the chat interface (text, plots, PDFs).
- **`main.py`**: The backend initialization and execution logic. Configures the `LlmAgent`, `Runner`, and `InMemorySessionService`. It implements a queue-based streaming mechanism to pass events from the async ADK runner to the Streamlit UI.
- **`tools.py`**: Contains callback functions, specifically `save_llm_generated_plot_artifact_callback_async`, which is used to capture and persist generated image artifacts.
- **`limitation.md`**: Documents specific architectural challenges with the current ADK version (e.g., "Last Output Wins" for plots) and the workarounds implemented in this project.

## Setup and Usage

### Prerequisites

- Python 3.13+
- A Google Cloud Project with the Gemini API enabled.
- A Google API Key.

### Installation

1.  **Install Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

    _Note: This project also contains a `uv.lock` file, suggesting `uv` can be used for faster dependency management._

2.  **Configure Secrets:**
    Create a `.streamlit/secrets.toml` file or set the environment variable `GOOGLE_API_KEY`.
    ```toml
    # .streamlit/secrets.toml
    [llmapikey]
    GOOGLE_API_KEY = "your_api_key_here"
    ```

### Running the Application

Start the Streamlit server:

```bash
streamlit run streamlit_app.py
```

## Architecture & Conventions

### Streaming & Async Bridge

Streamlit operates synchronously, while the ADK runner is asynchronous. This project uses a `queue.Queue` and a separate background thread (`threading.Thread` running an `asyncio` loop) to bridge these two worlds.

- **`run_streaming_async`** in `main.py` iterates over the ADK events and puts them into the queue.
- **`streamlit_app.py`** polls this queue to update the UI in real-time.

### Artifact Handling (The "Tunneling" Hack)

Due to limitations in the ADK regarding file outputs (see `limitation.md`), this project implements a "sniffing" strategy:

- It inspects `inline_data` in the streaming response.
- It detects Magic Bytes for PNGs (`\x89PNG`) and PDFs (`%PDF`) to identify binary content.
- It manually tunnels these bytes to the UI queue to ensure users see every plot generated, not just the final one.

### Code Execution

The agent uses `BuiltInCodeExecutor` to run Python code. It is instructed to:

- Create one plot per turn.
- Explicitly call `plt.show()` to generate image data.
- Use absolute paths for data loading (handled by the system note).

## Known Limitations

Refer to `limitation.md` for a detailed explanation of why certain workarounds (like the direct data capture loop) are necessary versus using standard ADK artifact services.
