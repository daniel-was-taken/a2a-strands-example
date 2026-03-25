from strands import Agent
from strands.multiagent import Swarm

# Create specialized agents
researcher = Agent(
    name="researcher",
    system_prompt="""You are a research specialist. Gather information and facts.
    When you need code written, hand off to the 'coder' agent.
    When you need content written, hand off to the 'writer' agent.""",
    description="Researches topics and gathers information"
)

coder = Agent(
    name="coder",
    system_prompt="""You are a coding specialist. Write clean, documented code.
    When you need research, hand off to the 'researcher' agent.
    When you need documentation written, hand off to the 'writer' agent.""",
    description="Writes and reviews code"
)

writer = Agent(
    name="writer",
    system_prompt="""You are a technical writer. Create clear documentation.
    When you need research, hand off to the 'researcher' agent.
    When you need code examples, hand off to the 'coder' agent.""",
    description="Writes documentation and content"
)

# Create swarm with agents
swarm = Swarm(
    nodes=[researcher, coder, writer],
    entry_point=researcher,
    max_handoffs=10,          # Max agent-to-agent handoffs
    max_iterations=15,        # Max total iterations
    execution_timeout=300.0   # 5 minute timeout
)

# Execute collaborative task
# result = swarm("Create a Python utility for parsing CSV files with documentation")
result = swarm(input("Enter query to view results..."))
print(f"Status: {result.status}")
print(f"Handoffs: {len(result.node_history)}")
for node in result.node_history:
    print(f"  - {node.node_id}")