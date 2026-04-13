from fastapi import APIRouter
from data.storage.recommendation_db import RecommendationDB

router = APIRouter()

@router.get('/live')
async def get_live_recommendations():
    db = RecommendationDB()
    try:
        recommendations = db.get_latest_recommendations(limit=15)
        return {'recommendations': recommendations, 'count': len(recommendations), 'status': 'success'}
    except Exception as e:
        return {'error': str(e), 'recommendations': [], 'count': 0, 'status': 'error'}
    finally:
        db.close()

@router.get('/history')
async def get_recommendation_history(limit: int = 50):
    db = RecommendationDB()
    try:
        return db.get_latest_recommendations(limit=limit)
    except Exception as e:
        return {'error': str(e)}
    finally:
        db.close()
