import os
from groq import Groq
from datetime import datetime
from typing import Dict, Any

class RecommendationGenerator:
    def __init__(self):
        self.client = Groq(api_key=os.getenv('GROQ_API_KEY'))
        self.model = 'llama-3.3-70b-versatile'
    
    def generate_recommendation(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        '''Generate professional recommendation using Groq LLM'''
        
        # Build detailed prompt with all analysis
        prompt = f'''
You are a professional stock analyst at a top investment firm. Analyze this stock and provide a clear BUY/SELL/HOLD recommendation.

STOCK: {analysis_data['symbol']}
COMPANY: {analysis_data['company_name']}
CURRENT PRICE: 

ANALYSIS DATA:
????????????????????????????????????????
Technical Analysis:
- RSI: {analysis_data['technical']['rsi']:.1f}
- MACD: {analysis_data['technical']['macd']:.2f}
- Price vs 50-day MA: {analysis_data['technical']['price_vs_ma']:.1f}%
- Momentum: {analysis_data['technical']['momentum']}

Sentiment Analysis:
- News Sentiment: {analysis_data['sentiment']['score']:.2f} ({analysis_data['sentiment']['label']})
- Articles Analyzed: {analysis_data['sentiment']['article_count']}
- Key Headlines: {analysis_data['sentiment']['headlines']}

Fundamental Analysis:
- P/E Ratio: {analysis_data['fundamental']['pe_ratio']:.2f}
- EPS: 
- ROE: {analysis_data['fundamental']['roe']:.1f}%
- Debt/Equity: {analysis_data['fundamental']['debt_equity']:.2f}

Machine Learning Prediction:
- LSTM Model: {analysis_data['ml']['lstm_score']:.1%} probability of upward movement
- XGBoost Model: {analysis_data['ml']['xgb_score']:.1%} probability of upward movement
- Ensemble Confidence: {analysis_data['ml']['confidence']:.1%}

Volume & Liquidity:
- Average Volume: {analysis_data['volume']['avg_volume']:,.0f}
- Current Volume vs Average: {analysis_data['volume']['volume_ratio']:.1f}x

PROVIDE:
1. ACTION: Clearly state BUY, SELL, or HOLD
2. CONFIDENCE: Rate your confidence 1-10
3. TARGET PRICE: Specific price target (be precise)
4. STOP LOSS: Specific stop loss price
5. TIME HORIZON: Expected holding period
6. REASONING: 3-4 sentences explaining WHY this is the right move
7. RISKS: 2-3 key risks to consider
8. CATALYSTS: 2-3 events that could drive the stock

Write in a confident, professional tone. Be specific with numbers. Sound like a top analyst.
'''

        # Call Groq API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': 'You are a top-tier stock analyst known for accurate predictions and clear communication. Your recommendations are trusted by thousands of investors.'},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.3,  # Lower = more consistent
                max_tokens=1000
            )
            
            llm_output = response.choices[0].message.content
            
            # Parse the LLM output (you'd use regex or structured output here)
            recommendation = self._parse_recommendation(llm_output, analysis_data)
            
            return recommendation
            
        except Exception as e:
            print(f'Groq API error: {e}')
            return self._fallback_recommendation(analysis_data)
    
    def _parse_recommendation(self, llm_output: str, analysis_data: Dict) -> Dict:
        '''Parse LLM output into structured recommendation'''
        
        # Extract action (BUY/SELL/HOLD)
        action = 'HOLD'
        if 'BUY' in llm_output.upper()[:100]:
            action = 'BUY'
        elif 'SELL' in llm_output.upper()[:100]:
            action = 'SELL'
        
        return {
            'symbol': analysis_data['symbol'],
            'company_name': analysis_data['company_name'],
            'action': action,
            'current_price': analysis_data['current_price'],
            'llm_reasoning': llm_output,  # Full LLM output
            'confidence': analysis_data['ml']['confidence'],
            'timestamp': datetime.now().isoformat(),
            'technical_score': analysis_data['technical']['score'],
            'sentiment_score': analysis_data['sentiment']['score'],
            'ml_score': analysis_data['ml']['confidence'],
            'fundamental_score': analysis_data['fundamental']['score']
        }
    
    def _fallback_recommendation(self, analysis_data: Dict) -> Dict:
        '''Fallback if Groq API fails'''
        return {
            'symbol': analysis_data['symbol'],
            'action': 'HOLD',
            'llm_reasoning': 'Analysis in progress. Please check back shortly.',
            'confidence': 0.5
        }
