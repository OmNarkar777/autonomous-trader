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
You are Warren Buffett's personal stock analyst. A retail investor with limited time has asked you for ONE clear trade recommendation. They will follow your advice EXACTLY.

STOCK: {analysis_data['symbol']} - {analysis_data['company_name']}
CURRENT MARKET PRICE: ₹{analysis_data['current_price']:.2f}

YOUR COMPLETE ANALYSIS DATA:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 TECHNICAL ANALYSIS:
- RSI (14): {analysis_data['technical']['rsi']:.1f} (Below 30 = Oversold, Above 70 = Overbought)
- MACD Signal: {analysis_data['technical']['macd']:.2f} (Positive = Bullish)
- Price vs 50-MA: {analysis_data['technical']['price_vs_ma']:.1f}% (Above MA = Strong)
- Momentum: {analysis_data['technical']['momentum']}
- Overall Technical Score: {analysis_data['technical']['score']*10:.1f}/10

📰 SENTIMENT ANALYSIS:
- News Sentiment: {analysis_data['sentiment']['score']:.2f} ({analysis_data['sentiment']['label']})
- Articles Analyzed: {analysis_data['sentiment']['article_count']}
- Recent Headlines: {', '.join(analysis_data['sentiment']['headlines'][:3])}

📈 FUNDAMENTAL ANALYSIS:
- P/E Ratio: {analysis_data['fundamental']['pe_ratio']:.2f} (Lower = Cheaper, Industry avg ~20-25)
- EPS (Earnings): ₹{analysis_data['fundamental']['eps']:.2f}
- ROE (Profitability): {analysis_data['fundamental']['roe']:.1f}% (Above 15% = Excellent)
- Debt/Equity: {analysis_data['fundamental']['debt_equity']:.2f} (Below 1 = Healthy)
- Fundamental Score: {analysis_data['fundamental']['score']*10:.1f}/10

🤖 MACHINE LEARNING PREDICTION:
- LSTM Neural Network: {analysis_data['ml']['lstm_score']:.1%} probability of price increase
- XGBoost Model: {analysis_data['ml']['xgb_score']:.1%} probability of price increase
- Combined AI Confidence: {analysis_data['ml']['confidence']:.1%}

💰 VOLUME & LIQUIDITY:
- Average Daily Volume: {analysis_data['volume']['avg_volume']:,.0f} shares
- Today's Volume: {analysis_data['volume']['volume_ratio']:.1f}x average (Above 1.5x = Strong interest)

PROVIDE THIS EXACT FORMAT (copy exactly):

**🎯 RECOMMENDATION: BUY / SELL / HOLD**

**💪 CONFIDENCE: X/10**
Rate how confident you are (8+ = Very confident, 5-7 = Moderate, <5 = Low confidence)

**📍 ENTRY STRATEGY:**
Be SPECIFIC. Choose ONE:
- Option A: "EXECUTE NOW: Buy at current market price ₹{analysis_data['current_price']:.2f} immediately"
- Option B: "WAIT: Only buy if price drops to ₹[PRICE] (X% below current)"
State clearly: EXECUTE NOW or WAIT FOR [specific price]

**🎯 TARGET PRICE: ₹[EXACT NUMBER]**
Calculate based on technical levels and fundamentals. Be precise (e.g., ₹2,850, not "around 2,850")
Show expected gain: +X%

**🛡️ STOP LOSS: ₹[EXACT NUMBER]**
Mandatory risk management. Set at 4-8% below entry.
Show max loss: -X%

**💵 POSITION SIZE: X% of portfolio**
Conservative trade = 2-5%
Moderate confidence = 5-8%
High confidence = 8-12%

**📊 RISK/REWARD RATIO: 1:X**
Calculate: (Target - Entry) / (Entry - Stop Loss)
Must be at least 1:2 (risk ₹1 to make ₹2)

**⏰ TIME HORIZON: X months**
Short-term = 1-3 months
Medium-term = 3-6 months
Long-term = 6-12 months

**🔍 WHY THIS TRADE MAKES SENSE:**
Write 4-5 clear sentences:
1. What technical indicators show (momentum, trend, support/resistance)
2. What fundamentals indicate (valuation, growth, profitability)
3. What AI models predict (probability, confidence)
4. Why NOW is the right time to enter
5. What gives you confidence in this trade

**⚠️ KEY RISKS TO MONITOR:**
List 3 SPECIFIC risks (not generic):
1. [Specific risk with numbers/events]
2. [Specific risk with numbers/events]
3. [Specific risk with numbers/events]

**📈 CATALYSTS (What Could Drive Price Up):**
List 2-3 upcoming SPECIFIC events with dates:
1. [Catalyst with date/timeframe]
2. [Catalyst with date/timeframe]
3. [Catalyst with date/timeframe]

**✅ EXIT STRATEGY:**
Be crystal clear:
- "SELL at target price ₹X for +Y% profit"
- "SELL immediately if stop loss ₹Z is hit (-W% loss)"
- "REVIEW after [X months] or if [specific condition]"
- "Trail stop loss to ₹[X] once price reaches ₹[Y]"

Be ULTRA SPECIFIC with every number. Write with absolute confidence. This investor trusts you completely and will execute your recommendation exactly as written. Their money is on the line.
'''

        # Call Groq API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        'role': 'system', 
                        'content': 'You are a legendary stock analyst with 30 years experience and 85% accuracy rate. Your recommendations are followed by thousands of investors who trust you completely. Be specific, confident, and actionable. Every recommendation must be trade-ready with exact numbers.'
                    },
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.2,  # Very low for consistency
                max_tokens=2000   # Increased for full analysis
            )
            
            llm_output = response.choices[0].message.content
            
            # Parse the LLM output
            recommendation = self._parse_recommendation(llm_output, analysis_data)
            
            return recommendation
            
        except Exception as e:
            print(f'Groq API error: {e}')
            return self._fallback_recommendation(analysis_data)
    
    def _parse_recommendation(self, llm_output: str, analysis_data: Dict) -> Dict:
        '''Parse LLM output into structured recommendation'''
        
        # Extract action (BUY/SELL/HOLD)
        action = 'HOLD'
        if 'BUY' in llm_output.upper()[:200]:
            action = 'BUY'
        elif 'SELL' in llm_output.upper()[:200]:
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
            'company_name': analysis_data.get('company_name', 'Unknown'),
            'action': 'HOLD',
            'current_price': analysis_data.get('current_price', 0),
            'llm_reasoning': 'AI analysis temporarily unavailable. Please try again in a few moments.',
            'confidence': 0.5,
            'timestamp': datetime.now().isoformat(),
            'technical_score': 0.5,
            'sentiment_score': 0.5,
            'ml_score': 0.5,
            'fundamental_score': 0.5
        }
