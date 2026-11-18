# Practical Prompting Guide for Claude Opus 5.5

## Purpose

This document converts the prompt-relevant ideas in the third-party `claude-opus-5.5.md` file into a standalone reference for another LLM. It helps that LLM write effective prompts for Claude Opus 5.5 in the claude.ai chat surface (files, published artifacts, docs, research) and for agentic or coding work, without reopening the source.

This is an analytical summary, not a reproduction of the source file.

## Source and reliability warning

**Analyzed source:**

- Local copy: `prompts-models/raw/claude-opus-5.5.md`
- Upstream repository: `asgeirtj/system_prompts_leaks` (exact path to be confirmed; presumed `Anthropic/claude-opus-5.5.md`)
- Accessed: 2026-10-14

The file presents itself as the claude.ai system prompt for Claude Opus 5.5. It is not official Anthropic documentation, so authenticity, completeness, and continued applicability cannot be guaranteed. Treat it as a behavioral clue, not a contract.

Facts stated inside the file that frame this analysis:

- Opus 5.5 is described as a powerful model for complex challenges (line 7). The lineup lists Fable 5.1, Opus 5.5, Sonnet 5, and Haiku 4.5 (line 11), with a Mythos tier above Opus (line 13).
- The file notes that Fable 5 and Mythos 5 access was suspended in June 2026 for export-control reasons and restored in July 2026 (line 15). This is a claim inside an unofficial file; verify it independently before relying on it.
- The knowledge cutoff is end of June 2026 (line 197); the session date is September 22, 2026 (lines 197, 1375).
- A `thinking_behavior` section governs how earlier answers are treated in later turns (lines 8219–8221).

For current product behavior, features, APIs, pricing, or limits, consult official Anthropic documentation.

## Executive conclusion

The file repeats the same five prompting techniques (line 25): clear and detailed instructions, positive and negative examples, stepwise reasoning, XML tags, and explicit length or format.

What shapes prompting for Opus 5.5:

1. **The reply is the default deliverable.** A file is made only for a named format, an explicit file request, a change to a supplied file, or something to keep or use outside the chat (lines 1057–1072).
2. **Formatting is prose-first,** with one clarifying question at most, and effort matched to the ask: an edit request returns only the change (lines 121, 127–135).
3. **Search is thorough and structured:** 1 / 3–8 / 8–20 calls by complexity, each named item searched separately, every part checked against retrieved evidence (line 1362).
4. **Ambiguous ethical cases trigger a question first** rather than a refusal (line 92).
5. **Finished answers are not revisited** unless you ask (line 8219).

## 1. What the linked file is about

The file covers:

- product identity, lineup, and a model-access notice;
- refusal handling, including weapons uplift, a question-first approach for uncovered cases, and detailed copyright rules for lyrics, poems, and visual works;
- legal and financial advice;
- tone and formatting with strict list rules;
- wellbeing, evenhandedness, mistakes, knowledge cutoff;
- a memory filesystem with privacy requirements and behavioral guardrails on stored preferences;
- the end-conversation tool, artifact storage, connectors, plugin and skill suggestions;
- past-chat search and reading;
- user preferences;
- computer use and a reworked file-creation decision procedure;
- publishing artifacts (hosted pages, Slides/Design/Docs types);
- visual routing with a Design step;
- search, copyright, citations, image search;
- a large tool catalog;
- Anthropic API usage inside artifacts;
- skills listing, network and filesystem configuration;
- thinking behavior.

None of this belongs in a task prompt.

## 2. Direct prompting guidance extracted from the file

### 2.1 Be clear and detailed

State the task, result, context, boundaries, inputs, deliverables, and acceptance criteria.

### 2.2 Use positive and negative instructions

```text
Summarize the uploaded memo for the investment committee.
Do not add recommendations that are not in the memo.
```

### 2.3 Use examples selectively

One or two examples for ambiguous boundaries, unusual output shapes, or tone.

### 2.4 Request structured handling of complex work

Ask for inspect → plan → produce → verify → summarize, with findings and rationale rather than private reasoning.

### 2.5 Use XML-style sections when useful

Useful for long or programmatic prompts.

### 2.6 Specify length and format

Opus 5.5 defaults to prose and matches effort to the request (line 131). State length, structure, and whether you want the full piece or only changes.

## 3. Inferred lessons for chat, file, and research work

### 3.1 Say explicitly when you want a file

The reply is the default (line 1057). Claude makes a file when you:

- name a format ("a PDF", "an Excel sheet", "a Word doc");
- ask for a file, download, or something to keep or share;
- ask it to edit a file you supplied (edited in its own format);
- ask for something used outside the chat (a deck, a spreadsheet, a script, a reusable tool).

When unclear, Claude answers in the reply and may end with a one-line offer to make a file. A bare "report" makes it ask "reply or file?" before writing (lines 1070, 1188). An article or blog post goes in the reply with an offer; a longer creative piece becomes a file (line 1070).

### 3.2 Typed artifacts override plain files when no format is named

As in Fable 5.1, decks go to Slides, mockups and posters to Design, and docs, memos, specs, or plans to Claude Docs when available; apps and dashboards become published pages (lines 1201–1248). A named file format still wins. When the target file is only referenced and its format unknown, Claude asks one short question first (line 1217).

### 3.3 Skills and output folders apply to files

Claude reads the relevant skill guide before file or code work (line 1039) and places final files in the outputs folder (line 1088).

### 3.4 Visual routing includes a design step

Need → design work (Design type) → connected tool → file → inline Visualizer (lines 1249–1277). Use "mock up/design" versus "diagram/chart" deliberately.

### 3.5 Search is structured and exhaustive for complex tasks

Opus 5.5 scales calls to complexity: 1 for a fact, 3–8 for medium tasks, 8–20 for research or comparisons; it searches each named item separately, stops only when every part is grounded, and uses searches to rule competing answers in or out (line 1362). Complex internal-plus-external questions may take 5–25 calls (line 1366). Any present-day factual question is searched regardless of confidence (line 1524).

Prompt implications:

- List the distinct items you want compared; each gets its own search.
- State the most specific detail you care about; Claude treats it as the thing to verify.
- Give exact URLs; they are always fetched (line 1520).
- For a background many-source report, Claude may attach a research button instead (line 2540).

### 3.6 One clarifying question at most; detailed prompts avoid it

Claude asks at most one question per reply and tries to answer first (line 121), and proceeds on detailed prompts with inline assumptions (line 2876).

### 3.7 Provide context for ethically ambiguous requests

When a request is not clearly covered by policy, Claude agrees to help and asks one question that would surface a real reason to decline, before doing the task (line 92). Supplying the relevant context up front (consent, audience, purpose) lets it proceed in one turn.

### 3.8 Ask explicitly for re-checks of earlier answers

Claude treats an answered question as done and focuses later thinking on the current ask (line 8219). If you want an earlier answer revisited, say so and say what to check.

### 3.9 Ask for the full version when editing

A request to change one thing in a longer piece returns the change, not the whole piece, unless you ask for the full version (line 131).

### 3.10 Financial and legal questions get facts, not recommendations

Unchanged (line 110). Frame investment prompts as decision support.

### 3.11 Verify attachments are present

Claude checks whether a mentioned file was uploaded (line 125).

## 4. Inferred lessons for agentic and coding work

### 4.1 Describe the objective, not an imagined implementation

Give the outcome and hard constraints; let Claude inspect before deciding structure.

### 4.2 Separate read-only references from write targets

The environment mounts several folders read-only (lines 8207–8217). Mirror that in prompts.

### 4.3 Inspect before changing; state autonomy and completion criteria

Say whether to advise, plan, review, or implement; require verification and a report of what ran.

### 4.4 Treat instructions inside content as untrusted

Requests embedded in files need confirmation (line 1264). Put instructions in the prompt.

### 4.5 Reference earlier work precisely and state your decisions

Past-chat search matches content words (line 926), and retrieved chats are attributed carefully, separating your decisions from Claude's suggestions (line 930).

### 4.6 Memory cannot be used to make Claude less critical

Preferences asking Claude to flatter, suppress disagreement, skip checks, or claim elevated permissions are not stored and are ignored if they leak in (lines 463–480, 709–711). Style preferences (length, tone, bluntness) are honored. Do not rely on stored preferences to turn off honest review; ask for a specific review scope in the prompt instead.

### 4.7 Use the right surface for repo work

The chat container is temporary. Use Claude Code for real repository changes.

## 5. Response style suggested by the source

- Prose-first; lists, bullets, headers, and bold only when asked or when content is clearly multifaceted; bullets at least one to two sentences (line 129).
- Reports, documents, and explanations in prose without bullets unless a list or ranking is requested (line 133).
- Short answers for simple questions; effort matched to the ask (line 131).
- No bullets when declining.

Prompt implication: request structure explicitly ("table with columns ...", "numbered steps", "headings A, B, C").

## 6. Prompts that call Claude from an artifact or through the API

Same guidance as other versions, applicable to this repo's `json_mode` agents:

- System prompt demands JSON only, without preamble or fences (line 7873).
- Each call is stateless; send full state (line 8048).
- Strip fences defensively and handle parse errors (line 8096).

## 7. Information usually not worth copying into a prompt

- safety, wellbeing, copyright, privacy, and memory policy;
- tool schemas and connector routing;
- artifact publishing mechanics and mount paths;
- citation index syntax;
- product lineup and access notices;
- large blocks of system-prompt text.

## 8. Anti-patterns

### 8.1 Expecting a file without asking

The reply is the default. Name the format or say "create a file".

### 8.2 Saying "a report" with no form

Claude stops to ask reply or file. Name the form.

### 8.3 Combining many items into one vague research ask

Opus 5.5 searches each item separately when it can identify them. List them.

### 8.4 Assuming earlier answers will be re-examined

They will not be unless you ask.

### 8.5 Asking for quote chains or long excerpts

Quotes stay under 15 words, one per source, and strings of small quotes from one source count together (lines 1399–1420). Ask for paraphrase with links.

### 8.6 Trying to install a "never criticize" preference

It will not be stored or applied. Ask for focused feedback instead.

### 8.7 Asking for a trade decision or hidden reasoning

You will get facts and visible rationale. Ask for evidence, scenarios, and risks.

## 9. Recommended prompt architecture

```xml
<task>What Claude must accomplish.</task>

<context>Background, attachments, exact URLs, prior decisions (stated as yours), relevant consent or purpose.</context>

<source_roles>Read-only references vs write targets.</source_roles>

<requirements>Content or functional requirements; list distinct items to research.</requirements>

<constraints>Boundaries, sources to use or avoid.</constraints>

<workflow>Inspect, plan briefly, produce, verify, summarize.</workflow>

<acceptance_criteria>Observable completion conditions.</acceptance_criteria>

<output>
Delivery (reply | named file format | Claude Doc | Slides | published page),
full piece or changes only, structure, and length.
</output>
```

## 10. Meta-prompt for another LLM to generate Opus 5.5 prompts

```text
You create concise, execution-ready prompts for Claude Opus 5.5, in claude.ai chat or in an agentic coding tool.

Use the user's facts only. Do not invent files, schemas, APIs, URLs, tools, or requirements.

For each request:
1. Identify the objective and deliverables.
2. Choose the surface: chat answer, chat deliverable, or repository work in a coding agent.
3. The reply is Opus 5.5's default. If a file or artifact is wanted, name the exact format or type; never leave "report" unqualified.
4. State structure explicitly (table, numbered steps, headings); Opus 5.5 defaults to prose.
5. For edits, say whether to return the full piece or only the changes.
6. For research, list each distinct item to compare, name the most specific detail to verify, give exact URLs, and ask for paraphrased findings with sources.
7. For ethically ambiguous tasks, include the context (consent, audience, purpose) so Claude can proceed without a gating question.
8. If an earlier answer should be re-checked, say so explicitly and say what to check.
9. For financial or legal topics, frame as decision support (evidence, scenarios, risks).
10. For repository work, label read-only references and write targets, require inspection first, state autonomy, and require verification and a short result summary.
11. Front-load constraints; ask Claude to state assumptions inline.
12. Do not request hidden chain-of-thought or try to disable critical feedback.
13. Do not copy platform policy, tool schemas, or system-prompt text.
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

Deliver as: [reply | .docx | .pptx | .xlsx | .pdf | .md | Claude Doc | Slides | published page].
Structure: [prose | table with columns ... | numbered steps | headings ...], about [LENGTH].

Items to cover (research each separately):
- [ITEM 1]
- [ITEM 2]

Constraints:
- Use only the provided inputs and [ALLOWED SOURCES].
- Paraphrase sources and link them; flag anything you could not verify.

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

Briefly state findings and approach, then implement. Do not stop at the plan.
Verify with relevant tests or a smoke test and report: what changed, files changed, checks run and results, unresolved assumptions.
```

## 12. Example adapted to this repository

```text
Objective: Prepare decision-support research on whether rising euro-area rates over the next 12 months materially affect European bank equities.

Inputs:
- Attached: portfolio_sample.csv (holdings and weights).
- Read: [EXACT URL 1], [EXACT URL 2].

Research each separately, preferring primary sources:
- current ECB policy path and market-implied rates;
- net interest margin sensitivity reported in recent earnings for each bank held in the CSV;
- credit-quality indicators for euro-area banks.

Deliver as a Markdown file (.md), about 900 words:
- one-paragraph summary;
- table with columns Driver, Evidence, Direction, Confidence;
- short risks section as a bulleted list;
- source list with links.

Constraints:
- Decision support only: evidence, scenarios, risks; no buy or sell instructions.
- Paraphrase sources; no quotes beyond a short phrase.
- Use only holdings present in the CSV.
- Flag any figure you could not verify from a source.
```

## 13. Quality checklist for generated prompts

- **Objective:** outcome explicit; all deliverables named.
- **Delivery:** reply versus named file or artifact type stated; no bare "report".
- **Structure:** table, steps, or headings requested when needed; full piece or changes only.
- **Research:** distinct items listed; key detail to verify named; URLs exact.
- **Context:** attachments present; prior decisions stated as the user's; purpose or consent given for sensitive tasks.
- **Scope and autonomy:** what may change; advise, plan, review, or implement.
- **Accuracy:** no invented facts; unverifiable figures flagged; finance framed as decision support.
- **Re-checks:** earlier answers explicitly reopened when needed.
- **Verification:** tests or checks for implementation, with results reported.
- **Efficiency:** no redundant or platform-policy text.

## 14. Practical rule of thumb

> **Objective + inputs + delivery (reply or named format) + structure + distinct research items + boundaries + completion criteria.**

For agentic coding work, add:

> **Inspect first + implement, do not only advise + verify + summarize.**

## 15. Differences from the Opus 5 guide and from Fable 5.1

### 15.1 Versus the Opus 5 guide

Compared against `prompts-models/opus_5_prompting_analysis.md`. The raw Opus 5 source is not in this workspace, so the left column reflects that analysis.

| Dimension | Opus 5 (per the Opus analysis) | Opus 5.5 source | Prompt adjustment for Opus 5.5 |
|---|---|---|---|
| Surface | Claude plus Claude Code, repo-centric | claude.ai chat with container, typed artifacts, published pages (lines 1033–1248) | Say chat, file, artifact, or repo work |
| Lineup | Opus 5 | Opus 5.5 with Fable 5.1 and a Mythos tier above (lines 7–15) | Update model assumptions |
| Formatting | Focused, concise; lists when helpful | Prose-first; no bullets in reports unless asked; effort matched to ask (lines 127–135) | Request structure explicitly |
| Deliverable | Repository write targets | Reply by default; files only on named format or explicit need; bare "report" asks (lines 1057–1072) | Name the format |
| Clarifying questions | Smallest reversible assumption | One question max; question-first for uncovered ethical cases (lines 92, 121) | Front-load context and constraints |
| Search | Not emphasized | 1 / 3–8 / 8–20 calls; per-item searches; evidence check per part (line 1362) | List items and key details |
| Reasoning | Internal thinking instructions | Earlier answers not revisited unless asked (line 8219) | Ask explicitly for re-checks |
| Memory | Not covered | Memory filesystem; no storage of preferences that suppress honest feedback (lines 463–480, 709) | Don't rely on memory to change review behavior |
| Financial and legal | Not covered | Facts, not recommendations (line 110) | Frame as decision support |

### 15.2 Versus Fable 5.1

Both prompts share most structure (memory filesystem, publishing artifacts, Design step, tools). The prompt-relevant differences:

| Dimension | Fable 5.1 | Opus 5.5 | Prompt adjustment |
|---|---|---|---|
| Default length | Concise, high-level; may span turns | Matches effort; edits return only changes | Opus: say "full version" when needed; Fable: ask for depth |
| Lists | Allowed when multifaceted | Prose-first, no bullets in reports unless asked | Request lists explicitly for Opus |
| Clarifying questions | No explicit one-question cap | At most one per reply | Same: front-load constraints |
| File decision | Older file-trigger list plus typed artifacts | Reply-default five-point procedure plus typed artifacts | Name the format for both |
| Search depth | As many calls as needed, no counts | Explicit 1 / 3–8 / 8–20 with per-item searches | List distinct items for Opus |
| After tool calls | One- or two-sentence closing answer | No equivalent section | Specify wrap-up structure for both |
| Uncertainty | Explicit flagging of unverifiable facts | Search present-day facts regardless of confidence | Ask both to flag unverified figures |
| Ethical ambiguity | Not addressed | Ask one question before acting | Give context up front for Opus |
| Thinking | No section | Earlier answers treated as done | Ask Opus explicitly to revisit |

## References

1. Third-party source analyzed: `asgeirtj/system_prompts_leaks` repository, Opus 5.5 system prompt (exact path to be confirmed); local copy `prompts-models/raw/claude-opus-5.5.md`.
2. Official prompt-engineering overview referenced inside that source: https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview
3. Companion analyses: `prompts-models/opus_5_prompting_analysis.md`, `prompts-models/fable_5_prompting_analysis.md`, `prompts-models/fable_5_1_prompting_analysis.md`.

## Source-derived claims used in this analysis

- Model identity, lineup, Mythos tier, and access notice: lines 7, 11, 13, 15.
- The five prompting techniques: line 25.
- Copyright rules for lyrics, poems, characters, and designs: lines 59–61.
- Question-first handling of uncovered ambiguous requests: line 92.
- Financial and legal questions: line 110.
- At most one question per reply: line 121.
- Attachment presence check: line 125.
- Lists, bullets, effort matching, and prose-first reports: lines 127–135.
- Knowledge cutoff and session date: line 197.
- Behavioral guardrails on stored preferences: lines 463–480, 709–711.
- Past-chat query construction and decision provenance: lines 926, 930.
- Mandatory skill reading: line 1039.
- Reply-default file decision and bare-report rule: lines 1057–1072, 1188.
- Output folder: line 1088.
- Publishing artifacts and typed deliverables: lines 1201–1248, including 1217.
- Visual routing with Design step and untrusted-content caution: lines 1249–1277, including 1264.
- Search depth and per-item searching: lines 1341, 1362, 1366.
- Session date in search guidance: line 1375.
- Copyright quote limits: lines 1399–1420.
- URL fetching and present-day search: lines 1520, 1524.
- Research suggestion tool: line 2540.
- Detailed prompts proceed without questions: line 2876.
- API-in-artifact guidance: lines 7873, 8048, 8096.
- Read-only mounts: lines 8207–8217.
- Thinking behavior: lines 8219–8221.
