# Add to data/storage/database.py

class DatabaseManager:
    # ... existing code ...
    
    def store_recommendation(self, recommendation: Dict):
        '''Store detailed recommendation with LLM reasoning'''
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO recommendations (
                symbol, company_name, action, current_price,
                llm_reasoning, confidence, timestamp,
                technical_score, sentiment_score, ml_score, fundamental_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            recommendation['symbol'],
            recommendation['company_name'],
            recommendation['action'],
            recommendation['current_price'],
            recommendation['llm_reasoning'],
            recommendation['confidence'],
            recommendation['timestamp'],
            recommendation['technical_score'],
            recommendation['sentiment_score'],
            recommendation['ml_score'],
            recommendation['fundamental_score']
        ))
        self.conn.commit()
    
    def get_latest_recommendations(self, limit=20):
        '''Get latest recommendations with full details'''
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM recommendations
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
    
    def get_recommendation_accuracy(self, days=30):
        '''Calculate historical accuracy of recommendations'''
        # Compare recommendations vs actual price movements
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as correct
            FROM recommendations
            WHERE timestamp > datetime('now', '-{days} days')
        '''.format(days=days))
        result = cursor.fetchone()
        if result['total'] > 0:
            return (result['correct'] / result['total']) * 100
        return 0
