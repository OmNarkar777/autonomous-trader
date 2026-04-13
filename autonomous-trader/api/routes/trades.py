from fastapi import APIRouter
from typing import List
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class Trade(BaseModel):
    id: int = 1
    symbol: str = "RELIANCE.NS"
    action: str = "BUY"
    quantity: int = 10
    entry_price: float = 1424.50
    timestamp: str = datetime.now().isoformat()

@router.get("/")
async def get_trades(limit: int = 100):
    return []

@router.get("/recent")
async def get_recent_trades():
    return []
