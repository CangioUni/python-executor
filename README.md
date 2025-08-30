# Script Manager

A simple web-based tool to manage and monitor long-running Python scripts. It's particularly useful for running scripts that are not fully debugged and might fail, as it provides an auto-restart mechanism.

## Goal of the Software

This software is designed to control the execution of multiple Python scripts that need to run continuously, even after the user's session is closed. It monitors their execution and provides an automatic restart feature, which is advantageous for new or unstable scripts that are prone to failure.

## Features

*   **Web-based UI**: Manage your scripts from a simple, intuitive web interface.
*   **Persistent Scripts**: Scripts are stored in a `scripts.json` file and reloaded on application start.
*   **Run Scripts as Services**: Keep your scripts running in the background, independent of your terminal session.
*   **Automatic Restarts**: Configure scripts to restart automatically based on policies:
    *   `on-failure`: Restarts the script only if it exits with a non-zero status code.
    *   `always`: Restarts the script regardless of its exit status.
*   **Live Output Streaming**: View the live `stdout` and `stderr` of your scripts in real-time through the web UI.
*   **Easy Configuration**: Add new scripts by providing the script path, command-line arguments, and a restart policy through a web form.

## Getting Started

### Prerequisites

*   Python 3.12+ (as specified in `main.py`)

### Installation

1.  Clone this repository to your local machine.
2.  Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Running the Application

To start the Script Manager, run the following command in your terminal:

```bash
python main.py
```

The application will be accessible at `http://localhost:8000`.

## Usage

1.  **Adding a Script**:
    *   Open your web browser and navigate to `http://localhost:8000`.
    *   Click on the "Add New Script" button.
    *   On the "Add Script" page, you will need to provide:
        *   **Path**: The full path to the Python script you want to manage (e.g., `/home/user/scripts/my_script.py`).
        *   **Arguments**: Any command-line arguments your script needs, separated by spaces.
        *   **Restart Policy**: Choose a restart policy from the dropdown (`on-failure` or `always`).
    *   Click "Add Script". You will be redirected back to the homepage.

2.  **Managing Scripts**:
    *   The homepage displays a list of all your added scripts.
    *   For each script, you can see its name, restart policy, and its current status (`running`, `stopped`, `error`).
    *   Use the "Start" and "Stop" buttons to manually control the execution of each script. The status will update in real-time.

3.  **Viewing Script Details and Logs**:
    *   Click on a script's name in the list to go to its details page.
    *   This page shows the script's configuration, its runtime information (like start time and running duration), and a live stream of its output.
    *   The output log displays the most recent output from the script, which is useful for debugging.
