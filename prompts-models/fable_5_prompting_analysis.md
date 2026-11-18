# Practical Prompting Guide for Claude Fable 5

## Purpose

This document converts the useful, prompt-relevant ideas found in the third-party `claude-fable-5.md` file into a standalone reference for another LLM. Its purpose is to help that LLM write effective prompts for Claude Fable 5, both in the claude.ai chat surface (files, artifacts, research) and for agentic or coding work, without reopening the source.

This is an analytical summary, not a reproduction of the source file.

## Source and reliability warning

**Analyzed source:**

- Local copy: `prompts-models/raw/claude-fable-5.md`
- Upstream repository: `asgeirtj/system_prompts_leaks` (exact path to be confirmed; presumed `Anthropic/claude-fable-5.md`)
- Accessed: 2026-10-14

The file presents itself as the claude.ai system prompt for Claude Fable 5. It is not official Anthropic documentation, so authenticity, completeness, version accuracy, and continued applicability cannot be guaranteed. Treat it as a behavioral clue, not as a contract.

Facts stated inside the file that frame this analysis:

- The prompt is dated Tuesday, June 9, 2026, with a stated knowledge cutoff of end of January 2026 (line 182).
- It runs with a 190,000-token budget (line 5) and `thinking_mode: auto` (line 3818).
- It describes Fable 5 as a Mythos-class tier above Opus (line 17), yet lists Opus 4.8, not Opus 5, among current models (line 23). This inconsistency with the Opus 5 source is a reason for caution about version claims in either file.

For current product behavior, supported features, APIs, pricing, or limits, consult official Anthropic documentation.

## Executive conclusion

Like the Opus 5 file, this is a set of instructions for Claude, not a user prompting manual. It repeats the same five prompting techniques Anthropic recommends (line 31):

1. Be clear and sufficiently detailed.
2. Use positive and negative examples when ambiguity matters.
3. Encourage stepwise handling of complicated work.
4. Use XML-style tags when they help separate content.
5. Specify the desired length and format.

What is new compared with the Opus 5 analysis is how much the file reveals about the **chat surface**: when Claude writes a file versus answers inline, how it formats prose, how many searches it runs, when it asks clarifying questions, and how it treats financial questions. Those defaults shape what a prompt must state explicitly to get the intended result.

## 1. What the linked file is about

The file groups its guidance into these areas:

- product identity, model lineup, and pointers to official docs;
- refusal and safety handling, including financial and legal advice;
- tone and formatting, with a strong prose-first default;
- user wellbeing and evenhandedness;
- knowledge cutoff and when to search;
- a memory system, past-chat search tools, and user preferences;
- persistent storage for artifacts and MCP connector suggestions;
- computer use: skills, file creation rules, output folders, artifacts, package management;
- a visual-routing checklist (connected tool, then file, then inline Visualizer);
- web search behavior, copyright limits, and citation format;
- image search;
- full tool schemas;
- instructions for artifacts that call the Anthropic API themselves;
- filesystem and network configuration.

Almost none of this should be copied into a task prompt. It is platform behavior Claude already receives.

## 2. Direct prompting guidance extracted from the file

### 2.1 Be clear and detailed

State the task, intended result, relevant context, boundaries, available files, deliverables, and acceptance criteria. "Detailed" means including what changes the outcome, not adding length.

### 2.2 Use positive and negative instructions

Say what to do and, where a realistic misreading exists, what to avoid.

```text
Summarize the uploaded memo for the investment committee.
Do not add recommendations that are not in the memo.
```

### 2.3 Use examples selectively

One or two examples help when a boundary is ambiguous, an output shape is unusual, or a tone is hard to describe. Many near-identical examples add little.

### 2.4 Request structured handling of complex work

Ask for a sensible sequence (inspect, plan, produce, verify, summarize). Request findings, assumptions, and rationale rather than private reasoning.

### 2.5 Use XML-style sections when useful

Tags such as `<task>`, `<context>`, `<constraints>`, and `<output>` help in long or programmatically assembled prompts. For short prompts, plain headings are enough.

### 2.6 Specify length and format

Because Fable's defaults are opinionated (see section 5), format instructions matter more here than for the Opus 5 analysis. Name the format, the structure, and roughly how long.

## 3. Inferred lessons for chat, file, and research work

### 3.1 Say whether you want a file or an inline answer

The file draws a firm line (lines 1051–1061): standalone pieces such as articles, blog posts, stories, and code over about ten lines become files; strategies, summaries, outlines, and explanations stay in chat. Tone and length do not move an item between buckets. Word documents are treated as expensive and produced only on a clear signal.

Prompt implication:

```text
Create a Markdown file with the full report.
```

or

```text
Answer inline in chat; do not create a file.
```

If a Word document is genuinely needed, ask for `.docx` explicitly.

### 3.2 Name the file type so the right skill is used

Claude is told to read the relevant skill guide before writing any file or code (line 1033). Naming the target format (pptx, xlsx, docx, pdf, a React component) helps it pick the right guidance. There is no need to tell Claude to read skills; it does so already.

### 3.3 Expect a delivered file plus a short note, not narration

Finished files go to an outputs folder and are presented with a brief summary (lines 1079, 1094–1102). Long files are built iteratively. If you want an explanation of the content as well, ask for it; the default is minimal post-amble.

### 3.4 Know when a response becomes an artifact

Artifacts are used for code over 20 lines, standalone documents over 20 lines or 1,500 characters, and content meant for reuse; lists, tables, and short answers stay inline regardless of length (lines 1121–1137). If you want a table as a downloadable file, say so.

### 3.5 Visual requests follow a fixed routing order

Before producing any visual, Claude checks whether a visual is needed at all, then whether a connected tool fits, then whether a file was requested, and only then uses the inline Visualizer (lines 1202–1220). Prompt implications:

- Use "show", "chart", or "diagram" when you want a visual; plain questions get prose.
- Use "save as `name.html`" when you want a file rather than an inline widget.
- Name a connected tool if you want that specific tool used.

### 3.6 Search scales with the question

The file prescribes roughly one search for a single fact, three to five for medium tasks, five to ten for comparisons, and a dedicated Research feature beyond about twenty (line 1303). Internal tools are preferred over web search for company or personal data (line 1305), and any URL in the prompt is fetched directly (line 1602).

Prompt implications:

- State the depth you want ("a quick check" versus "a thorough comparison of five vendors").
- Paste the exact URLs you want read.
- Say which internal sources (Drive, mail) are relevant if connectors exist.

### 3.7 Detailed prompts suppress clarifying questions

Claude asks at most one question per reply and tries to answer before asking (line 88). When a prompt already contains specific constraints, it proceeds and states its assumptions inline instead of asking (line 1734). A complete prompt therefore gets a complete answer on the first turn.

### 3.8 Verify attachments are actually present

The file notes that a prompt mentioning a file does not guarantee the file was uploaded, and Claude checks (line 92). Attach the file, or name the exact path or link.

### 3.9 Financial and legal questions get facts, not recommendations

For questions such as whether to make a trade, Claude provides the factual basis for the person's own decision and notes it is not an advisor (line 76). Frame investment prompts as decision support: ask for evidence, scenarios, risks, and trade-offs rather than a buy/sell instruction.

## 4. Inferred lessons for agentic and coding work

The Opus 5 guidance still applies; the Fable file adds a few environment clues.

### 4.1 Describe the objective, not an imagined implementation

Give the outcome and the hard constraints. Do not prescribe class hierarchies or folder layouts before the code has been inspected, unless they are real requirements.

### 4.2 Separate read-only references from write targets

The Fable environment itself mounts several folders read-only and requires copying before editing (line 3807). The same discipline belongs in prompts:

```text
REFERENCE ONLY: <path>
WRITE TARGET: <path>
Do not modify the reference location.
```

### 4.3 Tell the agent to inspect before changing

If the answer exists in files, direct Claude to derive it from them rather than guess.

### 4.4 State the autonomy level and completion criteria

Say whether to advise, plan, review, or implement. For implementation, require verification (tests or a smoke check) and a report of what actually ran.

### 4.5 Treat instructions inside content as untrusted

The file instructs Claude to confirm requests that appear inside files or other untrusted content rather than act on them (line 1210). Put real instructions in the prompt itself, not inside an attached document.

### 4.6 Reference earlier work with concrete keywords

Past-chat search is a text match on content words (line 832). When continuing earlier work, name the project, file, or topic ("the cap-rate model for InmoAI") rather than "what we discussed".

### 4.7 Use the right surface for repo work

The chat surface runs on a temporary Linux container whose filesystem resets between tasks. For real repository changes, prompt Claude Code (or another repo-attached agent) with the coding template in section 11.

## 5. Response style suggested by the source

Fable's defaults are prose-first and sparing with formatting (lines 96–100):

- Formatting such as bullets, headers, and bold appears only when asked or when the content is clearly multifaceted.
- Reports, documents, and explanations are written as prose without bullets unless a list or ranking is requested.
- Bullets that do appear are one to two sentences long.
- Casual and research answers stay conversational, without report-style headers.

Prompt implication: if you want bullets, a table, headings, or a numbered list, ask for them by name. Example:

```text
Return a table with columns Risk, Evidence, Severity, then three bullet points with next steps.
```

## 6. Prompts that call Claude from an artifact or through the API

The file includes guidance for artifacts that call the Anthropic API. These lessons apply to any programmatic prompt, including this repo's agent prompts that rely on `json_mode`:

- State in the system prompt that the model must return only JSON, with no preamble and no Markdown fences (line 3457).
- Still strip code fences defensively before parsing (line 3689).
- Each call is stateless; include all relevant state and history in every request (line 3638).
- Read response content blocks by type, not by position (line 3492).

## 7. Information usually not worth copying into a prompt

Do not normally copy into prompts:

- safety, wellbeing, or copyright policy;
- memory rules, forbidden memory phrases, or preference-handling logic;
- tool schemas and connector routing rules;
- mount paths, output folders, or package-manager flags;
- citation index syntax;
- product lineup or identity statements;
- large blocks of system-prompt wording.

These are platform-level, may be outdated or surface-specific, cost context, and cannot be overridden reliably by user text.

## 8. Anti-patterns

### 8.1 Overlong prompts with speculative architecture

Do not decide every class and folder before Claude sees the codebase.

### 8.2 Vague deliverables

Weak:

```text
Make a doc about our Q3 portfolio.
```

Better:

```text
Create a Markdown report (about 800 words) summarizing Q3 portfolio performance from the attached CSV, with a returns table and a short risks section.
```

### 8.3 Expecting bullets or headers without asking

Fable defaults to prose. If the structure matters, specify it.

### 8.4 Asking for long verbatim quotes from sources

Copyright limits cap quotes at under 15 words and one quote per source (line 1280). Ask for paraphrased findings with links instead.

### 8.5 Conflicting instructions

Avoid "do not assume, do not ask, finish everything". Prefer: "Verify from the provided material; make the smallest reversible assumption for non-critical gaps and state it; stop only for a genuine blocker."

### 8.6 Asking for chain-of-thought

Ask for findings, rationale for key decisions, assumptions, and validation results instead.

### 8.7 Asking for a trade decision

Asking "should I buy X" yields facts rather than a recommendation. Ask for the evidence, scenarios, and risks you need to decide yourself.

### 8.8 Excessive persona prompting

A concise role helps; grand personas do not. Task context and acceptance criteria matter more.

## 9. Recommended prompt architecture

Use only the sections that add value.

```xml
<task>
What Claude must accomplish.
</task>

<context>
Relevant background, attached files, links, prior work (named concretely).
</context>

<source_roles>
Which locations are read-only references and which may be modified.
</source_roles>

<requirements>
Functional or content requirements.
</requirements>

<constraints>
Boundaries, prohibitions, and sources to use or avoid.
</constraints>

<workflow>
Inspect, plan briefly, produce, verify, summarize.
</workflow>

<acceptance_criteria>
Observable conditions that define completion.
</acceptance_criteria>

<output>
Delivery mode (inline or file), file type, structure (prose, bullets, table, headings), and length.
</output>
```

For small tasks, compress this into a few plain lines.

## 10. Meta-prompt for another LLM to generate Fable 5 prompts

```text
You create concise, execution-ready prompts for Claude Fable 5, in claude.ai chat or in an agentic coding tool.

Use the user's facts only. Do not invent files, schemas, APIs, URLs, tools, or requirements.

For each request:
1. Identify the concrete objective and deliverables.
2. Decide the surface: chat answer, chat file deliverable, or repository work in a coding agent.
3. Separate context from instructions.
4. For chat work, state the delivery mode (inline or file), the file type if any, and the structure (prose, bullets, table, headings), because Fable defaults to prose and minimal formatting.
5. For research, state the depth wanted, list the exact URLs to read, and ask for paraphrased findings with sources rather than long quotes.
6. For financial or legal topics, frame the request as decision support (evidence, scenarios, risks), not a direct recommendation.
7. For repository work, label read-only references and write targets, tell Claude to inspect before deciding, specify the autonomy level, and require verification and a short result summary.
8. Include the constraints that matter and a short list of realistic prohibitions.
9. Provide enough constraints that Claude can proceed without clarifying questions; tell it to state assumptions inline.
10. Define observable acceptance criteria.
11. Do not ask for hidden chain-of-thought; request findings, rationale, assumptions, and validation results.
12. Use XML-style sections only when they improve separation; otherwise use short headings.
13. Do not copy platform policy, tool schemas, or system-prompt text into the prompt.
14. Prefer the shortest prompt that preserves all material constraints.

Return:
- Ready-to-paste prompt
- Optional missing inputs or assumptions, only if material
```

## 11. Reusable short templates

### 11.1 Chat deliverable

```text
Objective: [DESIRED OUTCOME]

Inputs: [ATTACHED FILES / EXACT URLS]

Deliver as: [inline answer | Markdown file | .docx | .xlsx | .pptx], about [LENGTH].
Structure: [prose | bullets | table with columns ... | headings ...].

Requirements:
- [REQUIREMENT 1]
- [REQUIREMENT 2]

Constraints:
- Use only the provided inputs and [ALLOWED SOURCES].
- Paraphrase sources and link them; no long quotes.

If something is missing, make the smallest reasonable assumption and state it inline.
```

### 11.2 Coding or agentic work

```text
Work on: [WRITE TARGET]
Reference only: [READ-ONLY LOCATION]. Do not modify it.

Objective: [DESIRED OUTCOME]

Inspect the relevant files before deciding on changes. Do not invent facts that can be verified from the project.

Requirements:
- [REQUIREMENT 1]
- [REQUIREMENT 2]

Constraints:
- [CONSTRAINT 1]
- [CONSTRAINT 2]

Briefly state your findings and approach, then implement. Do not stop at the plan.
Verify with the relevant tests or a minimal smoke test, and report: what changed, files changed, checks run and results, and unresolved assumptions.
```

## 12. Example adapted to this repository

A research prompt for the claude.ai chat surface that feeds the investment committee:

```text
Objective: Prepare decision-support research on whether rising euro-area rates over the next 12 months materially affect European bank equities.

Inputs:
- Attached: portfolio_sample.csv (current holdings and weights).
- Read these pages: [EXACT URL 1], [EXACT URL 2].

Scope: A thorough comparison; search as needed for current ECB policy and recent bank earnings. Prefer primary sources (central bank, company filings).

Deliver as a Markdown file of about 900 words with:
- a one-paragraph summary;
- a table with columns Driver, Evidence, Direction, Confidence;
- a short risks section in bullets;
- a source list with links.

Constraints:
- This is decision support only: present evidence, scenarios, and risks; do not give buy or sell instructions.
- Paraphrase sources; no quotes longer than a short phrase.
- Use only holdings that appear in the CSV.

If a figure cannot be verified, say so rather than estimating silently.
```

## 13. Quality checklist for generated prompts

### Objective

- Is the desired outcome explicit?
- Are all deliverables represented?

### Surface and delivery

- Is it clear whether this is a chat answer, a file, or repository work?
- Is the file type named when a file is wanted?
- Is the structure (prose, bullets, table, headings) stated where it matters?

### Context

- Are files attached or paths and URLs given exactly?
- Is earlier work referenced by concrete name rather than "what we discussed"?
- Are read-only references distinguished from write targets?

### Scope and autonomy

- Is it clear what Claude may change?
- Does the prompt say whether to advise, plan, review, or implement?

### Accuracy

- Does it prohibit inventing verifiable facts?
- Does it explain how to handle uncertainty?
- Are financial or legal requests framed as decision support?

### Research

- Is the expected search depth stated?
- Are paraphrase and source links requested instead of long quotes?

### Verification

- For implementation, are tests or checks requested and must results be reported?

### Efficiency

- Is every instruction necessary?
- Has platform policy or system-prompt text been left out?

## 14. Practical rule of thumb

A strong Fable 5 prompt usually contains:

> **Objective + inputs + delivery mode and format + boundaries + completion criteria.**

For agentic coding work, add:

> **Inspect first + implement, do not only advise + verify + summarize.**

## 15. Differences from the Opus 5 guide

This comparison is against the existing analysis in `prompts-models/opus_5_prompting_analysis.md`, not against the raw Opus 5 source, which is not in this workspace.

| Dimension | Opus 5 source (per the Opus analysis) | Fable 5 source | Prompt adjustment for Fable |
|---|---|---|---|
| Surface | Claude plus Claude Code, agentic coding in a repository | claude.ai web/mobile chat with a temporary Linux container (lines 1065–1072) | State whether you want a chat answer, a file, or repo work; use a coding agent for real repo changes |
| Model positioning | Opus 5 | Mythos-class tier above Opus; lists Opus 4.8 as current, not Opus 5 (lines 17, 23) | Treat version claims in both files with caution |
| Formatting default | Focused, concise; lists when they aid clarity | Prose-first; no bullets in reports or documents unless asked; bullets 1–2 sentences (lines 96–100) | Ask for bullets, tables, or headings by name |
| File output | Repository write targets | File-versus-inline rule, outputs folder, file presentation step; Word files are costly (lines 1051–1102) | Name the format and say "create a file" or "answer inline" |
| Skills | Skill selection for file work | Reading the relevant skill guide is mandatory before any file or code (line 1033) | Name the file type; no need to mention skills |
| Clarifying questions | Smallest reversible assumption | At most one question; none when the prompt is detailed, assumptions stated inline (lines 88, 1734) | Front-load constraints to get a complete first answer |
| Search and quotes | Not emphasized | Search counts scaled to complexity; quotes under 15 words, one per source (lines 1280, 1303) | State research depth; ask for paraphrase with links |
| Reasoning | Internal thinking instructions | `thinking_mode: auto` (line 3818) | Ask for rationale and assumptions, not hidden reasoning |
| Memory and history | Not covered | Memory plus past-chat search matched on content words (lines 193–945, 832) | Reference earlier work by concrete names |
| Financial and legal | Not covered | Facts for the person's own decision, not confident recommendations (line 76) | Frame investment prompts as decision support |
| Write location | User's repository | Temporary container; several folders read-only (line 3807) | Keep repo work in Claude Code; label read-only sources explicitly |

When switching a prompt from Opus 5 to Fable 5 in chat:

1. Add an explicit delivery line: inline, Markdown file, or a named office format.
2. Add an explicit structure line if you want anything other than prose.
3. Put all constraints up front so Claude proceeds without clarifying questions.
4. Replace "recommend a trade" with "lay out evidence, scenarios, and risks".
5. Keep implementation prompts for repositories in Claude Code; the chat container is not your repo.

## References

1. Third-party source analyzed: `asgeirtj/system_prompts_leaks` repository, Fable 5 system prompt (exact path to be confirmed); local copy `prompts-models/raw/claude-fable-5.md`.
2. Official prompt-engineering overview referenced inside that source: https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview
3. Companion analysis: `prompts-models/opus_5_prompting_analysis.md`.

## Source-derived claims used in this analysis

- Model positioning and lineup: lines 17, 23.
- The five prompting techniques: line 31.
- Financial and legal questions answered with facts, not recommendations: line 76.
- At most one clarifying question per reply: line 88.
- Claude checks whether a mentioned file is actually present: line 92.
- Prose-first formatting and bullet rules: lines 96–100.
- Knowledge cutoff and prompt date: line 182.
- Past-chat search uses content keywords: line 832.
- Mandatory skill reading before file or code work: line 1033.
- File-versus-inline rules and Word cost: lines 1051–1061.
- Output folder, file strategy, and file sharing: lines 1079, 1094, 1102.
- Artifact criteria: lines 1121–1137.
- Visual routing and untrusted-content caution: lines 1202–1220.
- Copyright quote limits: line 1280.
- Search scaling and internal-tool priority: lines 1303–1305.
- URLs in the prompt are fetched directly: line 1602.
- Detailed prompts proceed without clarifying questions: line 1734.
- API-in-artifact guidance (JSON-only, block types, stateless calls, fence stripping): lines 3457, 3492, 3638, 3689.
- Read-only mounts: line 3807.
- Thinking mode: line 3818.
