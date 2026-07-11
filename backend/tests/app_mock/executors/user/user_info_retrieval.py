from app.domains.users.schemas.request_schemas import DeveloperInfoRequest, UserInfoRequest
from ..base import MockExecutorWorkflow


class UserInfoExecutor(MockExecutorWorkflow):
    ui_loading_message = "Getting your account info..."

    def build_reply(self, task: UserInfoRequest, dependent_results: dict) -> str:
        return (
            "## Your account\n\n"
            "Here's a quick snapshot of what's on file for you. Nothing here is "
            "sensitive, just the basics I use to personalize recommendations — "
            "you can always ask me to update or forget any of it.\n\n"
            "### At a glance\n\n"
            "- **Status** — ✅ active, no restrictions\n"
            "- **Session history**\n"
            "  - a handful of chats so far\n"
            "  - most recent activity: this conversation\n"
            "- **Preferences on file**\n"
            "  - ✅ favorite genres captured\n"
            "  - ⚠️ reading pace not set yet — ask me and I'll remember it\n\n"
            "| Field | Value |\n"
            "| --- | --- |\n"
            "| Account type | Standard |\n"
            "| Personalization | Enabled |\n"
            "| Data retention | Session-based |\n\n"
            "> Tip: the more you tell me about what you liked or didn't, the "
            "better future recommendations get.\n\n"
            "> **📦 Privacy note**\n"
            ">\n"
            "> *Nothing here* is shared outside this session — it's only used "
            "to personalize <u>your own</u> recommendations.\n\n"
            "Want me to walk through anything specific about your account?"
        )


class DeveloperInfoExecutor(MockExecutorWorkflow):
    ui_loading_message = "Getting developer info..."

    def build_reply(self, task: DeveloperInfoRequest, dependent_results: dict) -> str:
        return (
            "## About the developer\n\n"
            "This project is built and maintained by a solo developer as a "
            "hands-on way to explore LLM-driven planning systems — you can find "
            "more of their work on [GitHub](https://github.com/) and connect on "
            "[LinkedIn](https://www.linkedin.com/).\n\n"
            "### Focus areas\n\n"
            "1. **Backend architecture** — async Python, workflow orchestration, "
            "structured LLM tool-calling\n"
            "2. **Data & retrieval** — PostgreSQL, `pgvector` similarity search\n"
            "3. **Frontend** — React, real-time SSE streaming UIs\n\n"
            "- ✅ Actively maintained\n"
            "- ✅ Open to feedback and feature requests\n"
            "- ⚠️ Solo project, so response times can vary\n\n"
            "> Built as a learning project first, a useful tool second — but "
            "hopefully both.\n\n"
            "> **📦 Open to work**\n"
            ">\n"
            "> *Always happy* to chat about the project or opportunities — "
            "reach out via <u>GitHub or LinkedIn</u> above.\n\n"
            "Feel free to ask if you'd like more detail on any part of how this "
            "was built."
        )
