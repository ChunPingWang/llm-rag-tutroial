#!/usr/bin/env python3
"""
K8s MCP Server - Provides kubectl operations as MCP tools.
Used by OpenCode to interact with Kubernetes clusters.
"""

import json
import subprocess
import sys

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

server = Server("k8s-mcp-server")


def run_kubectl(args: list[str], namespace: str = None, context: str = None) -> dict:
    """Execute a kubectl command and return structured output."""
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    if namespace:
        cmd.extend(["-n", namespace])
    cmd.extend(args)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 30 seconds", "command": " ".join(cmd)}
    except FileNotFoundError:
        return {"error": "kubectl not found. Is it installed and in PATH?"}


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="kubectl_get",
            description="Get Kubernetes resources. Examples: pods, deployments, services, nodes, events",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource": {"type": "string", "description": "Resource type (pods, deployments, services, nodes, events, etc.)"},
                    "namespace": {"type": "string", "description": "Kubernetes namespace (optional, defaults to current context)"},
                    "name": {"type": "string", "description": "Specific resource name (optional)"},
                    "output": {"type": "string", "description": "Output format: wide, yaml, json (optional, defaults to wide)"},
                    "selector": {"type": "string", "description": "Label selector (optional, e.g. app=nginx)"},
                    "all_namespaces": {"type": "boolean", "description": "Search across all namespaces"},
                },
                "required": ["resource"],
            },
        ),
        Tool(
            name="kubectl_describe",
            description="Show detailed information about a Kubernetes resource",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource": {"type": "string", "description": "Resource type (pod, deployment, service, node, etc.)"},
                    "name": {"type": "string", "description": "Resource name"},
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                },
                "required": ["resource", "name"],
            },
        ),
        Tool(
            name="kubectl_logs",
            description="Get logs from a pod or container",
            inputSchema={
                "type": "object",
                "properties": {
                    "pod": {"type": "string", "description": "Pod name"},
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    "container": {"type": "string", "description": "Container name (optional)"},
                    "tail": {"type": "integer", "description": "Number of lines to show (default: 100)"},
                    "previous": {"type": "boolean", "description": "Show logs from previous container instance"},
                },
                "required": ["pod"],
            },
        ),
        Tool(
            name="kubectl_top",
            description="Show resource usage (CPU/memory) for pods or nodes",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource": {"type": "string", "description": "pods or nodes"},
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    "name": {"type": "string", "description": "Specific resource name (optional)"},
                },
                "required": ["resource"],
            },
        ),
        Tool(
            name="kubectl_exec",
            description="Execute a command in a running container (read-only commands recommended)",
            inputSchema={
                "type": "object",
                "properties": {
                    "pod": {"type": "string", "description": "Pod name"},
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    "container": {"type": "string", "description": "Container name (optional)"},
                    "command": {"type": "string", "description": "Command to execute"},
                },
                "required": ["pod", "command"],
            },
        ),
        Tool(
            name="kubectl_events",
            description="Get recent events for debugging. Automatically sorted by time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    "resource_name": {"type": "string", "description": "Filter events for specific resource"},
                    "all_namespaces": {"type": "boolean", "description": "Show events across all namespaces"},
                },
            },
        ),
        Tool(
            name="kubectl_raw",
            description="Execute any kubectl command. Use for operations not covered by other tools.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Full kubectl command arguments (without 'kubectl' prefix)"},
                },
                "required": ["command"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "kubectl_get":
        args = ["get", arguments["resource"]]
        if arguments.get("name"):
            args.append(arguments["name"])
        output = arguments.get("output", "wide")
        args.extend(["-o", output])
        if arguments.get("selector"):
            args.extend(["-l", arguments["selector"]])
        if arguments.get("all_namespaces"):
            args.append("--all-namespaces")
        result = run_kubectl(args, namespace=arguments.get("namespace"))

    elif name == "kubectl_describe":
        args = ["describe", arguments["resource"], arguments["name"]]
        result = run_kubectl(args, namespace=arguments.get("namespace"))

    elif name == "kubectl_logs":
        args = ["logs", arguments["pod"]]
        if arguments.get("container"):
            args.extend(["-c", arguments["container"]])
        tail = arguments.get("tail", 100)
        args.extend(["--tail", str(tail)])
        if arguments.get("previous"):
            args.append("--previous")
        result = run_kubectl(args, namespace=arguments.get("namespace"))

    elif name == "kubectl_top":
        args = ["top", arguments["resource"]]
        if arguments.get("name"):
            args.append(arguments["name"])
        result = run_kubectl(args, namespace=arguments.get("namespace"))

    elif name == "kubectl_exec":
        args = ["exec", arguments["pod"], "--"]
        if arguments.get("container"):
            args = ["exec", arguments["pod"], "-c", arguments["container"], "--"]
        args.extend(arguments["command"].split())
        result = run_kubectl(args, namespace=arguments.get("namespace"))

    elif name == "kubectl_events":
        args = ["get", "events", "--sort-by=.lastTimestamp"]
        if arguments.get("resource_name"):
            args.extend(["--field-selector", f"involvedObject.name={arguments['resource_name']}"])
        if arguments.get("all_namespaces"):
            args.append("--all-namespaces")
        result = run_kubectl(args, namespace=arguments.get("namespace"))

    elif name == "kubectl_raw":
        cmd_args = arguments["command"].split()
        result = run_kubectl(cmd_args)

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    if "error" in result:
        return [TextContent(type="text", text=f"Error: {result['error']}")]

    output = f"$ {result['command']}\n\n{result['stdout']}"
    if result.get("stderr"):
        output += f"\nSTDERR:\n{result['stderr']}"
    if result.get("returncode", 0) != 0:
        output += f"\n(exit code: {result['returncode']})"

    return [TextContent(type="text", text=output)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
