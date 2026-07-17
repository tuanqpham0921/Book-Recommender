# frontend/src

Single-page React app (React 19 + Vite). All routes (`/`, `/blog`, `/review`) render
`BookRecommenderPage`, which maps the path to a view; views are lazy-loaded and stay
mounted once visited.

## Map

| Path | What it is |
|---|---|
| `api.js` | **The only backend surface.** Uses `VITE_API_URL`; wraps fetch with a 120s timeout. Note: `stopChatStream`, `getTaskPlanDiagram`, and `getRecommendedBooks` are dead/unwired (docs/backlog.md) |
| `components/ChatBot.jsx` | Chat view: sends messages, consumes the SSE stream, builds ordered response sections (`text`/`books`/`diagram`/`error`) in `use-immer` state |
| `components/chatbot/` | `ChatInput`, `ChatMessages` (react-markdown + remark-gfm rendering) |
| `components/MermaidDiagram.jsx` | Renders the task-plan diagram (`securityLevel: 'strict'`, pan/zoom via `@panzoom/panzoom`); shared with the review page |
| `components/book/` | `BookCard`, `BookCover`, `BookDetailModal`, `BooksGrid` |
| `pages/ChatReviewPage.jsx` | Review queue over recorded chat runs: expand a run → goals, diagram, raw envelopes; file one review per run (`PUT /feedback/review`) |
| `pages/BookRecommenderPage.jsx` | Shell: header, view switching |
| `design-system/` | Button, Badge, Modal, Dropdown, IconButton, ColorModeToggle, … |
| `hooks/`, `utils/`, `styles/`, `data/` | Support code; split CSS lives in `styles/` |

## SSE events the chat handles

`chat.id`, `ui.loading`, `content.delta`, `book_card`, `mermaid.diagram`,
`step.complete`, `error`, `complete` — handled in `ChatBot.jsx` via
`parseSSEStream` from `utils/`.

## Conventions

- Complex nested state uses `use-immer`.
- Review categories in `ChatReviewPage.jsx` must match the backend's
  `FeedbackCategory` literal (`backend/app/api/schemas/external.py`).
- Reduce features rather than add them — V1 direction (docs/roadmap.md).
