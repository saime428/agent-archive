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
  - mcp:*
---
Prefer the simplest correct change. Use this order: existing project code,
built-in language features, an already imported standard library module, then a new
import only if necessary. Do not add an import, dependency, helper, or abstraction
when a clear built-in expression solves the same behavior. When two fixes are
equivalent, choose fewer changed lines and no new imports. Read the relevant code
before editing, and verify with focused tests before broad regression checks. For
equivalent Python whitespace normalization, prefer split()/join() over re.sub.
