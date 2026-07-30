from openai import OpenAI
from config import settings
client = OpenAI(api_key=settings.openai.API_KEY)

response = client.responses.create(
    model="gpt-5.6",
    tools=[{"type": "web_search"}],
    input="What was a positive news story from today?",
)
from common.utils import save_file
save_file(response, "websearch_exmaple")
print(response)