name: reviewer
description: Missing frontmatter delimiters, so this candidate must be rejected.

This document never starts with a frontmatter block, so the existing parser
must reject it before anything is written to the user store.
