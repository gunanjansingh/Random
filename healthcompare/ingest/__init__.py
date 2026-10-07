"""Ingestion: official documents -> cited, validated criterion values.

    fetch      download every document URL listed in data/india/plans.json
    extract    read each PDF (Claude + regex rules), validate quotes against the text
    apply      reconcile extracted values into data/india/plans.json

Run with `python -m healthcompare.ingest <step>`. Needs open network access to
insurer sites; `extract` needs `pip install pypdf anthropic` and an API key.
"""
