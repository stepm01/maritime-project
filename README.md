# Data Quality Monitor

A multi-agent data quality system deployed on [Maritime](https://maritime.sh). Drop in any CSV data and get an AI-powered quality report identifying anomalies, null issues, outliers, and duplicates.

## How It Works

Three agents collaborate sequentially:

1. **Collector Agent** — Parses CSV data and computes summary statistics (null counts, distributions, outliers, duplicates)
2. **Analyzer Agent** — Uses LLM reasoning to detect anomalies and quality issues, classifying each by severity
3. **Reporter Agent** — Formats findings into a structured, actionable report

Also supports **chat mode**: ask follow-up questions about your data quality in natural language.

## Usage

### Analyze Data
```bash
curl -X POST https://your-agent-url/invoke \
  -H "Content-Type: application/json" \
  -d '{"csv_data": "col1,col2\nval1,val2\n..."}'
```

### Ask Questions
```bash
curl -X POST https://your-agent-url/invoke \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the most critical issues in my data?"}'
```

## What It Catches

- Null/missing values above threshold
- Statistical outliers (beyond 3 standard deviations)
- Unexpected negative values
- Duplicate rows
- Suspicious volume spikes
- Data gaps and missing time periods

## Tech Stack

- **Agents:** CrewAI (sequential multi-agent orchestration)
- **LLM:** Llama 3.3 70B via Groq
- **Data Processing:** Pandas
- **Deployment:** Maritime.sh

## Author

Built by [Stepan Muradkhanyan](https://github.com/stepm01)
