# Context Extraction (Step 9) — thin pass

`tools/java/` (Maven module, JavaParser 3.27.0 per `configs/tools.lock`) + `src/context.py` (Python wrapper).

## What it does
1. `context.changed_ranges_by_file(diff_text)`: parses `--- ` / `@@ -lo,len` headers to get changed line
   ranges per file, on the buggy/old side (pure Python, no Defects4J needed — 4 unit tests).
2. `apsec.ContextExtractor` (Java): given a buggy-checkout source file + line ranges, parses with JavaParser,
   finds enclosing `MethodDeclaration`s overlapping those ranges, and returns JSON: class declaration line,
   import list, and per-method {containing_class, signature, begin/end line, full source}.
3. `context.extract(buggy_dir, src_classes_rel, diff_text)`: combines the two into `ContextItem` objects
   (`changed_method`, `signatures`, `imports_types`) for `context_budget.fit_to_budget` / `request_builders`.

## Validated on real data (Chart-19 / patch1-Chart-19-ACS)
Both changed methods (`getDomainAxisIndex`, `getRangeAxisIndex`) correctly identified from the actual
Defects4J-checked-out `CategoryPlot.java` (2500+ lines), with correct class declaration and 56 imports. No
errors. Never reads `fixed_oracle/` (defensive `workspaces.assert_not_fixed_oracle` call on every path).

## Bug found and fixed while validating
`ClassOrInterfaceDeclaration`/`MethodDeclaration` `toString()` includes the attached Javadoc by default. This
codebase's Javadoc is full of `{@link ...}` tags, whose literal `{` was mistaken by a naive "find first `{`"
header-truncation for the body's opening brace, corrupting `class_declaration` and `signature` (confirmed:
truncated mid-sentence inside the class-level comment). Fixed by calling `removeComment()` before deriving the
header text (full method `source` is still captured with its Javadoc, before the comment is stripped).

## Deferred (thin-pass scope, not full spec)
- **Referenced fields** and **direct helper methods** (protocol `context_priority` items 5–6) are not
  extracted yet — `context.extract` only produces `changed_method`, `signatures`, `imports_types`.
  `javaparser-symbol-solver-core` is already a dependency (for exactly this, later) but symbol resolution
  isn't wired up yet.
- Multi-file diffs are supported (each file processed independently) but not yet exercised on a real
  multi-file patch.
