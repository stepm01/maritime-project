"""
Data Quality Monitor - Multi-Agent System
Deployed on Maritime.sh
"""
import litellm
litellm.drop_params = True

import os
os.environ["LITELLM_DROP_PARAMS"] = "true"

_original_completion = litellm.completion
def _patched_completion(*args, **kwargs):
    if "messages" in kwargs:
        for msg in kwargs["messages"]:
            if isinstance(msg, dict):
                msg.pop("cache_breakpoint", None)
                msg.pop("cache_control", None)
    return _original_completion(*args, **kwargs)
litellm.completion = _patched_completion

import json
import logging
import io
import pandas as pd
from flask import Flask, request, jsonify
from groq import Groq

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
latest_report = {"status": "No data analyzed yet. Send CSV data to /invoke to get started."}


def get_groq():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


# ─── AGENT 1: COLLECTOR ───
def collector_agent(csv_text):
    """Parse CSV and compute statistics. Pure Python, no LLM needed."""
    try:
        df = pd.read_csv(io.StringIO(csv_text))
    except Exception as e:
        return {"error": f"Failed to parse CSV: {str(e)}"}

    stats = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {},
        "potential_issues": []
    }

    for col in df.columns:
        col_stats = {
            "dtype": str(df[col].dtype),
            "null_count": int(df[col].isna().sum()),
            "null_percentage": round(df[col].isna().sum() / len(df) * 100, 2),
            "unique_values": int(df[col].nunique()),
        }

        if pd.api.types.is_numeric_dtype(df[col]):
            col_stats["min"] = float(df[col].min()) if not df[col].isna().all() else None
            col_stats["max"] = float(df[col].max()) if not df[col].isna().all() else None
            col_stats["mean"] = round(float(df[col].mean()), 2) if not df[col].isna().all() else None
            col_stats["std"] = round(float(df[col].std()), 2) if not df[col].isna().all() else None

            if col_stats["std"] and col_stats["std"] > 0:
                mean = col_stats["mean"]
                std = col_stats["std"]
                outliers = df[(df[col] < mean - 3 * std) | (df[col] > mean + 3 * std)]
                if len(outliers) > 0:
                    col_stats["outlier_count"] = len(outliers)
                    stats["potential_issues"].append(
                        f"Column '{col}' has {len(outliers)} outliers beyond 3 standard deviations"
                    )

            if df[col].min() < 0:
                neg_count = int((df[col] < 0).sum())
                col_stats["negative_count"] = neg_count
                stats["potential_issues"].append(
                    f"Column '{col}' has {neg_count} negative values"
                )
        else:
            col_stats["sample_values"] = df[col].dropna().head(3).tolist()

        if col_stats["null_percentage"] > 5:
            stats["potential_issues"].append(
                f"Column '{col}' has {col_stats['null_percentage']}% null values"
            )

        stats["columns"][col] = col_stats

    dupe_count = int(df.duplicated().sum())
    if dupe_count > 0:
        stats["duplicate_rows"] = dupe_count
        stats["potential_issues"].append(f"Found {dupe_count} duplicate rows")

    log.info(f"[Collector] Computed stats for {len(df.columns)} columns, {len(df)} rows")
    return stats


# ─── AGENT 2: ANALYZER (uses LLM) ───
def analyzer_agent(stats):
    """Send stats to LLM for anomaly detection."""
    client = get_groq()

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{
            "role": "user",
            "content": f"""You are a senior data quality analyst. Review these statistics and identify all data quality issues.

STATISTICS:
{json.dumps(stats, indent=2)}

For each issue, return a JSON array of objects with:
- "check_type": category (missing_data, outlier, negative_values, duplicates, trend_anomaly)
- "severity": "critical", "warning", or "info"
- "description": clear explanation
- "recommended_fix": actionable fix

Return ONLY valid JSON array. No markdown, no backticks, no preamble."""
        }],
        max_tokens=1500,
        temperature=0.1,
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        findings = json.loads(raw)
    except json.JSONDecodeError:
        findings = [{"check_type": "parse_error", "severity": "warning",
                     "description": "Could not parse LLM response", "recommended_fix": "Review manually"}]

    log.info(f"[Analyzer] Found {len(findings)} quality issues")
    return findings


# ─── AGENT 3: REPORTER ───
def reporter_agent(findings):
    """Format findings into a structured report. Pure Python."""
    severity_counts = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info").lower()
        if sev in severity_counts:
            severity_counts[sev] += 1

    report = {
        "report_type": "Data Quality Analysis",
        "summary": {
            "total_issues": len(findings),
            "critical": severity_counts["critical"],
            "warnings": severity_counts["warning"],
            "info": severity_counts["info"],
            "status": "NEEDS ATTENTION" if severity_counts["critical"] > 0
                      else "ACCEPTABLE" if severity_counts["warning"] > 0
                      else "CLEAN"
        },
        "findings": findings
    }

    log.info(f"[Reporter] Report: {severity_counts['critical']} critical, "
             f"{severity_counts['warning']} warnings, {severity_counts['info']} info")
    return report


# ─── CHAT MODE ───
def handle_chat(question):
    client = get_groq()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system",
             "content": f"You are a data quality assistant. Answer based on this report:\n\n"
                        f"{json.dumps(latest_report, indent=2)}\n\nBe concise and specific."},
            {"role": "user", "content": question}
        ],
        max_tokens=500,
        temperature=0.1,
    )
    return response.choices[0].message.content


# ─── ROUTES ───
@app.route("/invoke", methods=["POST"])
def invoke():
    global latest_report
    data = request.get_json(force=True)

    if "question" in data:
        answer = handle_chat(data["question"])
        return jsonify({"mode": "chat", "answer": answer})

    if "csv_data" in data:
        csv_data = data["csv_data"]
        log.info(f"Received CSV data ({len(csv_data)} chars)")

        try:
            # Agent 1: Collect stats
            stats = collector_agent(csv_data)
            if "error" in stats:
                return jsonify({"error": stats["error"]}), 400

            # Agent 2: Analyze with LLM
            findings = analyzer_agent(stats)

            # Agent 3: Format report
            report = reporter_agent(findings)

            latest_report = report
            return jsonify({"mode": "analysis", "report": report})

        except Exception as e:
            log.error(f"Pipeline failed: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return jsonify({
        "error": "Send either 'csv_data' for analysis or 'question' for chat",
        "usage": {
            "analyze": {"csv_data": "col1,col2\\nval1,val2\\n..."},
            "chat": {"question": "What are the most critical issues?"}
        }
    }), 400


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "agent": "Data Quality Monitor"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log.info(f"Starting Data Quality Monitor on port {port}")
    app.run(host="0.0.0.0", port=port)