# RAG Template Library

`all_templates.json` is intentionally empty in the public repository.

Historical templates from local experiments can contain absolute paths, device
state, private targets, and generated-script registry references. Sanitized
workflow examples are provided under `examples/` for reference only.

To build a runnable reuse library:

1. Run a read-only exploration task on your own device.
2. Let the Codex mobile agent publish its generated `action_path.json` and
   `generated_script.py`.
3. Use the generated RAG export output as your local `all_templates.json`.

Do not commit real run directories, private device data, or generated evidence
records.
