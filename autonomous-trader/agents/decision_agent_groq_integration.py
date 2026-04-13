# Add to agents/decision_agent.py after existing imports

from agents.recommendation_generator import RecommendationGenerator

class DecisionAgent:
    def __init__(self):
        # ... existing code ...
        self.recommendation_generator = RecommendationGenerator()
    
    def execute(self, state):
        # ... existing analysis code ...
        
        # After all analysis, generate professional recommendation
        analysis_data = {
            'symbol': symbol,
            'company_name': self.get_company_name(symbol),
            'current_price': current_price,
            'technical': {
                'rsi': technical_score['rsi'],
                'macd': technical_score['macd'],
                'price_vs_ma': technical_score['price_vs_ma'],
                'momentum': technical_score['momentum'],
                'score': technical_score['overall']
            },
            'sentiment': {
                'score': sentiment_score,
                'label': self.get_sentiment_label(sentiment_score),
                'article_count': len(state['news_data'].get(symbol, [])),
                'headlines': self.get_key_headlines(symbol, state)
            },
            'fundamental': {
                'pe_ratio': fundamental_score['pe_ratio'],
                'eps': fundamental_score['eps'],
                'roe': fundamental_score['roe'],
                'debt_equity': fundamental_score['debt_equity'],
                'score': fundamental_score['overall']
            },
            'ml': {
                'lstm_score': ml_score,
                'xgb_score': ml_score,  # Both from ensemble
                'confidence': confidence
            },
            'volume': {
                'avg_volume': volume_data['avg'],
                'volume_ratio': volume_data['ratio']
            }
        }
        
        # Generate professional recommendation with Groq
        recommendation = self.recommendation_generator.generate_recommendation(analysis_data)
        
        return recommendation
