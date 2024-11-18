"""
Client for interacting with Openrouter API.
"""
import json
from typing import TypedDict, List, Dict, Any, Optional

import httpx

class OpenrouterResponse:
    """Wrapper for Openrouter API response to match interface."""
    def __init__(self, message, http_response: httpx.Response):
        self.message = message
        self.http_response = http_response

    def parse(self):
        return self.message

class OpenrouterClient:
    """Client for interacting with Openrouter API."""
        
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        # Initialize beta property immediately
        self.beta = self.Beta(self)
        self._initialized = False
        
    async def initialize(self):
        """Initialize the client by testing the connection to Openrouter"""
        try:
            async with httpx.AsyncClient() as async_client:
                response = await async_client.get(f"{self.base_url}/models")
                response.raise_for_status()
            self._initialized = True
            return self
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Openrouter: {e}")
            
        
    class Beta:
        def __init__(self, client):
            self.client = client
            self.messages = self.Messages(client)
            
        class Messages:
            def __init__(self, client):
                self.client = client
                
            def with_raw_response(self):
                """Method chaining to match interface"""
                return self
                
            async def create(
                self,
                max_tokens: int,
                messages: list[dict],
                system: list[dict],
            ) -> OpenrouterResponse:
                """
                Create a chat completion with Openrouter API.
                
                Args:
                    max_tokens: Maximum tokens to generate
                    messages: Chat history in the format [{"role": str, "content": str}]
                    model: Model name to use (must be one of the supported models)
                    system: System messages in the format [{"text": str}]
                    tools: List of available tools (currently not used by Openrouter)
                    betas: List of beta features to enable (currently not used by Openrouter)
                    
                Returns:
                    OpenrouterResponse: Wrapper containing both the HTTP response and parsed Message
                    
                Raises:
                    ValueError: If the model is not supported or if the input format is invalid
                    RuntimeError: If connection or model loading fails
                """
                # Validate input parameters
                if not messages or not isinstance(messages, list):
                    raise ValueError("Messages must be a non-empty list")
                
                for msg in messages:
                    if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                        raise ValueError("Each message must be a dict with 'role' and 'content' keys")
                    if msg["role"] not in ["user", "assistant", "system", "tool"]:
                        raise ValueError(f"Invalid message role: {msg['role']}")
                
                if not self.client.model:
                    raise ValueError("Model name is required")
                                
                # Convert messages to Openrouter format
                openrouter_messages = [{
                    "role": "system",
                    "content": system
                }]
                
                for msg in messages:
                    openrouter_messages.append(msg)
                
                # Prepare Openrouter request
                request_data = {
                    "model": self.client.model,
                    "messages": openrouter_messages,
                    "stream": False,
                    "max_tokens": max_tokens,
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "computer",
                            "description": "A comprehensive tool that enables interaction with computer input/output devices including screen, keyboard, and mouse. It supports various operations like typing, clicking, scrolling and taking screenshots.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "action": {
                                        "type": "string",
                                        "enum": [
                                            "key",
                                            "type",
                                            "mouse_move",
                                            "left_click",
                                            "left_click_drag",
                                            "right_click",
                                            "middle_click",
                                            "double_click",
                                            "screenshot",
                                            "cursor_position",
                                            "scroll_up",
                                            "scroll_down",
                                        ],
                                        "description": "Specifies the type of action to perform on the computer. Each action corresponds to a specific interaction with the input/output devices."
                                    },
                                    "text": {
                                        "type": "string",
                                        "description": "Required for keyboard input actions ('key' or 'type'). For Windows key, use 'win'."
                                    },
                                    "coordinate": {
                                        "type": "array",
                                        "prefixItems": [
                                            { "type": "number" },
                                            { "type": "number" },
                                        ],
                                        "items": { "type": "number" },
                                        "description": "Required for mouse-related actions. Specifies the x,y coordinates on screen for mouse movement, clicking, or dragging operations."
                                    },
                                    "scroll_amount": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "description": "Optional for scroll_up and scroll_down actions. Specifies the amount to scroll. Must be a positive integer. Default is 400. The direction is determined by the action type (scroll_up or scroll_down)."
                                    },
                                    "repeat": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "description": "Optional for all actions. Specifies how many times to repeat the action. Default is 1. For example, can be used to repeat key presses, mouse clicks, scrolling, or any other action multiple times."
                                    }
                                },
                                "required": [
                                    "action"
                                ]
                            }
                        }
                    },{
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "description": "A Windows command execution tool that maintains a persistent cmd.exe session. Supports command execution with automatic timeout control and screenshot capability for commands without output.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "command": {
                                        "type": "string",
                                        "description": "The Windows command to execute in the persistent cmd.exe session. Commands timeout after 120 seconds."
                                    },
                                    "restart": {
                                        "type": "boolean",
                                        "description": "Optional parameter to restart the cmd.exe session. Use this if the session becomes unresponsive or times out."
                                    }
                                }
                            }
                        }
                    },{
                        "type": "function",
                        "function": {
                            "name": "str_replace_editor",
                            "description": "A powerful file editing tool that supports viewing, creating, editing, and managing file content with history tracking.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "command": {
                                        "type": "string",
                                        "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                                        "description": "The editing command to perform: view (show file content), create (create new file), str_replace (replace text), insert (insert at line), undo_edit (revert last change)"
                                    },
                                    "path": {
                                        "type": "string",
                                        "description": "The absolute path of the file to operate on"
                                    },
                                    "file_text": {
                                        "type": "string",
                                        "description": "Required for 'create' command. The content to write to the new file."
                                    },
                                    "view_range": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                        "description": "Optional for 'view' command. Specify start and end line numbers to view [start, end]. Use -1 for end to view until the last line."
                                    },
                                    "old_str": {
                                        "type": "string",
                                        "description": "Required for 'str_replace' command. The string to be replaced."
                                    },
                                    "new_str": {
                                        "type": "string",
                                        "description": "Required for 'str_replace' and 'insert' commands. The new string to insert or replace with."
                                    },
                                    "insert_line": {
                                        "type": "integer",
                                        "description": "Required for 'insert' command. The line number where the new content should be inserted."
                                    }
                                },
                                "required": ["command", "path"]
                            }
                        }
                    }],
                }
                try:
                    # Make request to Openrouter API asynchronously
                    async_client = httpx.AsyncClient(base_url=self.client.base_url, timeout=60.0)
                    try:
                        http_response = await async_client.post(
                            "/chat/completions",
                            headers={
                            "Authorization": f"Bearer {self.client.api_key}"},
                            data=json.dumps(request_data)
                        )
                        http_response.raise_for_status()
                    except httpx.TimeoutException as e:
                        raise RuntimeError(f"Request to Openrouter timed out: {e}")
                    except httpx.RequestError as e:
                        raise RuntimeError(f"Failed to connect to Openrouter: {e}")
                    except httpx.HTTPStatusError as e:
                        raise RuntimeError(f"Openrouter API returned error {e.response.status_code}: {e.response.text}")
                
                    try:
                        # Convert Openrouter response to Message format
                        openrouter_response = http_response.json()
                        print(openrouter_response)
                    except ValueError as e:
                        raise ValueError(f"Invalid JSON response from Openrouter: {e}")
                
                    if not isinstance(openrouter_response, dict):
                        raise ValueError(f"Expected dict response, got {type(openrouter_response)}")
                    
                    if "message" not in openrouter_response['choices'][0]:
                        raise ValueError(f"Response missing 'message' field: {openrouter_response}")
                        
                except Exception as e:
                    if isinstance(e, (ValueError, RuntimeError)):
                        raise
                    raise RuntimeError(f"Unexpected error while getting response from Openrouter: {e}")
                
                content = []
                if openrouter_response['choices'][0]["message"]["content"] is not None:
                    content.append({"type": "text", "text": openrouter_response['choices'][0]["message"]["content"]})
                if 'tool_calls' in openrouter_response['choices'][0]['message'].keys():
                    for item in openrouter_response['choices'][0]['message']['tool_calls']:
                        content.append({"type": "tool_use", 
                                        "name": item['function']['name'],
                                        "input": json.loads(item['function']['arguments']),
                                        'id': item['id']
                        })
                # Create Message response
                message = {
                    "id": "msg_" + http_response.headers.get("X-Request-ID", "unknown"),
                    "type": "message",
                    "role": "assistant",
                    "content": content,
                    "model": self.client.model,
                    "stop_reason": "tool_use" if openrouter_response['choices'][0]['finish_reason'] == "tool_calls" else "stop_sequence",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": openrouter_response['usage']['prompt_tokens'],  
                        "output_tokens": openrouter_response['usage']['completion_tokens']
                    }
                }
                
                return OpenrouterResponse(message, http_response), openrouter_response['choices'][0]['message']
