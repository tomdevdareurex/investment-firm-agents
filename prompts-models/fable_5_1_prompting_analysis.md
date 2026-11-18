# Practical Prompting Guide for Claude Fable 5.1

## Purpose

This document converts the prompt-relevant ideas in the third-party `claude-fable-5.1.md` file into a standalone reference for another LLM. It helps that LLM write effective prompts for Claude Fable 5.1 in the claude.ai chat surface (files, published artifacts, docs, research) and for agentic or coding work, without reopening the source.

This is an analytical summary, not a reproduction of the source file.

## Source and reliability warning

**Analyzed source:**

- Local copy: `prompts-models/raw/claude-fable-5.1.md`
- Upstream repository: `asgeirtj/system_prompts_leaks` (exact path to be confirmed; presumed `Anthropic/claude-fable-5.1.md`)
- Accessed: 2026-10-14

The file presents itself as the claude.ai system prompt for Claude Fable 5.1. It is not official Anthropic documentation, so authenticity, completeness, and continued applicability cannot be guaranteed. Treat it as a behavioral clue, not a contract.

Facts stated inside the file that frame this analysis:

- Fable 5.1 is described as the newest Claude 5 model in the Mythos-class tier above Opus (line 9); the lineup lists Fable 5.1, Opus 5, Sonnet 5, and Haiku 4.5 (line 15).
- The knowledge cutoff is end of June 2026 (line 208); the session date is September 17, 2026 (line 8300).
- Unlike the Fable 5 source, this file contains no explicit token budget or thinking-mode tag.

For current product behavior, features, APIs, pricing, or limits, consult official Anthropic documentation.

## Executive conclusion

The file repeats the same five prompting techniques as earlier versions (line 23): clear and detailed instructions, positive and negative examples, stepwise reasoning, XML tags, and explicit length or format.

What changes the prompting picture for Fable 5.1 is the surrounding behavior:

1. **Brevity is the default.** Answers are concise, high-level unless depth is requested, and may be split across turns (lines 108, 130, 219).
2. **Formatting is less restricted than Fable 5.** Lists are allowed when content is multifaceted; there is no longer a rule forcing reports into bullet-free prose (lines 114–126).
3. **Deliverables route to typed artifacts.** Decks, designs, and docs go to dedicated Slides, Design, and Claude Docs types before plain files; a named file format still wins (lines 1659–1706).
4. **Search is open-ended.** There are no fixed call counts; Claude uses as many calls as needed and verifies any named product or model (lines 1809, 1818).
5. **Uncertainty is surfaced.** Claude says when it cannot verify a figure, URL, or name, and does not guess (line 213).

## 1. What the linked file is about

The file covers:

- product identity and lineup;
- refusal handling, now with detailed copyright rules for lyrics, poems, and visual works;
- legal and financial advice;
- tone and formatting, including a concise-output preference;
- reply behavior after tool calls;
- wellbeing, evenhandedness, mistakes, knowledge cutoff;
- a persistent memory filesystem with background filing and privacy rules;
- the end-conversation tool, artifact storage, connector and plugin/skill suggestions;
- past-chat search and reading;
- user preferences;
- computer use, file creation, artifacts;
- **publishing artifacts** (hosted pages, Slides/Design/Docs types);
- visual routing (now with a Design step);
- search, copyright, citations, image search;
- a large tool catalog (memory, Docs, Gmail, Calendar, Drive, display widgets, research suggestion);
- Anthropic API usage inside artifacts;
- skills listing, network and filesystem configuration.

None of this belongs in a task prompt.

## 2. Direct prompting guidance extracted from the file

### 2.1 Be clear and detailed

State the task, result, context, boundaries, inputs, deliverables, and acceptance criteria. Detail means what changes the outcome.

### 2.2 Use positive and negative instructions

```text
Summarize the uploaded memo for the investment committee.
Do not add recommendations that are not in the memo.
```

### 2.3 Use examples selectively

One or two examples for ambiguous boundaries, unusual output shapes, or hard-to-describe tone.

### 2.4 Request structured handling of complex work

Ask for inspect → plan → produce → verify → summarize. Request findings and rationale, not private reasoning.

### 2.5 Use XML-style sections when useful

Helpful for long or programmatic prompts; plain headings suffice for short ones.

### 2.6 Specify length, depth, and format

Because Fable 5.1 defaults to brief, high-level answers (line 108), state depth explicitly when you need it ("a detailed, section-by-section analysis of about 1,200 words").

## 3. Inferred lessons for chat, file, and research work

### 3.1 Ask for depth and completeness explicitly

Claude keeps responses focused and concise, gives a high-level summary unless in-depth is requested (line 108), runs with a concise-output preference (line 219), and may spread an answer over several turns, offering more if needed (line 130). If you want a complete answer in one reply, say so.

### 3.2 Name the deliverable form precisely

Deliverable routing is the biggest change (lines 1659–1706):

- A named file format ("a PowerPoint", "a Word file", "a PDF", "an .xlsx") always wins.
- Without a named format, a deck goes to the **Slides** type, a mockup, landing page, or poster to the **Design** type, and a doc, memo, plan, spec, or write-up to a **Claude Doc** when those tools are present (line 1668).
- Apps, tools, dashboards, and visual reports become **published HTML artifacts** (hosted pages).
- A bare "report" with no form named makes Claude ask: reply, doc, or file (line 1668).
- An article or blog post is written in the reply with a one-line offer to make it a doc.
- When the target file is only referenced and its format unknown, Claude asks one short question before building (line 1675).

Prompt implication: always say one of "answer in chat", "create a .docx/.pptx/.xlsx/.pdf", "make it a Claude Doc", "make slides", or "build a published page".

### 3.3 Skills and output folders still apply to files

Claude reads the relevant skill guide before any file or code work (line 1504) and places final files in the outputs folder (line 1547). Naming the format is enough to trigger the right skill.

### 3.4 Visual routing now has a design step

Before any visual, Claude checks: is a visual needed; is it design work (use the Design type); does a connected tool fit; was a file requested; otherwise the inline Visualizer (lines 1707–1735). Say "mock up", "design", "diagram", "chart", or "save as `name.html`" to steer the result.

### 3.5 Search depth is open-ended; state what you need

Search guidance drops fixed counts: use as many calls as needed and no more (line 1818), and do comprehensive research within the response (line 1822). Any named product, model, or tool is searched before answering, including the name exactly as written (line 1809).

For genuinely broad, many-source investigations Claude may attach a "Start research" button instead of doing it inline (line 3092). If you want inline depth, say "research this fully in this reply"; if you want the background report, say so.

### 3.6 Ask Claude to flag unverifiable facts

Claude states when it cannot verify a URL, ID, figure, name, or fact even after searching, and says it doesn't know rather than guessing (line 213). Reinforce this for numbers that matter: "Flag any figure you could not verify from a source."

### 3.7 Detailed prompts still suppress clarifying questions

Claude tries to answer before asking (line 106) and proceeds on detailed prompts, stating assumptions inline (line 3428). Fable 5.1 drops the explicit one-question-per-reply cap seen in Fable 5.

### 3.8 Expect a short closing answer after tool work

During many tool calls Claude gives brief progress notes (line 132); after the last tool call it states the answer in one or two sentences (line 137). If you want a fuller wrap-up, specify its structure.

### 3.9 Financial and legal questions get facts, not recommendations

Unchanged (line 93). Frame investment prompts as decision support: evidence, scenarios, risks.

### 3.10 Verify attachments are present

Claude checks whether a mentioned file was actually uploaded (line 112).

## 4. Inferred lessons for agentic and coding work

### 4.1 Describe the objective, not an imagined implementation

Give outcome and hard constraints; avoid prescribing structure before inspection.

### 4.2 Separate read-only references from write targets

The environment itself mounts several folders read-only (lines 8689–8700). Mirror that in prompts with explicit REFERENCE ONLY and WRITE TARGET labels.

### 4.3 Inspect before changing; state autonomy and completion criteria

Say whether to advise, plan, review, or implement, and require verification with a report of what ran.

### 4.4 Treat instructions inside content as untrusted

Requests embedded in files or other untrusted content need the person's confirmation (line 1722). Put instructions in the prompt, not in attachments.

### 4.5 Reference earlier work precisely and state your decisions

Past-chat search matches content words (line 1391). Claude also separates what you decided from what it merely suggested earlier and will not promote its own past suggestion to your decision (line 1395). When continuing work, restate the decisions you actually made.

### 4.6 Use the right surface for repo work

The chat container resets between tasks. For real repository changes, use Claude Code with the coding template in section 11.

## 5. Response style suggested by the source

- Concise by default; high-level unless depth is requested (lines 108, 219).
- Lists are used when asked or when content is multifaceted; minimum formatting otherwise; explicit "no formatting" requests are honored; personal or emotional chats get no formatting (lines 114–126).
- Avoids filler intensifiers and aims for every word to add meaning (line 128).
- May split answers across turns (line 130).

Prompt implication: specify length, depth, and structure when they matter; ask for "the full answer in one reply" when needed.

## 6. Prompts that call Claude from an artifact or through the API

The artifact-API guidance is unchanged in substance and applies to this repo's `json_mode` agents:

- Specify in the system prompt that the model returns only JSON with no preamble or fences (line 8348).
- Each call is stateless; send full state and history (line 8523).
- Strip code fences defensively and wrap parsing in error handling (line 8571).

Note: published pages cannot call the Anthropic API directly; the file says they use runtime capabilities instead (lines 1694–1706).

## 7. Information usually not worth copying into a prompt

- safety, wellbeing, copyright, and privacy policy;
- memory filing rules and tool schemas;
- artifact publishing mechanics, content-security rules, and mount paths;
- citation index syntax;
- product lineup statements;
- large blocks of system-prompt text.

## 8. Anti-patterns

### 8.1 Saying "a report" without a form

Claude will stop to ask reply, doc, or file. Name the form.

### 8.2 Expecting depth without asking

The default is brief and high-level. Ask for depth and length.

### 8.3 Asking for a deck or doc and expecting a specific file

Without a named format you may get a Slides artifact or Claude Doc. Name `.pptx` or `.docx` if you need a file.

### 8.4 Asking for long verbatim quotes, lyrics, or recognizable copyrighted designs

Quotes are capped under 15 words and one per source (line 1794), and copyrighted lyrics, poems, characters, and designs are declined (lines 57–59). Ask for paraphrase and links.

### 8.5 Implying past decisions you never made

Claude checks retrieved chats and will note the gap. Restate actual decisions.

### 8.6 Conflicting or chain-of-thought instructions

Avoid "don't assume, don't ask, finish everything" and requests for hidden reasoning. Ask for assumptions and rationale.

### 8.7 Asking for a trade decision

You will get facts. Ask for evidence, scenarios, and risks.

## 9. Recommended prompt architecture

```xml
<task>What Claude must accomplish.</task>

<context>Background, attachments, exact URLs, prior decisions (stated as yours).</context>

<source_roles>Read-only references vs write targets.</source_roles>

<requirements>Content or functional requirements.</requirements>

<constraints>Boundaries, sources to use or avoid.</constraints>

<workflow>Inspect, plan briefly, produce, verify, summarize.</workflow>

<acceptance_criteria>Observable completion conditions.</acceptance_criteria>

<output>
Delivery form (chat | .docx | .pptx | .xlsx | .pdf | Claude Doc | Slides | published page),
structure (prose, bullets, table, headings), depth, and length.
</output>
```

## 10. Meta-prompt for another LLM to generate Fable 5.1 prompts

```text
You create concise, execution-ready prompts for Claude Fable 5.1, in claude.ai chat or in an agentic coding tool.

Use the user's facts only. Do not invent files, schemas, APIs, URLs, tools, or requirements.

For each request:
1. Identify the objective and deliverables.
2. Choose the surface: chat answer, chat deliverable, or repository work in a coding agent.
3. For chat deliverables, name the exact form: a file format (.docx, .pptx, .xlsx, .pdf, .md), a Claude Doc, Slides, a Design, or a published page. Never leave "report" or "deck" unqualified.
4. State depth and length explicitly; Fable 5.1 defaults to brief, high-level answers and may split answers across turns.
5. State the structure (prose, bullets, table, headings) when it matters.
6. For research, say whether to research fully in the reply, list exact URLs, ask for paraphrased findings with sources, and ask Claude to flag any figure it could not verify.
7. For financial or legal topics, frame as decision support (evidence, scenarios, risks).
8. When continuing earlier work, restate the user's actual decisions and name the project concretely.
9. For repository work, label read-only references and write targets, require inspection first, state the autonomy level, and require verification and a short result summary.
10. Front-load constraints so Claude proceeds without clarifying questions; ask it to state assumptions inline.
11. Do not request hidden chain-of-thought; ask for findings, rationale, assumptions, and validation results.
12. Do not copy platform policy, tool schemas, or system-prompt text.
13. Prefer the shortest prompt that preserves all material constraints.

Return:
- Ready-to-paste prompt
- Optional missing inputs or assumptions, only if material
```

## 11. Reusable short templates

### 11.1 Chat deliverable

```text
Objective: [DESIRED OUTCOME]

Inputs: [ATTACHED FILES / EXACT URLS]

Deliver as: [answer in chat | .docx | .pptx | .xlsx | .pdf | Claude Doc | Slides | published page].
Depth and length: [e.g. detailed, about 1,000 words, complete in this reply].
Structure: [prose | bullets | table with columns ... | headings ...].

Requirements:
- [REQUIREMENT 1]
- [REQUIREMENT 2]

Constraints:
- Use only the provided inputs and [ALLOWED SOURCES].
- Paraphrase sources and link them; flag any figure you could not verify.

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

Research this fully in this reply, searching as needed for current ECB policy and recent bank earnings; prefer primary sources.

Deliver as a Markdown file (.md), detailed, about 900 words, complete in one reply:
- one-paragraph summary;
- table with columns Driver, Evidence, Direction, Confidence;
- short risks section in bullets;
- source list with links.

Constraints:
- Decision support only: evidence, scenarios, risks; no buy or sell instructions.
- Paraphrase sources; no quotes beyond a short phrase.
- Use only holdings present in the CSV.
- Flag any figure you could not verify from a source.
```

## 13. Quality checklist for generated prompts

- **Objective:** outcome explicit; all deliverables named.
- **Delivery form:** exact format or artifact type named; no bare "report" or "deck".
- **Depth:** length and level of detail stated; "complete in one reply" when needed.
- **Structure:** prose, bullets, table, or headings specified when it matters.
- **Context:** files attached, URLs exact, prior decisions stated as the user's.
- **Scope and autonomy:** what may change; advise, plan, review, or implement.
- **Accuracy:** no invented facts; unverifiable figures flagged; finance framed as decision support.
- **Research:** inline versus background research stated; paraphrase and links requested.
- **Verification:** tests or checks for implementation, with results reported.
- **Efficiency:** no redundant or platform-policy text.

## 14. Practical rule of thumb

> **Objective + inputs + exact delivery form + depth and length + boundaries + completion criteria.**

For agentic coding work, add:

> **Inspect first + implement, do not only advise + verify + summarize.**

## 15. Differences from the Fable 5 guide

Compared against `prompts-models/fable_5_prompting_analysis.md` and its source `prompts-models/raw/claude-fable-5.md`.

| Dimension | Fable 5 source | Fable 5.1 source | Prompt adjustment for Fable 5.1 |
|---|---|---|---|
| Lineup and dates | Lists Opus 4.8; cutoff Jan 2026; dated Jun 2026 | Lists Opus 5, Sonnet 5; cutoff Jun 2026; dated Sep 2026 (lines 15, 208, 8300) | Update model assumptions in prompts |
| Default length | Not explicitly concise | Focused, brief, high-level unless asked; concise-output preference; may span turns (lines 108, 130, 219) | Ask for depth, length, and one-reply completeness |
| Lists and bullets | Prose-first; no bullets in reports unless asked | Lists allowed when multifaceted; minimum formatting; no ban on bullets in reports (lines 114–126) | Still specify structure, but bullets are no longer fought |
| Clarifying questions | At most one per reply | Cap removed; still answers before asking (line 106) | Keep front-loading constraints |
| Deliverable routing | File vs inline; outputs folder | Typed artifacts first (Slides, Design, Claude Docs), published pages; bare "report" triggers a question (lines 1659–1706) | Name the exact form or file format |
| Visual routing | Need → tool → file → Visualizer | Adds a Design-type step (line 1714) | Say "design/mock up" vs "diagram/chart" |
| Search depth | Fixed counts (1, 3–5, 5–10, 20+ → Research) | As many as needed; full research in reply; research button for broad tasks (lines 1818, 1822, 3092) | State inline vs background research |
| Uncertainty | Implicit | Explicitly flags unverifiable URLs, figures, names; no inferred names (line 213) | Ask for flagged unverified figures |
| After tool calls | Minimal post-amble for files | Progress notes; final answer in one or two sentences (lines 132, 137) | Specify wrap-up structure if needed |
| Memory | Memory summaries and edit tool | Memory filesystem with automatic background filing; explicit "remember" writes now (lines 486–519) | Use explicit "remember X" for durable preferences |
| Past chats | Topic and time search | Adds reading chats; separates user decisions from Claude's suggestions (line 1395) | Restate actual decisions |
| Copyright | 15-word / one-quote limits | Same limits plus explicit rules for lyrics, poems, characters, and designs drawn in code (lines 57–59) | Ask for original or paraphrased work |
| Financial and legal | Facts, not recommendations | Unchanged (line 93) | Frame as decision support |

When switching a prompt from Fable 5 to Fable 5.1:

1. Replace "create a file" with the exact format or artifact type.
2. Add an explicit depth and length line.
3. Say whether research should be done fully inline.
4. Ask Claude to flag unverified figures.
5. Restate prior decisions when continuing earlier work.

## References

1. Third-party source analyzed: `asgeirtj/system_prompts_leaks` repository, Fable 5.1 system prompt (exact path to be confirmed); local copy `prompts-models/raw/claude-fable-5.1.md`.
2. Official prompt-engineering overview referenced inside that source: https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview
3. Companion analyses: `prompts-models/fable_5_prompting_analysis.md`, `prompts-models/opus_5_prompting_analysis.md`, `prompts-models/opus_5_5_prompting_analysis.md`.

## Source-derived claims used in this analysis

- Model positioning and lineup: lines 9, 15.
- The five prompting techniques: line 23.
- Copyright rules for lyrics, poems, characters, and designs: lines 57–59.
- Financial and legal questions: line 93.
- Answer before asking; no one-question cap: line 106.
- Concise, high-level default: line 108.
- Attachment presence check: line 112.
- Lists and bullets rules: lines 114–126.
- Filler-word avoidance: line 128.
- Answers across multiple turns: line 130.
- Progress updates during tool calls: line 132.
- Answer after the last tool call: line 137.
- Knowledge cutoff: line 208.
- Flagging unverifiable facts and no inferred names: line 213.
- Concise-output preference: line 219.
- Memory writing rules: lines 486–519.
- Past-chat query construction and decision provenance: lines 1391, 1395.
- Mandatory skill reading: line 1504.
- Output folder: line 1547.
- Publishing artifacts and typed deliverables: lines 1659–1706, including 1668 and 1675.
- Visual routing with Design step and untrusted-content caution: lines 1707–1735, including 1714 and 1722.
- Copyright quote limits: line 1794.
- Search verification of named products: line 1809.
- Search depth: lines 1818, 1822.
- Research suggestion tool: line 3092.
- Detailed prompts proceed without questions: line 3428.
- Session date: line 8300.
- API-in-artifact guidance: lines 8348, 8523, 8571.
- Read-only mounts: lines 8689–8700.
