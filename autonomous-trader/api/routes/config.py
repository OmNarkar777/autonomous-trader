from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def get_config():
    return {"watchlist": ["RELIANCE.NS", "TCS.NS"]}
