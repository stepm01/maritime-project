"""
Data Quality Monitor - Multi-Agent System
Deployed on Maritime.sh

Ultra-lightweight version: no pandas, no litellm, no crewai.
Just flask + groq + pure Python.
"""

import os
import json
import csv
import io
import logging
import statistics
from flask import Flask, request, jsonify
from groq import Groq

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
latest_report = {"status": "No data analyzed yet. Send CSV data to /invoke to get started."}


def get_groq():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


# ─── AGENT 1: COLLECTOR (pure Python) ───
def collector_agent(csv_text):
    """Parse CSV and compute statistics without pandas."""
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
    except Exception as e:
        return {"error": f"Failed to parse CSV: {str(e)}"}

    if not rows:
        return {"error": "CSV is empty"}

    columns = list(rows[0].keys())
    stats = {
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": {},
        "potential_issues": []
    }

    for col in columns:
        values = [r[col] for r in rows]
        null_count = sum(1 for v in values if v is None or v.strip() == "")
        non_null = [v.strip() for v in values if v is not None and v.strip() != ""]

        col_stats = {
            "null_count": null_count,
            "null_percentage": round(null_count / len(rows) * 100, 2),
            "unique_values": len(set(non_null)),
        }

        # Try numeric parsing
        numeric_vals = []
        for v in non_null:
            try:
                numeric_vals.append(float(v))
            except ValueError:
                pass

        if len(numeric_vals) > len(non_null) * 0.5:
            col_stats["type"] = "numeric"
            col_stats["min"] = min(numeric_vals)
            col_stats["max"] = max(numeric_vals)
            col_stats["mean"] = round(statistics.mean(numeric_vals), 2)
            if len(numeric_vals) > 1:
                col_stats["std"] = round(statistics.stdev(numeric_vals), 2)

                # Outliers
                mean = col_stats["mean"]
                std = col_stats["std"]
                if std > 0:
                    outliers = [v for v in numeric_vals if v < mean - 3 * std or v > mean + 3 * std]
                    if outliers:
                        col_stats["outlier_count"] = len(outliers)
                        col_stats["outlier_values"] = outliers[:5]
                        stats["potential_issues"].append(
                            f"Column '{col}' has {len(outliers)} outliers beyond 3 std devs (e.g. {outliers[0]})"
                        )

            # Negative values
            neg = [v for v in numeric_vals if v < 0]
            if neg:
                col_stats["negative_count"] = len(neg)
                stats["potential_issues"].append(f"Column '{col}' has {len(neg)} negative values")
        else:
            col_stats["type"] = "text"
            col_stats["sample_values"] = non_null[:3]

        if col_stats["null_percentage"] > 5:
            stats["potential_issues"].append(
                f"Column '{col}' has {col_stats['null_percentage']}% null values"
            )

        stats["columns"][col] = col_stats

    # Duplicates
    row_strings = [json.dumps(r, sort_keys=True) for r in rows]
    dupe_count = len(row_strings) - len(set(row_strings))
    if dupe_count > 0:
        stats["duplicate_rows"] = dupe_count
        stats["potential_issues"].append(f"Found {dupe_count} duplicate rows")

    log.info(f"[Collector] Stats for {len(columns)} columns, {len(rows)} rows")
    return stats


# ─── AGENT 2: ANALYZER (LLM) ───
def analyzer_agent(stats):
    client = get_groq()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{
            "role": "user",
            "content": f"""You are a senior data quality analyst. Review these statistics and identify all data quality issues.

STATISTICS:
{json.dumps(stats, indent=2)}

For each issue return a JSON array of objects with:
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

    log.info(f"[Analyzer] Found {len(findings)} issues")
    return findings


# ─── AGENT 3: REPORTER ───
def reporter_agent(findings):
    severity_counts = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info").lower()
        if sev in severity_counts:
            severity_counts[sev] += 1

    report = {
        "report_type": "Data Quality Analysis",
        "agents_used": ["Collector (stats)", "Analyzer (LLM anomaly detection)", "Reporter (formatting)"],
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

    log.info(f"[Reporter] {severity_counts['critical']} critical, "
             f"{severity_counts['warning']} warnings, {severity_counts['info']} info")
    return report


# ─── CHAT ───
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

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "online",
        "service": "Data Quality Monitor",
        "usage": "Send a POST request to /invoke with your data."
    }), 200

# ─── ROUTES ───
@app.route("/invoke", methods=["POST"])
def invoke():
    global latest_report
    data = request.get_json(force=True)

    if "question" in data:
        answer = handle_chat(data["question"])
        return jsonify({"mode": "chat", "answer": answer})

    if "csv_data" in data:
        log.info(f"Received CSV data ({len(data['csv_data'])} chars)")
        try:
            stats = collector_agent(data["csv_data"])
            if "error" in stats:
                return jsonify({"error": stats["error"]}), 400
            findings = analyzer_agent(stats)
            report = reporter_agent(findings)
            latest_report = report
            return jsonify({"mode": "analysis", "report": report})
        except Exception as e:
            log.error(f"Pipeline failed: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return jsonify({
        "error": "Send 'csv_data' for analysis or 'question' for chat",
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