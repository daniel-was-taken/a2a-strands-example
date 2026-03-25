from strands import Agent
from strands.multiagent import GraphBuilder

analyzer = Agent(name="analyzer", system_prompt="Analyze the input.")
implementer = Agent(name="implementer", system_prompt="Implement the solution.")
reviewer = Agent(name="reviewer", system_prompt="Review the implementation.")

builder = GraphBuilder()
builder.add_node(analyzer, "analyze")
builder.add_node(implementer, "implement")
builder.add_node(reviewer, "review")
builder.add_edge("analyze", "implement")
builder.add_edge("implement", "review")
    # Conditional routing
builder.add_edge(
        "review",
        "implement",
        condition=lambda state: "needs revision" in str(state.results.get("review", ""))
    )
builder.set_entry_point("analyze")
builder.set_max_node_executions(10)
graph = builder.build()


result = graph("Build a REST API")
# result = graph(input("Enter query to view results..."))

# Access the results
print(f"\nStatus: {result.status}")
print(f"Execution order: {[node.node_id for node in result.execution_order]}")