from typing import Any

# Annotated so it lands in `ConfigDict(json_schema_extra=...)`, whose value type
# is invariant and would otherwise reject the inferred nested-dict type.
planner_example: dict[str, Any] = {
    "examples": [
        {
            "query": "Hi! Can you recommend books like Dune?",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "instruction": "Find the book Dune by title",
                        "reasoning": "Recommendation needs the anchor book first",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "instruction": "Find books similar to Dune",
                        "reasoning": "Similarity search seeded by the retrieved title",
                        "confidence": 1.0,
                        "target_node_type": "Analyze_Similar_Books",
                        "depends_on": ["1"],
                    },
                    {
                        "id": "3",
                        "instruction": "Present the recommended books and explain why they fit Dune",
                        "reasoning": "A recommendation chain ends with the reply that presents it",
                        "confidence": 1.0,
                        "target_node_type": "Generate_Recommendations",
                        "depends_on": ["2"],
                    },
                ],
                "reasoning": "Greeting plus a recommendation ask: retrieve the anchor, search from it, and close the chain with the goal that writes the reply",
            },
        },
        {
            "query": "What's the weather like today?",
            "request": {
                "system_goals": [],
                "out_of_scope": "What's the weather like today?",
                "reasoning": "No supported capability covers weather",
            },
        },
        {
            "query": "Find thrillers that are not thrillers",
            "request": {
                "system_goals": [],
                "out_of_scope": ["Find thrillers that are not thrillers"],
                "reasoning": "The two halves cancel each other out, so no set of books can satisfy it",
            },
        },
        {
            "query": "Find some sci-fi books",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "instruction": "Find sci-fi books",
                        "reasoning": "Single-dimension genre lookup",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Lexical_Traits",
                        "depends_on": [],
                    }
                ],
            },
            "reasoning": "Direct match to a supported capability",

        },
        {
            "query": "Compare Flights and Satantango",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "instruction": "Find the book Flights by title",
                        "reasoning": "One anchor book for the comparison",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "instruction": "Find the book Satantango by title",
                        "reasoning": "The other anchor book for the comparison",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "3",
                        "instruction": "Compare Flights and Satantango",
                        "reasoning": "Compare needs both books retrieved first",
                        "confidence": 1.0,
                        "target_node_type": "Analyze_Compare",
                        "depends_on": ["1", "2"],
                    },
                ],
                "reasoning": "Comparison requires retrieving both titles before comparing them",

            },
        },
        {
            "query": "Find Dune, compare Dune with Neuromancer, then find Dune again and recommend books like Dune",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "instruction": "Find the book Dune by title",
                        "reasoning": "One retrieval covers every mention of Dune",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "instruction": "Find the book Neuromancer by title",
                        "reasoning": "The other anchor book for the comparison",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "3",
                        "instruction": "Compare Dune and Neuromancer",
                        "reasoning": "Compare reuses goal 1 instead of re-finding Dune",
                        "confidence": 1.0,
                        "target_node_type": "Analyze_Compare",
                        "depends_on": ["1", "2"],
                    },
                    {
                        "id": "4",
                        "instruction": "Find books similar to Dune",
                        "reasoning": "The similarity search reuses the same retrieval of Dune",
                        "confidence": 1.0,
                        "target_node_type": "Analyze_Similar_Books",
                        "depends_on": ["1"],
                    },
                    {
                        "id": "5",
                        "instruction": "Present the books recommended from Dune and explain why they fit",
                        "reasoning": "Only the recommendation chain ends in a generation goal; the comparison stands on its own",
                        "confidence": 1.0,
                        "target_node_type": "Generate_Recommendations",
                        "depends_on": ["4"],
                    },
                ],
                "reasoning": "Dune is named four times but is retrieved once — a repeated mention of an already-retrieved book adds no goal, it is reused by depending on the existing retrieval id, so both analyze goals point back at goal 1; the recommendation chain then closes with its generation goal while the compare chain does not take one",
            },
        },
        {
            "query": "Show me thrillers by Gillian Flynn",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "instruction": "Find thriller books",
                        "reasoning": "Genre is one retrieval dimension",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Lexical_Traits",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "instruction": "Find books by Gillian Flynn",
                        "reasoning": "Author is a separate retrieval dimension",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Author",
                        "depends_on": [],
                    },
                    {
                        "id": "3",
                        "instruction": "Keep only the books that are both thrillers and by Gillian Flynn",
                        "reasoning": "Both conditions must hold on the same book, so AND the two retrievals",
                        "confidence": 1.0,
                        "target_node_type": "Combine_Intersect",
                        "depends_on": ["1", "2"],
                    },
                ],
                "reasoning": "Genre and author are both search subjects, so each is its own retrieval goal; they must hold on the same book, which is a third goal — without it the two retrievals would simply be pooled",

            },
        },
        {
            "query": "Books by Kazuo Ishiguro published before 2000",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "instruction": "Find books by Kazuo Ishiguro",
                        "reasoning": "Author is the search subject",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Author",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "instruction": "Find books published before 2000",
                        "reasoning": "The year bound is its own retrieval dimension",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Numeric_Traits",
                        "depends_on": [],
                    },
                    {
                        "id": "3",
                        "instruction": "Keep only the books that are both by Kazuo Ishiguro and published before 2000",
                        "reasoning": "Both conditions must hold on the same book, so AND the two retrievals",
                        "confidence": 1.0,
                        "target_node_type": "Combine_Intersect",
                        "depends_on": ["1", "2"],
                    },
                ],
                "reasoning": "A measurable bound is a retrieval like any other, so the year gets its own goal rather than being folded into the author's; the intersect is what makes the two conditions hold together instead of being pooled",
            },
        },
        {
            "query": "What's my saved memory?",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "instruction": "Retrieve user saved memory",
                        "reasoning": "Direct user-info lookup",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_User_Info",
                        "depends_on": [],
                    }
                ],
                "reasoning": "Direct match to a supported capability",
            },
        },
    ]
}