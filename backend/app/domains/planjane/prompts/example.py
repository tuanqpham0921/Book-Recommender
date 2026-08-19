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
                        "description": "Find the book Dune by title",
                        "reasoning": "Recommendation needs the anchor book first",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "description": "Recommend books similar to Dune",
                        "reasoning": "Similarity search seeded by the retrieved title",
                        "confidence": 1.0,
                        "target_node_type": "Analyze_Recommend",
                        "depends_on": ["1"],
                    },
                ],
                "reasoning": "Greeting plus a direct match to two supported capabilities",
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
                        "description": "Find sci-fi books",
                        "reasoning": "Single-dimension genre lookup",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Genre",
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
                        "description": "Find the book Flights by title",
                        "reasoning": "One anchor book for the comparison",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "description": "Find the book Satantango by title",
                        "reasoning": "The other anchor book for the comparison",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "3",
                        "description": "Compare Flights and Satantango",
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
                        "description": "Find the book Dune by title",
                        "reasoning": "One retrieval covers every mention of Dune",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "description": "Find the book Neuromancer by title",
                        "reasoning": "The other anchor book for the comparison",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Title",
                        "depends_on": [],
                    },
                    {
                        "id": "3",
                        "description": "Compare Dune and Neuromancer",
                        "reasoning": "Compare reuses goal 1 instead of re-finding Dune",
                        "confidence": 1.0,
                        "target_node_type": "Analyze_Compare",
                        "depends_on": ["1", "2"],
                    },
                    {
                        "id": "4",
                        "description": "Recommend books similar to Dune",
                        "reasoning": "Recommend reuses the same retrieval of Dune",
                        "confidence": 1.0,
                        "target_node_type": "Analyze_Recommend",
                        "depends_on": ["1"],
                    },
                ],
                "reasoning": "Dune is named four times but is retrieved once — a repeated mention of an already-retrieved book adds no goal, it is reused by depending on the existing retrieval id, so both analyze goals point back at goal 1",
            },
        },
        {
            "query": "Show me thrillers by Gillian Flynn",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "description": "Find thriller books",
                        "reasoning": "Genre is one retrieval dimension",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Genre",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "description": "Find books by Gillian Flynn",
                        "reasoning": "Author is a separate retrieval dimension",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Author",
                        "depends_on": [],
                    },
                    {
                        "id": "3",
                        "description": "Keep only the books that are both thrillers and by Gillian Flynn",
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
                        "description": "Find books by Kazuo Ishiguro",
                        "reasoning": "Author is the search subject",
                        "confidence": 1.0,
                        "target_node_type": "Retrieve_by_Author",
                        "depends_on": [],
                    },
                    {
                        "id": "2",
                        "description": "Keep only the ones published before 2000",
                        "reasoning": "Year can only narrow the retrieved set, so it is a separate filter goal",
                        "confidence": 1.0,
                        "target_node_type": "Filter_Retrieval",
                        "depends_on": ["1"],
                    },
                ],
                "reasoning": "The author is the subject of the search; publication year can only narrow it and cannot be searched for on its own, so it becomes a separate narrowing goal rather than a retrieval",
            },
        },
        {
            "query": "What's my saved memory?",
            "request": {
                "system_goals": [
                    {
                        "id": "1",
                        "description": "Retrieve user saved memory",
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