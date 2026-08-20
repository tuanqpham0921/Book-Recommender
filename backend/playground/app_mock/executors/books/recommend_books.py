from app.domains.books.schemas import RecommendationStrategy
from ..base import MockExecutorWorkflow


class RecommendBooksExecutor(MockExecutorWorkflow):
    ui_loading_message = "Finding book recommendations..."

    def build_reply(self, task: RecommendationStrategy, dependent_results: dict) -> str:
        return (
            "## Recommendations for you\n\n"
            "I put together a few recommendations based on what you've told me so "
            "far. I tried to balance books that closely match your stated "
            "preferences with a couple of picks that are a bit more of a stretch, "
            "in case you're up for something slightly outside your usual lane. See "
            "[Goodreads](https://www.goodreads.com/) for reviews if you want a "
            "second opinion before committing.\n\n"
            "### What I weighed\n\n"
            "1. **Genre & themes** — prioritized books that match the categories "
            "and tone you asked about\n"
            "   - close matches first, adjacent genres second\n"
            "2. **Reader reception** — favored titles with strong average ratings "
            "and a healthy number of reviews\n"
            "   - ✅ high rating *and* high review count\n"
            "   - ⚠️ high rating but thin review count (proceed with a bit of "
            "caution)\n"
            "3. **Variety** — mixed in different authors and publication years so "
            "the list doesn't feel repetitive\n"
            "4. **Accessibility** — kept length and reading level in mind so "
            "nothing here feels like a slog\n\n"
            "> Rule of thumb: if a pick has ✅ on both rating and review count, "
            "it's a safe bet.\n\n"
            "> **📦 Bottom line**\n"
            ">\n"
            "> These are ranked roughly `best fit → biggest stretch`, not "
            "~~strictly~~ by rating alone.\n\n"
            "*The top pick* is the closest match to what you asked for, but "
            "don't sleep on the <u>stretch picks</u> further down the list.\n\n"
            "Let me know if you'd like me to lean more into any of these factors, "
            "and I can refine the list further."
        )
