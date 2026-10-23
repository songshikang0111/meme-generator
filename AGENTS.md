# Project instructions

## Git workflow

- Use SSH for GitHub Git transport. The project remote is `git@github.com:songshikang0111/meme-generator.git`.
- Automatically create a local Git commit after each meaningful change once the appropriate checks pass. The user has authorized these commits; no additional confirmation is needed.
- Keep commits focused on the completed task, with descriptive English commit messages. Preserve unrelated user changes.
- Keep virtual environments, model caches, generated indexes, rendered outputs, credentials, and secrets out of commits.
- Automatic commits are local. Push commits when the user requests a push or provides an applicable standing push instruction.

## Meme library

- Write skill instructions, catalog annotations, aliases, scenarios, caption examples, and layout descriptions in English.
- Have the calling agent translate non-English user intent faithfully into an English embedding query.
- Retrieve five candidate templates for agent inspection and selection. Judge candidate recall rather than requiring a particular template to rank first.
