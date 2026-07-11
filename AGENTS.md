# Data Quality Monitor - Agent Instructions

## Purpose
A multi-agent data quality system that analyzes datasets, detects anomalies,
and generates actionable quality reports. Users can also ask questions about
their data quality in natural language.

## Agents

### Collector Agent
- Accepts raw data (CSV text or JSON) via the invoke endpoint
- Computes summary statistics: row counts, null percentages, min/max/avg for numeric columns, unique value counts, distribution outliers
- Passes structured stats to the Analyzer

### Analyzer Agent
- Receives statistics from the Collector
- Uses LLM reasoning to identify anomalies, data quality issues, and suspicious patterns
- Classifies each finding by severity (critical, warning, info)
- Provides recommended fixes for each issue

### Reporter Agent
- Takes the Analyzer's findings and formats them into a clean, structured report
- Includes a summary section with counts by severity
- Returns the report as JSON that any downstream system can consume

## Chat Mode
- Users can send a natural language question about data quality
- The system uses the most recent quality report as context to answer

## Boundaries
- Never fabricate data or statistics that weren't computed from the actual input
- Always classify severity honestly -- don't inflate or downplay issues
- If input data is too small or malformed to analyze meaningfully, say so
