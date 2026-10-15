# AGENTS.md

## Purpose

Working rules for agents editing this Jekyll blog repository.

## Post Metadata

- Categories: use exactly 1 entry from `_data/categories.yml`.
- Tags: use 2-5 entries from `_data/tags.yml`.
- Names must be singular, lowercase, and hyphenated.

## Commit Messages

- Use Conventional Commits: `type(scope): subject`.
- Look at the staged and unstaged changes with `git diff`
- Write a clear commit message based on what changed
- For multi-line messages, use a temporary file with `git commit -F <temp_file_path> && rm -f <temp_file_path>` to avoid shell expansion issues.

## Writing Style

- Keep summaries to one concise sentence.
- Use impersonal tone.
