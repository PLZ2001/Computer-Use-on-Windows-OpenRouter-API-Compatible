"""
Client for interacting with Openrouter API.
"""
import json
import os
import httpx
from typing import Any, Dict, List, Optional, Union
from anthropic.types.beta import BetaMessage

class OpenrouterResponse:
    """Wrapper for Openrouter API response to match Anthropic's interface."""
    def __init__(self, beta_message: BetaMessage, http_response: httpx.Response):
        self.beta_message = beta_message
        self.http_response = http_response

    def parse(self) -> BetaMessage:
        return self.beta_message

class OpenrouterClient:
    """Client for interacting with Openrouter API."""
    
    SUPPORTED_MODELS = ["anthropic/claude-3.5-sonnet:beta"]  # List of supported models
    
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
                """Method chaining to match Anthropic's interface"""
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
                    OpenrouterResponse: Wrapper containing both the HTTP response and parsed BetaMessage
                    
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
                            "description": "A tool that allows you to interact with the screen, keyboard, and mouse. Where possible/feasible, try to use 'bash' tool instead of the 'computer' tool for better results.",
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
                                        "description": "'action' is the action performed on the screen. When searching for targets on the screen, try to interact with the screen with 'scroll_up' or 'scroll_down' to explore the unseen space."
                                    },
                                    "text": {
                                        "type": "string",
                                        "description": "'text' is required for action of 'key' or 'type'. When you want to use the Windows key, please use the 'win' string. "
                                    },
                                    "coordinate": {
                                        "type": "array",
                                        "prefixItems": [
                                            { "type": "number" },
                                            { "type": "number" },
                                        ],
                                        "items": { "type": "number" },
                                        "description": "'coordinate' is required for actions of mouse moving, clicking or dragging."
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
                            "description": "A tool for executing shell commands. Where possible/feasible, try to use 'bash' tool instead of the 'computer' tool for better results.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "command": {
                                        "type": "string",
                                        "description": "'command' is the command to be executed."
                                    },
                                    "restart": {
                                        "type": "boolean",
                                        "description": "set 'restart' true to restart the tool after execution. Default value: false. "
                                    }
                                }
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
                        # Convert Openrouter response to Anthropic format
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
                # Create BetaMessage response
                beta_message = BetaMessage(
                    id="msg_" + http_response.headers.get("X-Request-ID", "unknown"),
                    type="message",
                    role="assistant",
                    content=content,
                    model=self.client.model,
                    stop_reason= "tool_use" if openrouter_response['choices'][0]['finish_reason'] == "tool_calls" else "stop_sequence",
                    stop_sequence=None,
                    usage={
                        "input_tokens": openrouter_response['usage']['prompt_tokens'],  
                        "output_tokens": openrouter_response['usage']['completion_tokens']
                    }
                )
                
                return OpenrouterResponse(beta_message, http_response), openrouter_response['choices'][0]['message']