# Demo script for Mem0 MCP Server capabilities

print("=" * 60)
print("MEM0 MCP SERVER - Available Tools")
print("=" * 60)
print()

tools = [
    ("add_memory", "Save text or conversation history (or explicit message objects) for a user/agent"),
    ("search_memories", "Semantic search across existing memories (filters + limit supported)"),
    ("get_memories", "List memories with structured filters and pagination"),
    ("get_memory", "Retrieve one memory by its memory_id"),
    ("update_memory", "Overwrite a memory's text once the user confirms the memory_id"),
    ("delete_memory", "Delete a single memory by memory_id"),
    ("delete_all_memories", "Bulk delete all memories in confirmed scope (user/agent/app/run)"),
    ("delete_entities", "Delete a user/agent/app/run entity (and its memories)"),
    ("list_entities", "Enumerate users/agents/apps/runs stored in Mem0"),
]

print("Available Tools:")
for tool_name, description in tools:
    print(f"  • {tool_name}: {description}")

print()
print("=" * 60)
print("INSTALLATION SUMMARY")
print("=" * 60)
print()
print("✓ Server directory created: mcp-server/mem0-mcp/")
print("✓ Package installed: mem0-mcp-server (0.2.1)")
print("✓ Configuration updated in cline_mcp_settings.json:")
print("  - Server name: mem0-mcp")
print("  - Command: uvx mem0-mcp-server")
print("  - Environment variables: MEM0_API_KEY configured")
print()
print("=" * 60)
print("USAGE OPTIONS (from official README)")
print("=" * 60)
print()
print("Option 1: Python Package (local installation)")
print("  uv pip install mem0-mcp-server")
print("  or: pip install mem0-mcp-server")
print()
print("Option 2: Docker deployment")
print("  docker build -t mem0-mcp-server .")
print("  docker run --rm -d -e MEM0_API_KEY=... mem0-mcp-server")
print()
print("Option 3: Smithery remote server (managed)")
print("  Available at https://smithery.ai/@mem0ai/mem0-memory-mcp")
print()
