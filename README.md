# League of Legends Matchup Analyzer — Multi-Step LLM Agent

A **pure-Python**, framework-free, multi-step LLM agent that generates a tactical strategy report for any League of Legends champion matchup. It chains **4 LLM calls** (Groq / Llama-3.3-70b) and **1 web-search tool call** through a shared state dictionary, producing a polished Markdown report with power spikes, build paths, and a minute-by-minute game plan.

> **No LangChain. No LlamaIndex. No agent frameworks.**
> Only the official `groq` Python SDK, a shared `state` dict, and clean modular code.

---

## Table of Contents

- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Pipeline Steps](#pipeline-steps)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [Example Output](#example-output)
- [How the State Dict Works](#how-the-state-dict-works)
- [Error Handling](#error-handling)

---

## Architecture

```
+----------------+
|   User Input   |
+-------+--------+
        |
        v
+-----------------------------------------------------------------------+
|  main.py  -- Orchestrator                                             |
|  Initialises state = {} and pipes it through each step                |
|                                                                       |
|  +---------+   +---------+   +----------+   +----------+   +--------+|
|  | Step 1  |-->| Step 2  |-->| Step 3   |-->| Step 4   |-->| Step 5 ||
|  | Parse   |   | Search  |   | Analyse  |   | Timeline |   | Format ||
|  | (LLM)   |   | (DDGS)  |   | (LLM)    |   | (LLM)    |   | (LLM)  ||
|  +---------+   +---------+   +----------+   +----------+   +--------+|
|        |            |              |              |              |    |
|        +------------+--------------+--------------+--------------+    |
|                          shared state dict {}                         |
+-----------------------------------------------------------------------+
        |
        v
+---------------------------+
| strategy_report.md        |
| (saved in project folder) |
+---------------------------+
```

---

## Project Structure

```
LLM_agent_NLP_asg/
|-- main.py               # Orchestrator -- runs the 5-step pipeline
|-- agent_steps.py        # All 5 pipeline step functions (merged)
|-- llm.py                # Groq API helper with Markdown-fence stripping
|-- requirements.txt      # Python dependencies
|-- .env                  # GROQ_API_KEY (not committed to git)
|-- README.md             # This file
`-- strategy_report.md    # Generated tactical report (auto-created on run)
```

All code files live flat in the project directory — no subdirectories.

---

## Pipeline Steps

| Step | Function | Type | Description |
|------|----------|------|-------------|
| 1 | `agent_steps.parse_input` | **LLM Call** | Extracts `user_champ`, `lane_opponent`, `user_role`, `enemy_jungle`, supports from free-form input |
| 2 | `agent_steps.search_web` | **Tool Call** | Builds a dynamic query and searches DuckDuckGo for current-patch matchup data |
| 3 | `agent_steps.analyze_matchup` | **LLM Call** | Analyzes power spikes, build path, and matchup difficulty |
| 4 | `agent_steps.generate_timeline` | **LLM Call** | Generates a minute-by-minute tactical plan (Min 1-20) |
| 5 | `agent_steps.format_report` | **LLM Call** | Formats a polished Markdown strategy report and saves to disk |

---

## Setup & Installation

### Prerequisites

- **Python 3.9+**
- A **Groq API key** (free at [console.groq.com](https://console.groq.com))

### 1. Clone the repository

```bash
git clone <repo-url>
cd LLM_agent_NLP_asg
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key

Create a `.env` file in the project root (if it doesn't exist):

```
GROQ_API_KEY=gsk_your_key_here
```

---

## Usage

### Interactive mode (prompted)

```bash
python main.py
```

You'll be prompted to describe your matchup:

```
Describe your matchup (e.g. 'I'm playing Darius top vs Garen, enemy jungler is Lee Sin'):
> I'm playing Yasuo mid against Zed, the enemy jungler is Evelynn
```

### Command-line mode

```bash
python main.py "I'm playing Darius top vs Garen, enemy jungler is Lee Sin"
```

### Supports 2v2 bot-lane matchups too

```bash
python main.py "I'm playing Lux ADC with Yuumi support vs Caitlyn and Lulu"
```

### What happens

1. The pipeline runs all 5 steps sequentially.
2. After **every step**, the full `state` dictionary is printed to the terminal for traceability.
3. The final Markdown report is saved as `strategy_report.md` in the same directory.

---

## Example Output

The generated `strategy_report.md` contains:

- **Matchup Overview** -- Champion names, role, difficulty rating
- **Power Spikes** -- Early / Mid / Late game breakdown
- **Recommended Build** -- Starting items, core build, boots, situational
- **Tactical Timeline (Min 1-20)** -- A table with columns: Minute, Action, Wave Management, Threat Level, Jungle Threat, Notes
- **Win Condition** -- How to close out the game
- **Data Source Note** -- Web search vs training-data fallback

---

## How the State Dict Works

The entire pipeline revolves around a single Python dictionary called `state`:

```python
state = {"user_input": "I'm playing Darius top vs Garen..."}
```

Each step function reads from the state, writes new keys, and returns the same dict. The orchestrator prints the state after every step:

```
========================================================================
  STATE after Step 1 - Parse
========================================================================
{
  "user_input": "I'm playing Darius top vs Garen...",
  "user_champ": "Darius",
  "lane_opponent": "Garen",
  "user_role": "Top",
  "enemy_jungle": "Unknown",
  "ally_support": null,
  "enemy_support": null
}
========================================================================
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| DuckDuckGo search fails | `state["search_results"]` is set to `"SEARCH_FAILED"` -- Step 3 falls back to LLM training data |
| LLM returns Markdown-wrapped JSON | `llm.py` strips ` ```json ... ``` ` fences before parsing |
| Invalid JSON from LLM | `json.JSONDecodeError` is raised with the raw response for debugging |
| Missing `.env` / API key | The Groq SDK raises an authentication error at startup |
| Groq rate limit hit | A `rate_limit_exceeded` error is raised -- wait a moment and retry |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| LLM Provider | [Groq](https://groq.com) (Llama-3.3-70b-versatile) |
| LLM SDK | `groq` (official Python SDK) |
| Web Search | `ddgs` (DuckDuckGo Search) |
| Env Management | `python-dotenv` |
| Frameworks | **None** -- pure Python |

---

## License

This project is for educational / assignment purposes.