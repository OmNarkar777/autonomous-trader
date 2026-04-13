from fastapi import APIRouter
from typing import List
router = APIRouter()

@router.get("/prices")
async def get_prices(symbols: str = "RELIANCE.NS"):
    return []

@router.get("/decisions")  
async def get_decisions(limit: int = 10):
    return []
