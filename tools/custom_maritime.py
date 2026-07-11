"""
Custom tools for the Data Quality Monitor agent.
Handles data parsing, statistics computation, and report formatting.
"""

import json
import io
import pandas as pd
from crewai.tools import tool


@tool("Parse CSV Data")
def parse_csv_data(csv_text: str) -> str:
    """
    Parse raw CSV text into summary statistics.
    Returns JSON with row count, column info, null counts,
    numeric distributions, and potential issues.
    """
    try:
        df = pd.read_csv(io.StringIO(csv_text))
    except Exception as e:
        return json.dumps({"error": f"Failed to parse CSV: {str(e)}"})

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

        # Numeric column stats
        if pd.api.types.is_numeric_dtype(df[col]):
            col_stats["min"] = float(df[col].min()) if not df[col].isna().all() else None
            col_stats["max"] = float(df[col].max()) if not df[col].isna().all() else None
            col_stats["mean"] = round(float(df[col].mean()), 2) if not df[col].isna().all() else None
            col_stats["std"] = round(float(df[col].std()), 2) if not df[col].isna().all() else None

            # Flag outliers (values beyond 3 std devs)
            if col_stats["std"] and col_stats["std"] > 0:
                mean = col_stats["mean"]
                std = col_stats["std"]
                outliers = df[(df[col] < mean - 3 * std) | (df[col] > mean + 3 * std)]
                if len(outliers) > 0:
                    col_stats["outlier_count"] = len(outliers)
                    stats["potential_issues"].append(
                        f"Column '{col}' has {len(outliers)} outliers beyond 3 standard deviations"
                    )

            # Flag negative values where unexpected
            if df[col].min() < 0:
                neg_count = int((df[col] < 0).sum())
                col_stats["negative_count"] = neg_count
                stats["potential_issues"].append(
                    f"Column '{col}' has {neg_count} negative values"
                )

        # String column stats
        else:
            col_stats["sample_values"] = df[col].dropna().head(3).tolist()

        # Flag high null percentage
        if col_stats["null_percentage"] > 5:
            stats["potential_issues"].append(
                f"Column '{col}' has {col_stats['null_percentage']}% null values"
            )

        stats["columns"][col] = col_stats

    # Check for duplicate rows
    dupe_count = int(df.duplicated().sum())
    if dupe_count > 0:
        stats["duplicate_rows"] = dupe_count
        stats["potential_issues"].append(f"Found {dupe_count} duplicate rows")

    return json.dumps(stats, indent=2)


@tool("Format Quality Report")
def format_quality_report(findings_json: str) -> str:
    """
    Take raw analysis findings and format them into a clean,
    structured quality report with severity counts and actionable items.
    """
    try:
        findings = json.loads(findings_json)
    except json.JSONDecodeError:
        # If it's not valid JSON, wrap it as a text finding
        findings = [{"severity": "info", "description": findings_json, "recommended_fix": "Review manually"}]

    if isinstance(findings, dict):
        findings = [findings]

    # Count by severity
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
            "status": "NEEDS ATTENTION" if severity_counts["critical"] > 0 else "ACCEPTABLE" if severity_counts["warning"] > 0 else "CLEAN"
        },
        "findings": findings
    }

    return json.dumps(report, indent=2)
