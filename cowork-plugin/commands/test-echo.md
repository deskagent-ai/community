# Agent: Test Echo

A simple test agent that echoes back the input message. Used for testing the agent-as-tool architecture.

## Inputs

Message to echo:
{{INPUT.message}}

Optional prefix:
{{INPUT.prefix}}

## Task

Return a JSON response with the echoed message:

```json
{
  "echo": "[prefix] message",
  "timestamp": "",
  "success": true
}
```

If prefix is provided, prepend it to the message with a space.
If no prefix, just return the message as-is.
