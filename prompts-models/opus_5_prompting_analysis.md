# Practical Prompting Guide for Claude Opus 5

## Purpose

This document converts the useful, prompt-relevant ideas found in the linked third-party `claude-opus-5.md` file into a standalone reference for another LLM. Its purpose is to help that LLM create effective prompts for Claude Opus 5 or Claude Code without reopening the source.

This is an analytical summary, not a reproduction of the source file.

## Source and reliability warning

**Analyzed source:**

- GitHub file: `asgeirtj/system_prompts_leaks/Anthropic/claude-opus-5.md`
- URL: https://github.com/asgeirtj/system_prompts_leaks/blob/main/Anthropic/claude-opus-5.md
- Accessed: 2026-08-30

The repository presents the file as an extracted system prompt for Claude Opus 5 and Claude Code. It is not official Anthropic documentation, so authenticity, completeness, version accuracy, and continued applicability cannot be guaranteed. Treat it as a behavioral clue, not as a contract or authoritative specification.

For current product behavior, supported features, APIs, pricing, limits, or installation instructions, consult official Anthropic documentation.

## Executive conclusion

The linked file is mainly a collection of instructions intended for Claude itself. It is **not primarily a user prompting manual**. However, it contains several useful clues for writing prompts that fit Claude's expected working style.

The principal user-facing prompting advice in the file is:

1. Be clear and sufficiently detailed.
2. Use positive and negative examples when ambiguity matters.
3. Ask for deliberate, stepwise handling of complicated work.
4. Use XML-style sections when they improve separation of context and instructions.
5. Specify the desired length and output format.

The rest of the useful prompting lessons must be inferred from the operating behavior described in the file, including tool use, repository inspection, file handling, verification, concise answers, and agentic completion of coding tasks.

## 1. What the linked file is about

The file appears to combine several categories of internal guidance:

- general conversational behavior and tone;
- safety and refusal behavior;
- web search and source handling;
- memory behavior;
- file creation and filesystem restrictions;
- tool definitions and tool-selection rules;
- specialist workflows for documents, spreadsheets, slides, PDFs, and frontend work;
- Claude Code or coding-agent behavior;
- response formatting and concision;
- internal reasoning behavior;
- product-specific behavior.

Most of this should **not** be copied into a normal task prompt. Claude already receives its own platform instructions. Repeating them can waste context and distract from the actual task.

## 2. Direct prompting guidance extracted from the file

### 2.1 Be clear and detailed

A useful prompt should clearly state:

- the task;
- the intended result;
- the relevant context;
- the boundaries;
- the available files or resources;
- the required deliverables;
- the acceptance criteria.

“Detailed” does not mean “long.” Include details that affect execution and omit background that does not change the result.

### 2.2 Use positive and negative instructions

Tell the model both what to do and what to avoid when there is a realistic risk of misunderstanding.

Example:

```text
Reuse the existing feature engineering where appropriate.
Do not invent columns or silently change the target definition.
```

Negative instructions should be concrete. Avoid long lists of unlikely mistakes.

### 2.3 Use examples selectively

Examples are helpful when:

- a classification boundary is ambiguous;
- the required output has a special shape;
- naming conventions matter;
- several interpretations are plausible;
- the desired tone is difficult to describe.

Provide one or two representative examples rather than many repetitive ones.

### 2.4 Request structured handling of complex work

For complicated work, ask Claude to inspect, plan, implement, test, and summarize in a sensible sequence. Do not ask it to reveal private chain-of-thought. Ask for concise conclusions, assumptions, decisions, and verification results instead.

Good wording:

```text
Inspect the repository first. Briefly summarize what you found and your proposed approach, then implement it, run the relevant checks, and report the files changed and any unresolved issues.
```

### 2.5 Use XML-style sections when useful

XML-style tags can separate instructions, context, constraints, and output requirements. They are most valuable in longer prompts or prompts assembled programmatically.

Example:

```xml
<task>
Implement the missing model layer.
</task>

<context>
The old repository is reference-only. The new repository is the write target.
</context>

<constraints>
Do not invent schema fields. Keep the implementation readable.
</constraints>

<deliverables>
Working code, tests, and short usage examples.
</deliverables>
```

For a short, simple prompt, headings or bullets may be easier than XML. XML is an organizational technique, not a requirement.

### 2.6 Specify length and format

State what the response or artifact should look like when it matters.

Examples:

```text
Keep the explanation under 500 words.
Return JSON matching this schema.
Create the implementation in the repository, then provide a short summary.
Use Markdown with the headings Findings, Changes, Tests, and Open Issues.
```

## 3. Inferred lessons for prompting Claude Code

### 3.1 Describe the objective, not an imagined implementation

When Claude can inspect a repository, provide the business or technical outcome and the important constraints. Avoid forcing a folder structure, design pattern, package, or model type before the repository has been inspected, unless those choices are genuine requirements.

Weak:

```text
Create BaseModel, ModelFactory, four subclasses, six YAML files, and a registry.
```

Better:

```text
Inspect the existing structure and implement the simplest reusable modeling layer for the four required property and transaction combinations. Avoid duplicated logic and do not over-engineer.
```

### 3.2 Clearly distinguish read-only references from write targets

When multiple repositories or directories are involved, label their roles explicitly.

```text
REFERENCE ONLY:
C:\path\old-repo

REPOSITORY TO MODIFY:
C:\path\new-repo

Do not change the reference repository.
```

This is more reliable than mentioning both paths in prose.

### 3.3 Tell the agent to inspect before changing

If the required information exists in files, direct Claude to derive it from those files instead of guessing.

```text
Inspect the repository, configuration, data schema, and reference notebook before deciding on the architecture. Do not invent columns or targets that can be verified from the project.
```

### 3.4 State the autonomy level

Make clear whether Claude should only advise, prepare a plan, or actually modify files and run checks.

For implementation work:

```text
Do not stop after proposing a plan. Implement the changes, run the relevant tests or checks, and summarize the result.
```

For review-only work:

```text
Do not modify files. Return findings and a proposed patch plan only.
```

### 3.5 Define completion criteria

A strong coding prompt says what “done” means. Depending on the task, completion may require:

- implementation in the correct repository;
- preserved existing behavior;
- tests or smoke checks;
- readable code and comments;
- usage examples;
- documentation updates;
- a list of changed files;
- explicit unresolved blockers;
- no modifications outside scope.

### 3.6 Ask for verification, not just implementation

Useful language:

```text
Run the most relevant existing tests. If no tests exist, perform a minimal smoke test. Do not claim success without verification. Report exactly what you ran and whether it passed.
```

### 3.7 Give priority rules

When goals may conflict, rank them.

Example:

```text
Priorities, in order:
1. Correctness and consistency with the existing data pipeline.
2. No data leakage.
3. Readability and ease of experimentation.
4. Reuse without unnecessary abstraction.
5. Performance optimization only where justified.
```

### 3.8 Ask the model to surface uncertainty

```text
If something cannot be determined from the repositories, state the missing information and make the smallest reversible assumption. Do not silently invent project facts.
```

This is better than prohibiting all assumptions, because implementation sometimes requires a default. If assumptions are unacceptable, instruct the model to stop only when a blocker truly prevents safe progress.

## 4. Response style suggested by the source

The file describes a preference for focused, reasonably concise responses, high-level explanations by default, and lists when they improve clarity. Therefore:

- request a detailed report only when needed;
- ask for a brief summary after implementation;
- avoid asking for exhaustive narration of every action;
- request decision summaries rather than hidden reasoning;
- use clear headings for multifaceted deliverables.

Example:

```text
After implementation, give me:
1. a short summary of the approach;
2. files created or changed;
3. commands or tests run and their results;
4. the simplest usage example;
5. unresolved issues or assumptions.
```

## 5. Information usually not worth copying into a prompt

Do not normally copy the following material from the linked file into prompts:

- Claude's safety policy;
- internal refusal instructions;
- internal memory rules;
- hidden reasoning instructions;
- platform-specific tool schemas;
- mounted-directory details from another environment;
- skill paths from Anthropic's hosted environment;
- product descriptions unrelated to the task;
- instructions about how Claude should identify itself;
- large blocks of system-prompt wording.

Reasons:

1. These are platform-level instructions, not task requirements.
2. They may be obsolete or specific to a different Claude surface.
3. Repeating them consumes context.
4. User instructions cannot reliably override higher-priority system rules.
5. They can distract the model from the actual objective.

## 6. Anti-patterns

### 6.1 Overlong prompts full of speculative architecture

Avoid deciding every class, function, and directory before Claude sees the codebase.

### 6.2 Vague requests

Weak:

```text
Improve the models and make everything clean.
```

The model cannot know what “clean” or “improve” means.

### 6.3 Conflicting instructions

Avoid combinations such as:

```text
Do not make assumptions. Do not ask questions. Complete everything even if information is missing.
```

Prefer:

```text
Verify details from the repository. If a non-critical detail is missing, use the smallest reversible assumption and report it. Stop only for a genuine blocker.
```

### 6.4 Asking for a plan when implementation is wanted

If the model must act, explicitly say so.

### 6.5 Asking for chain-of-thought

Do not ask for private internal reasoning. Ask for:

- findings;
- rationale for key decisions;
- assumptions;
- validation results;
- concise step summaries.

### 6.6 Excessive persona prompting

A role can help, but task context and acceptance criteria are more valuable than grand personas.

Weak:

```text
You are the world's greatest machine-learning genius.
```

Better:

```text
Act as a pragmatic senior ML engineer. Prioritize correctness, leakage prevention, readability, and reproducibility.
```

## 7. Recommended prompt architecture

Use only the sections that add value.

```xml
<task>
What Claude must accomplish.
</task>

<context>
Relevant business context, repositories, files, and prior work.
</context>

<source_roles>
Which locations are read-only references and which may be modified.
</source_roles>

<requirements>
Functional requirements.
</requirements>

<constraints>
Important boundaries and prohibited changes.
</constraints>

<workflow>
Inspect, plan briefly, implement, test, and summarize.
</workflow>

<acceptance_criteria>
Observable conditions that define completion.
</acceptance_criteria>

<output>
Desired final response or artifact format and length.
</output>
```

For a small task, compress this into plain headings or bullets.

## 8. Meta-prompt for another LLM to generate Opus 5 prompts

The following can be passed to another LLM as its operating instruction.

```text
You create concise, execution-ready prompts for Claude Opus 5 and Claude Code.

Use the user's facts only. Do not invent repository contents, schemas, APIs, files, tools, or technical requirements.

For each request:
1. Identify the concrete objective and deliverables.
2. Separate context from instructions.
3. Clearly label read-only references and write targets.
4. Include important positive requirements and a short list of realistic prohibitions.
5. Tell Claude to inspect available files or repositories before making decisions when the answer exists there.
6. Specify whether Claude should advise, plan, review, or implement.
7. If implementation is requested, require implementation, verification, and a concise result summary.
8. Define observable acceptance criteria.
9. Specify output length or format only when useful.
10. Prefer the shortest prompt that preserves all material constraints.
11. Do not prescribe architecture prematurely unless the user explicitly requires it.
12. Do not ask for hidden chain-of-thought. Request concise findings, rationale, assumptions, and validation results instead.
13. Use XML-style sections only when they materially improve separation or machine readability. Otherwise use short headings and bullets.
14. Resolve conflicting instructions where possible. If critical information is missing, produce a prompt that tells Claude how to handle the uncertainty without silently inventing facts.

Return:
- Ready-to-paste prompt
- Optional assumptions or missing inputs, only if material

Do not add generic motivational language or repeat the same constraint in several forms.
```

## 9. Reusable short template

```text
Work on: [WRITE TARGET]

Reference only: [READ-ONLY LOCATION]
Do not modify the reference location.

Objective:
[DESIRED OUTCOME]

Inspect the relevant repository files and existing implementation before deciding on changes. Do not invent information that can be verified from the project.

Requirements:
- [REQUIREMENT 1]
- [REQUIREMENT 2]
- [REQUIREMENT 3]

Constraints:
- [CONSTRAINT 1]
- [CONSTRAINT 2]

Briefly summarize what you found and the approach you will take. Then implement the solution. Do not stop at the plan.

Verify the result using the relevant tests or a minimal smoke test. Finally report:
- what changed;
- files changed;
- checks run and results;
- simplest usage example;
- unresolved issues or assumptions.
```

## 10. Example adapted to a repository modeling task

```text
Work on this repository:
C:\path\InmoAI-lt

Reference repository, read-only:
C:\path\InmoAI

Reference notebook:
C:\path\InmoAI\models\reference_notebook.ipynb

Do not modify the reference repository.

Objective:
Implement a clean and reusable modeling layer in the working repository for apartments and houses, covering sale and rent. It must also support applying the relevant rental model to sale listings to estimate rental value and cap rate.

Inspect both repositories and the notebook before deciding on the structure. Verify targets, features, preprocessing, and existing conventions from the code. Do not invent schema fields or silently change the modeling definition.

Priorities:
1. consistency with the existing data pipeline;
2. leakage-safe training and evaluation;
3. simple training, loading, prediction, and experimentation;
4. readable, well-commented Python;
5. minimal duplication without over-engineering.

Briefly report your findings and proposed approach, then implement it in the working repository. Do not stop after the proposal.

Run relevant tests or a minimal smoke test. At the end, provide a concise summary of changed files, checks performed, assumptions, and simple examples for training, loading, prediction, rental estimation, and cap-rate calculation.
```

## 11. Quality checklist for generated prompts

Before returning a prompt, the prompt-writing LLM should verify:

### Objective

- Is the desired outcome explicit?
- Are all requested deliverables represented?

### Context

- Are paths, files, and repository roles accurate?
- Is reference-only material distinguished from editable material?

### Scope

- Is it clear what Claude may change?
- Are out-of-scope changes excluded where necessary?

### Execution

- Does the prompt say whether to inspect, plan, implement, or review?
- If implementation is requested, does it prevent Claude from stopping at a plan?

### Accuracy

- Does it prohibit silent invention of verifiable project facts?
- Does it explain how uncertainty should be handled?

### Verification

- Are tests, checks, or validation requested?
- Must Claude report what it actually verified?

### Output

- Is the desired response structure or artifact format clear?
- Is the requested level of detail proportionate?

### Efficiency

- Is every instruction necessary?
- Are constraints duplicated?
- Has speculative architecture been removed?

## 12. Practical rule of thumb

A strong Opus 5 prompt usually contains:

> **Objective + relevant context + boundaries + available evidence + completion criteria.**

For agentic coding work, add:

> **Inspect first + implement, do not only advise + verify + summarize.**

The linked file supports clear structure and explicit output requirements, but it does not imply that every prompt should be long, XML-heavy, or highly prescriptive.

## References

1. Third-party source analyzed: https://github.com/asgeirtj/system_prompts_leaks/blob/main/Anthropic/claude-opus-5.md
2. Official prompt-engineering overview referenced inside that source: https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview

## Source-derived claims used in this analysis

The linked file explicitly mentions clear and detailed instructions, positive and negative examples, stepwise reasoning, XML tags, and specified length or format as prompting techniques. It also characterizes Claude Code as an agentic coding tool and describes Claude as generally focused and concise. Its later sections contain environment-specific instructions for file creation, skill selection, filesystem restrictions, and internal thinking. Those latter details informed the distinction between reusable prompting lessons and platform-specific instructions that should not normally be copied into user prompts.
