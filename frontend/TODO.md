* review your new code

Do I need this with the new mermaid code?
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    meramid fonts is fixed at 14px? does that scale with smaller devices?

* get some tests for your front end
    * make sure the fonts and spacing stay the same in different scales

1. test your markdown and how it handle spacings (formatting)
    * nested bullet points was one
    * two dividers back to back? only one should show (or if there is no text before)
2. test error messages
3. test if your backend is not running or stalling

=======================================================================

Code review findings (2026-07-10):

Correctness bugs (highest priority):
* ChatBot.jsx:31-41 + 89-93 - mount-time initSession() and handleSendMessage's own
  fallback createSession() can both fire if you send a message before the initial
  session promise resolves -> two sessions created, last setSessionId wins silently.
* api.js:80 vs ChatBot.jsx:84-87 - sendChatMessage's own internal timeout (120000ms)
  fires before ChatBot's "safety timer" (180000ms) ever gets a chance to run - the
  3-minute timeout message is currently unreachable.
* [FIXED 2026-07-12] api.js:40,47 - fetch_api rejects with plain objects ({status, data}), not Error
  instances - ChatBot.jsx:242's `err.name === 'AbortError'` check can never match,
  so timeouts/HTTP failures fall through to the generic error message.
  -> both reject paths now throw real Error instances (status/data attached via
  Object.assign; the timeout path also sets .name = 'AbortError').
* ChatReviewPage.jsx + ChatFeedback.jsx:26-34 - every ChatRunRow mounts its own
  IssueReportModal unconditionally (not just when open), each registering a
  permanent mousedown listener - up to 200 live global listeners for a feature
  only one row uses at a time.
* stopChatStream in api.js is unused - the Stop button only aborts the client-side
  fetch, backend task keeps running server-side after clicking Stop.

Security:
* [FIXED 2026-07-12] MermaidDiagram.jsx:15 (securityLevel: 'loose') + :60 (innerHTML = svg) - diagram
  source comes from LLM/backend output and renders with sanitization disabled;
  'loose' permits click bindings and other script-bearing constructs. Switch to
  'strict' unless click-bindings are actually needed.

Consistency / tech debt:
* Click-outside-to-close logic copy-pasted 3x: VersionDropdown.jsx:16-24,
  ChatFeedback.jsx:26-34, ChatInput.jsx:26-48 - extract a shared useClickOutside hook.
* Session-creation boilerplate duplicated (ChatBot.jsx:31-41,89-93 and
  ChatReviewPage.jsx:302-307) - a shared useSession() hook would also fix the
  race condition above in one place.
* Leftover debug console.log: App.jsx:12, ChatBot.jsx:105,232-234,
  MermaidDiagram.jsx:102, VersionDropdown.jsx:29.
* api.js:156-162 getTaskPlanDiagram is dead/unwired (diagrams come over SSE instead
  per its own comment) - delete or finish wiring it up.
* data/chatSuggestions.js:27-38 - large commented-out block of old ideas, delete
  or move to a backlog note.
* utils/bookUtils.js:4-33 - formatAuthors/formatAuthorsMobile ~90% duplicated,
  collapse into one function with a `compact` flag.

Code cleanup pass (2026-07-12): fixed the two items above (MermaidDiagram.jsx
securityLevel, api.js fetch_api error rejection). Everything else below is still
open — each implies a small refactor/new hook (useSession, useClickOutside) or a
backend endpoint (stopChatStream), out of scope for a no-new-code cleanup pass.

Accessibility:
* ChatFeedback.jsx:55-196 (IssueReportModal) - no role="dialog"/aria-modal, no
  focus trap, no initial focus, no Escape-to-close.
* VersionDropdown.jsx:37-69 and the category dropdown in ChatFeedback.jsx:97-125 -
  mouse-only open/close, no Escape handling, no aria-expanded/aria-haspopup.
* NavBar.jsx:30-35 (overlay) + 37-79 (panel) - closes on click only, no keyboard
  equivalent, no focus trap/Escape while open.
* ChatInput.jsx:88-103 (textarea) - accessible name relies on placeholder text,
  which disappears once typing starts; add an aria-label.