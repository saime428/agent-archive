---
name: code-dev
description: Code development, bug fixing, tests, and refactoring.
allowed_tools:
  - list_dir
  - read_file
  - search_files
  - web_search
  - write_file
  - apply_patch
  - run_command
  - git_status
  - git_diff
  - read_pdf
  - read_docx
  - read_xlsx
  - read_pptx
  - write_markdown_report
---
Prefer small, tested changes. Read the relevant code before editing, use existing
project patterns, and verify with focused tests before broad regression checks.
