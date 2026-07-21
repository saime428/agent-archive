---
name: reviewer
description: Review changes for correctness, safety, and recovery before they land.
allowed_tools:
  - read_file
  - search_files
  - git_diff
---

REVIEWER-V2-BODY-MARKER revision:v2

Read the change, then report correctness, safety, and recovery findings.
Prefer the smallest correct fix over a rewrite.
