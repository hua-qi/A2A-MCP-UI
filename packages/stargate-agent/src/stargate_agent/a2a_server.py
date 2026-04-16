"""A2A Server setup using a2a-sdk"""
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from stargate_agent.agent_card_builder import build_agent_card
from stargate_agent.a2a_executor import StargateAgentExecutor


def create_a2a_app():
    """Create A2A FastAPI application"""
    
    # Build agent card with extensions
    agent_card = build_agent_card()
    
    # Create task store
    task_store = InMemoryTaskStore()
    
    # Create custom agent executor
    agent_executor = StargateAgentExecutor()
    
    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=task_store,
    )
    
    # Create A2A FastAPI application
    a2a_app = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    
    # Build and return the FastAPI app
    return a2a_app.build()


def get_a2a_app():
    """Get A2A app instance for uvicorn"""
    return create_a2a_app()
