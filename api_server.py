from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import asyncio
import uvicorn
import json
import os
import threading
from typing import Optional, Dict, Any, List
import uuid
import logging

# Import your agent code
from config import CONFIG
from core.agent import Agent
from tools.tool_registry import ToolRegistry
from llm.azure_openai_client import AzureOpenAIClient
from core.planner import Planner
from core.memory import Memory
from core.enhanced_memory import EnhancedMemory
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("manus-api")

app = FastAPI(title="Manus-Like Agent API")

# Store active sessions and their message queues
active_sessions = {}
user_response_queues = {}
active_agents = {}  # Store agent instances for stopping

class TaskRequest(BaseModel):
    task: str
    session_id: Optional[str] = None

class UserResponse(BaseModel):
    response: str

# Create an agent instance
def create_agent(session_id: str):
    # Load system prompt
    prompt_path = os.path.join(CONFIG["system"]["prompt_dir"], "system_prompt.txt")
    if os.path.exists(prompt_path):
        with open(prompt_path, encoding="utf-8") as f:
            system_prompt = f.read()
    else:
        system_prompt = "あなたはManusのようなエージェントです。"

    # Add an interaction rules section to the prompt to ensure proper tool usage
    interaction_rules = """
<interaction_rules>
- When you need information from the user, always use message_ask_user tool, not message_notify_user
- message_notify_user should only be used for one-way notifications that don't require a response
- After sending a question with message_ask_user, wait for the user's response before proceeding
- Never repeat questions if you don't receive a response; instead, use message_ask_user again only if necessary
</interaction_rules>
"""
    system_prompt += interaction_rules

    # Create LLM client
    llm_client = AzureOpenAIClient()
    planner = Planner(llm_client)
    registry = ToolRegistry()

    # Register regular tools
    for mod in [
        "tools.shell_tools",
        "tools.file_tools",
        "tools.info_tools",
        "tools.deploy_tools",
        "tools.browser_tools",
        "tools.codeact_tools",
        "tools.system_tools",
    ]:
        registry.register_tools_from_module(mod)

    # Register custom message tools for API communication
    def message_notify_handler(message, attachments=None):
        logger.info(f"[{session_id}] Notify: {message[:100]}...")
        # Add message to session's queue for frontend to fetch
        if session_id in active_sessions:
            asyncio.run_coroutine_threadsafe(
                active_sessions[session_id].put({
                    "type": "notify",
                    "content": message,
                    "attachments": attachments
                }),
                asyncio.get_event_loop()
            )
        return "メッセージを送信しました"

    def message_ask_handler(message, attachments=None, suggest_user_takeover="none"):
        logger.info(f"[{session_id}] Ask: {message[:100]}...")
        # Add question to session's queue
        if session_id in active_sessions:
            asyncio.run_coroutine_threadsafe(
                active_sessions[session_id].put({
                    "type": "ask",
                    "content": message,
                    "attachments": attachments,
                    "suggest_user_takeover": suggest_user_takeover
                }),
                asyncio.get_event_loop()
            )
        
        # Wait for user response
        response_queue = user_response_queues.get(session_id)
        if response_queue:
            try:
                # Block until response is received (with timeout)
                future = asyncio.run_coroutine_threadsafe(
                    response_queue.get(), 
                    asyncio.get_event_loop()
                )
                response = future.result(timeout=300)  # 5 minute timeout
                logger.info(f"[{session_id}] Got response: {response[:50]}...")
                return response
            except Exception as e:
                logger.error(f"[{session_id}] Response error: {str(e)}")
                return "タイムアウトしました"
        logger.warning(f"[{session_id}] No response queue")
        return "セッションが無効です"

    # Register the message handlers
    registry.register_tool(
        "message_notify_user",
        message_notify_handler,
        registry.get_tool_spec("message_notify_user")
    )
    registry.register_tool(
        "message_ask_user",
        message_ask_handler,
        registry.get_tool_spec("message_ask_user")
    )

    # Initialize memory
    workspace_dir = os.path.join(CONFIG["system"]["workspace_dir"], session_id)
    os.makedirs(workspace_dir, exist_ok=True)
    
    if CONFIG["memory"].get("use_vector_memory", False):
        memory = EnhancedMemory(workspace_dir=workspace_dir)
    else:
        memory = Memory(workspace_dir=workspace_dir)

    agent = Agent(llm_client, system_prompt, registry, planner, memory)
    active_agents[session_id] = agent
    return agent

# Run agent in background thread
def start_agent_thread(agent, task, session_id):
    try:
        logger.info(f"[{session_id}] Starting agent thread for task: {task[:50]}...")
        agent.start(task)
        logger.info(f"[{session_id}] Agent completed task")
        
        # Add completion message after agent finishes
        asyncio.run_coroutine_threadsafe(
            active_sessions[session_id].put({
                "type": "status", 
                "content": "タスクが完了しました"
            }), 
            asyncio.get_event_loop()
        )
    except Exception as e:
        logger.error(f"[{session_id}] Agent error: {str(e)}")
        
        # Send error message
        asyncio.run_coroutine_threadsafe(
            active_sessions[session_id].put({
                "type": "error",
                "content": f"エラー発生: {str(e)}"
            }),
            asyncio.get_event_loop()
        )

# Run agent
async def run_agent(task: str, session_id: str):
    try:
        # Create message queue if not exists
        if session_id not in active_sessions:
            active_sessions[session_id] = asyncio.Queue()
        
        if session_id not in user_response_queues:
            user_response_queues[session_id] = asyncio.Queue()
        
        # Create agent
        agent = create_agent(session_id)
        
        # Notify frontend that agent is starting
        await active_sessions[session_id].put({
            "type": "status",
            "content": "エージェントが起動しました"
        })
        
        # Start agent in a separate thread
        thread = threading.Thread(
            target=start_agent_thread, 
            args=(agent, task, session_id)
        )
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        logger.error(f"[{session_id}] Agent startup error: {str(e)}")
        # Add error message
        await active_sessions[session_id].put({
            "type": "error",
            "content": f"エラー発生: {str(e)}"
        })

@app.post("/api/task", response_model=Dict[str, str])
async def start_task(request: TaskRequest, background_tasks: BackgroundTasks):
    # Generate session ID if not provided
    session_id = request.session_id or str(uuid.uuid4())
    logger.info(f"Starting task for session {session_id}: {request.task[:50]}...")
    
    # Start agent in background
    background_tasks.add_task(run_agent, request.task, session_id)
    
    return {"status": "started", "session_id": session_id}

@app.get("/api/messages/{session_id}")
async def get_messages(session_id: str):
    """Long polling endpoint to get agent messages"""
    if session_id not in active_sessions:
        return {"status": "error", "message": "セッションが見つかりません"}
    
    try:
        # Wait for message with timeout
        message = await asyncio.wait_for(active_sessions[session_id].get(), timeout=30)
        return {"status": "success", "message": message}
    except asyncio.TimeoutError:
        return {"status": "timeout", "message": None}

@app.post("/api/response/{session_id}")
async def submit_response(session_id: str, data: UserResponse):
    """Submit user response to agent question"""
    if session_id not in user_response_queues:
        return {"status": "error", "message": "セッションが見つかりません"}
    
    logger.info(f"[{session_id}] Received user response: {data.response[:50]}...")
    await user_response_queues[session_id].put(data.response)
    return {"status": "success"}

@app.post("/api/stop/{session_id}")
async def stop_agent(session_id: str):
    """Stop running agent"""
    logger.info(f"Stopping agent for session {session_id}")
    
    # Get agent instance and stop it
    if session_id in active_agents:
        try:
            active_agents[session_id].stop()
            # Clean up
            if session_id in active_sessions:
                await active_sessions[session_id].put({
                    "type": "status", 
                    "content": "エージェントが停止されました"
                })
            return {"status": "stopped"}
        except Exception as e:
            logger.error(f"Error stopping agent: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    return {"status": "not_found", "message": "エージェントが見つかりません"}

# WebSocket alternative for more efficient communication
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info(f"WebSocket connection established for session {session_id}")
    
    if session_id not in active_sessions:
        active_sessions[session_id] = asyncio.Queue()
    
    if session_id not in user_response_queues:
        user_response_queues[session_id] = asyncio.Queue()
    
    # Handle incoming messages (user responses)
    async def receive_messages():
        try:
            while True:
                data = await websocket.receive_json()
                logger.info(f"[{session_id}] WebSocket received: {data.get('type', 'unknown')}")
                
                if data.get("type") == "response":
                    content = data.get("content", "")
                    logger.info(f"[{session_id}] User response via WebSocket: {content[:50]}...")
                    await user_response_queues[session_id].put(content)
                
                elif data.get("type") == "task":
                    content = data.get("content", "")
                    logger.info(f"[{session_id}] Task request via WebSocket: {content[:50]}...")
                    asyncio.create_task(run_agent(content, session_id))
                
                elif data.get("type") == "stop":
                    if session_id in active_agents:
                        logger.info(f"[{session_id}] Stop request via WebSocket")
                        active_agents[session_id].stop()
                        await active_sessions[session_id].put({
                            "type": "status", 
                            "content": "エージェントが停止されました"
                        })
        
        except WebSocketDisconnect:
            logger.info(f"Client disconnected: {session_id}")
        except Exception as e:
            logger.error(f"Error in WebSocket receive: {str(e)}")
    
    # Send messages to client
    async def send_messages():
        try:
            while True:
                message = await active_sessions[session_id].get()
                logger.info(f"[{session_id}] Sending WebSocket message: {message.get('type', 'unknown')}")
                await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error in WebSocket send: {str(e)}")
    
    # Run both tasks concurrently
    receive_task = asyncio.create_task(receive_messages())
    send_task = asyncio.create_task(send_messages())
    
    try:
        await asyncio.gather(receive_task, send_task)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        receive_task.cancel()
        send_task.cancel()
        logger.info(f"WebSocket connection closed for session {session_id}")

@app.get("/")
async def root():
    return {"status": "running", "message": "Manus-Like Agent API is running"}

if __name__ == "__main__":
    # Add command line arguments for port configuration
    import argparse
    parser = argparse.ArgumentParser(description='Manus API Server')
    parser.add_argument('--port', type=int, default=8001, help='Port to run the server on')
    parser.add_argument('--host', type=str, default="0.0.0.0", help='Host to bind to')
    args = parser.parse_args()
    
    logger.info(f"Starting API server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
