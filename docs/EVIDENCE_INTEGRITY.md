# Evidence Integrity

ForensiFlow now includes a first engineering implementation of the README phase-six integrity work. It is designed to make run artifact changes detectable.

## What It Provides

- SHA-256 manifest: `evidence_manifest.json`
- Hash-chained event log: `evidence_chain.jsonl`
- Chain state pointer: `evidence_chain_state.json`
- Verification CLI: `tools/verify_evidence_integrity.py`

The feature does not make files immutable and is not a legal evidence vault by itself. It gives the experiment workflow a reproducible way to detect accidental or later modification of run artifacts.

## Automatic Outputs

Codex mobile-agent runs write integrity artifacts under the run directory or script workspace:

```text
evidence_manifest.json
evidence_chain.jsonl
evidence_chain_state.json
```

The manifest includes JSON, JSONL, TXT, XML, Markdown, Python, and log files by default. Large binary files are skipped.

## Verify A Run

```bash
python tools/verify_evidence_integrity.py <run_dir>
```

Build or rebuild a manifest before verification:

```bash
python tools/verify_evidence_integrity.py <run_dir> --write
```

Print machine-readable details:

```bash
python tools/verify_evidence_integrity.py <run_dir> --json
```

## Python API

```python
from runner.forensiflow.core.evidence_integrity import build_manifest, verify_manifest

manifest = build_manifest(run_dir, device_serial="serial", app_name="WhatsApp")
result = verify_manifest(run_dir)
```

## Current Limits

- The manifest proves the current files match the manifest, not that the first manifest was created by a trusted external timestamping authority.
- Local users with write access can rewrite both evidence files and manifests. For stronger assurance, export `evidence_manifest.json` and `evidence_chain_state.json` to external read-only storage after each experiment run.
- The feature intentionally avoids hashing very large binary artifacts by default to keep experiment feedback fast.
