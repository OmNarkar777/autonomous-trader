"""
api/main.py - FastAPI backend for autonomous trading system.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time

from api.routes import portfolio, trades, system, config as config_routes, prices, recommendations
from api.websocket.live_feed import router as websocket_router
from config.logging_config import get_logger

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Autonomous Trading API")
    logger.info("API documentation: http://localhost:8000/docs")
    yield
    logger.info("🛑 Shutting down Autonomous Trading API")

app = FastAPI(
    title="Autonomous Trading System API",
    description="RESTful API and WebSocket feeds for autonomous stock trading",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.time() - start_time)
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": str(exc)})

@app.get("/")
async def root():
    return {"name": "Autonomous Trading System API", "version": "1.0.0", "status": "operational"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}

# Include routers
app.include_router(prices.router, prefix="/api", tags=["Prices"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(trades.router, prefix="/api/trades", tags=["Trades"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(config_routes.router, prefix="/api/config", tags=["Config"])
app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])
app.include_router(recommendations.router, prefix="/api/recommendations", tags=["Recommendations"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
