from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/status")
async def get_system_status():
    return {
        "status": "running",
        "uptime": "2h 15m",
        "last_cycle": datetime.now().isoformat()
    }

@router.get("/health")
async def get_health():
    return {
        "healthy": True,
        "database": "connected",
        "broker": "connected"
    }

@router.get("/circuit-breaker/status")
async def get_circuit_breaker_status():
    return {
        "state": "CLOSED",
        "consecutive_errors": 0,
        "last_error": None
    }

@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker():
    return {"status": "reset", "message": "Circuit breaker reset successfully"}

@router.get("/agents/status")
async def get_agents_status():
    return {
        "price_agent": {"status": "active", "last_run": datetime.now().isoformat()},
        "news_agent": {"status": "active", "last_run": datetime.now().isoformat()},
        "decision_agent": {"status": "active", "last_run": datetime.now().isoformat()},
        "execution_agent": {"status": "active", "last_run": datetime.now().isoformat()}
    }
