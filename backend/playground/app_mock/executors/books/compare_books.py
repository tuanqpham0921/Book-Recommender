from app.domains.books.schemas import CompareStrategy
from ..base import MockExecutorWorkflow


class CompareBooksExecutor(MockExecutorWorkflow):
    ui_loading_message = "Comparing books..."

    def build_reply(self, task: CompareStrategy, dependent_results: dict) -> str:
        return (
            "## Comparing these books\n\n"
            "Here's how those books stack up against each other. They share some "
            "common ground in tone and subject matter, but they diverge quite a bit "
            "in pacing, structure, and the kind of reading experience they're going "
            "for — so the right pick really depends on what you're in the mood for. "
            "You can read more about the general genre on "
            "[Wikipedia](https://en.wikipedia.org/wiki/Fiction) if you want the "
            "broader context.\n\n"
            "### Breakdown\n\n"
            "- **Pacing**\n"
            "  - Book A: slower, more atmospheric\n"
            "  - Book B: brisker, more event-driven\n"
            "- **Tone**\n"
            "  - Book A: introspective, character-driven\n"
            "  - Book B: plot-forward, higher stakes\n"
            "- **Reception**\n"
            "  - ✅ Book A: strong average rating, large review base\n"
            "  - ⚠️ Book B: solid rating, but a smaller, more niche audience\n"
            "- **Length & commitment**\n"
            "  - Book A: a noticeably longer read\n"
            "  - Book B: quicker to finish, easier to fit into a busy week\n\n"
            "> If you only have time for one right now, the shorter/brisker option "
            "is usually the easier entry point.\n\n"
            "> **📦 Bottom line**\n"
            ">\n"
            "> `Book A` rewards patience, `Book B` is built for momentum. "
            "~~Neither is objectively better~~ — it really comes down to what "
            "kind of read you're chasing.\n\n"
            "*Both are well regarded within their genre*, but the "
            "<u>reading experience</u> they deliver is genuinely different.\n\n"
            "If you want, I can dig into any one of these points in more depth."
        )
