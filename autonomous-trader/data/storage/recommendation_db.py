import sqlite3
from typing import List, Dict, Any

class RecommendationDB:
    def __init__(self, db_path='autonomous_trader.db'):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
    
    def store_recommendation(self, rec: Dict[str, Any]):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO recommendations (
                symbol, company_name, action, current_price, target_price,
                stop_loss, llm_reasoning, confidence, timestamp,
                technical_score, sentiment_score, ml_score, fundamental_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            rec.get('symbol'), rec.get('company_name'), rec.get('action'),
            rec.get('current_price'), rec.get('target_price'), rec.get('stop_loss'),
            rec.get('llm_reasoning'), rec.get('confidence'), rec.get('timestamp'),
            rec.get('technical_score'), rec.get('sentiment_score'),
            rec.get('ml_score'), rec.get('fundamental_score')
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_latest_recommendations(self, limit=20):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM recommendations ORDER BY timestamp DESC LIMIT ?', (limit,))
        return [dict(row) for row in cursor.fetchall()]
    
    def close(self):
        self.conn.close()
