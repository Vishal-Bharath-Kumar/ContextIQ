---
name: input-resolver
description: Resolve raw $ARGUMENTS into normalized content. Handles file-path detection, format conversion via markitdown (PDF/DOCX/PPTX/XLSX/images/audio/video), text passthrough, and >5MB preprocessing. WHEN: workflow says "Resolve Input", "/input-resolver", $ARGUMENTS is a file path, or input needs normalization before analysis.
license: MIT
metadata:
  author: KANINI
  version: 1.0.0
---

## Input

`$ARGUMENTS` — the raw input provided by the user or calling workflow.

## Resolution Logic

Determine input type from `$ARGUMENTS` and extract source content:

**File path** (any file path provided as input):
1. Verify the file exists and read its contents.
2. For any format that cannot be natively read, convert using the markitdown skill. Conversion is performed in memory — do not write intermediary files to disk.
   - `pdf`, `docx`, `pptx`, `xlsx` → convert to markdown.
   - `jpeg`, `jpg`, `png`, `gif`, `webp`, `bmp`, `tiff` → convert to markdown using OCR.
   - `mp3`, `mp4`, `wav`, `m4a`, `ogg` → transcribe to markdown.
   - If conversion fails → request an alternative file or pasted text and stop.
3. Validate content is readable and contains relevant information.

**Direct text**: Use `$ARGUMENTS` as source material directly.

**Fallback**: If no readable input or conversion fails → request a file path or pasted specification text.

## Large File Handling (>5MB)

1. First pass: extract headings and structure only.
2. Second pass: extract sections containing "requirement", "acceptance", "must", "shall", "user story".
3. Skip: appendix, revision history, references, background.
4. If still oversized: summarise verbose paragraphs to bullet points.

## Output

Resolved content ready for the calling workflow's analysis steps.

## Error Handling

| Error | Message | Remediation |
|---|---|---|
| File not found | "Input file does not exist at $ARGUMENTS" | Ask user for a valid path or pasted text |
| Unsupported format | "Cannot convert [ext] to markdown" | Request alternative format; stop if none |
| Conversion failure | "markitdown failed on [filename]" | Request alternative file or pasted text |
| File > 5MB after conversion | "Content oversized; applying section filtering" | Run large-file preprocessing per spec |
