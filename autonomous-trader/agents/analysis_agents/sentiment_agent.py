"""
agents/analysis_agents/sentiment_agent.py
===========================================
Sentiment Analysis Agent - analyzes news sentiment using Groq LLM.

Sentiment analysis methodology:
  1. Primary: Groq Llama 3.3 70B for nuanced sentiment analysis
  2. Fallback: FinBERT (transformer model) if Groq unavailable
  3. Aggregation: Weighted by article recency (newer = more weight)

Scoring (0-10 scale):
  - 8-10: Very positive sentiment (bullish news, upgrades, strong results)
  - 6-8: Positive sentiment
  - 4-6: Neutral/mixed sentiment
  - 2-4: Negative sentiment
  - 0-2: Very negative sentiment (bearish news, downgrades, scandals)

Usage:
    from agents.analysis_agents.sentiment_agent import SentimentAgent
    agent = SentimentAgent()
    result = agent.run(symbol="RELIANCE.NS", articles=[...])
    
    if result.success:
        score = result.data.sentiment_score
        print(f"Sentiment: {score}/10")
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json

from agents.base_agent import BaseAgent, AgentResult
from data.collectors.news_collector import NewsArticle
from data.storage.cache import cache
from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class ArticleSentiment:
    """Sentiment analysis for a single article."""
    title: str
    sentiment: str  # "POSITIVE" | "NEGATIVE" | "NEUTRAL"
    score: float    # 0-10
    confidence: float  # 0-1
    reasoning: Optional[str] = None


@dataclass
class SentimentAgentOutput:
    """Structured output from SentimentAgent."""
    symbol: str
    sentiment_score: float  # 0-10 (aggregated from all articles)
    sentiment_label: str    # "VERY_POSITIVE" | "POSITIVE" | "NEUTRAL" | "NEGATIVE" | "VERY_NEGATIVE"
    confidence: float       # 0-1 (average confidence across articles)
    
    # Article-level breakdown
    article_sentiments: List[ArticleSentiment]
    articles_analyzed: int
    positive_count: int
    negative_count: int
    neutral_count: int
    
    # Meta
    analysis_method: str  # "groq" | "finbert" | "fallback"


# ═══════════════════════════════════════════════════════════════
# SENTIMENT AGENT
# ═══════════════════════════════════════════════════════════════

class SentimentAgent(BaseAgent):
    """
    Agent that analyzes news sentiment using LLM-based analysis.
    
    Uses Groq's Llama 3.3 70B for sophisticated sentiment analysis
    with fallback to FinBERT if Groq is unavailable.
    """
    
    def __init__(self):
        super().__init__(agent_name="SentimentAgent")
        self._groq_available = bool(settings.GROQ_API_KEY)
        self._finbert_model = None  # Lazy load
    
    def execute(
        self,
        symbol: str,
        articles: List[NewsArticle],
        **kwargs
    ) -> AgentResult:
        """
        Analyzes sentiment from news articles.
        
        Args:
            symbol: Stock symbol
            articles: List of NewsArticle objects
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with SentimentAgentOutput in data field
        """
        self.logger.info(f"[{symbol}] Analyzing sentiment from {len(articles)} articles")
        
        # ── Handle no articles case ───────────────────────────────────────
        if len(articles) == 0:
            self.logger.warning(f"[{symbol}] No articles to analyze - defaulting to NEUTRAL")
            return self.success_result(
                data=SentimentAgentOutput(
                    symbol=symbol,
                    sentiment_score=5.0,
                    sentiment_label="NEUTRAL",
                    confidence=0.0,
                    article_sentiments=[],
                    articles_analyzed=0,
                    positive_count=0,
                    negative_count=0,
                    neutral_count=0,
                    analysis_method="none",
                ),
                metadata={
                    "warning": "No articles available",
                }
            )
        
        # ── Check cache ────────────────────────────────────────────────────
        cache_key = f"sentiment_{symbol}_{len(articles)}"
        cached_output = cache.get(cache_key)
        if cached_output:
            self.logger.debug(f"[{symbol}] Using cached sentiment analysis")
            # Re-hydrate ArticleSentiment objects
            article_sentiments = [
                ArticleSentiment(**a) for a in cached_output["article_sentiments"]
            ]
            cached_output["article_sentiments"] = article_sentiments
            return self.success_result(
                data=SentimentAgentOutput(**cached_output),
                metadata={"source": "cache"}
            )
        
        # ── Analyze articles ───────────────────────────────────────────────
        try:
            if self._groq_available:
                article_sentiments, method = self._analyze_with_groq(articles)
            else:
                self.logger.warning(f"[{symbol}] Groq not available - using FinBERT fallback")
                article_sentiments, method = self._analyze_with_finbert(articles)
            
            self.logger.debug(
                f"[{symbol}] Analyzed {len(article_sentiments)} articles using {method}"
            )
        
        except Exception as e:
            self.logger.error(f"[{symbol}] Sentiment analysis failed: {e}")
            return self.failure_result(
                error=f"Sentiment analysis failed: {e}",
                metadata={"symbol": symbol, "article_count": len(articles)}
            )
        
        # ── Aggregate sentiment ────────────────────────────────────────────
        aggregated_score, label = self._aggregate_sentiment(article_sentiments, articles)
        
        # ── Calculate counts ───────────────────────────────────────────────
        positive_count = sum(1 for a in article_sentiments if a.sentiment == "POSITIVE")
        negative_count = sum(1 for a in article_sentiments if a.sentiment == "NEGATIVE")
        neutral_count = sum(1 for a in article_sentiments if a.sentiment == "NEUTRAL")
        
        avg_confidence = (
            sum(a.confidence for a in article_sentiments) / len(article_sentiments)
            if article_sentiments else 0.0
        )
        
        # ── Build output ───────────────────────────────────────────────────
        output = SentimentAgentOutput(
            symbol=symbol,
            sentiment_score=round(aggregated_score, 2),
            sentiment_label=label,
            confidence=round(avg_confidence, 2),
            article_sentiments=article_sentiments,
            articles_analyzed=len(article_sentiments),
            positive_count=positive_count,
            negative_count=negative_count,
            neutral_count=neutral_count,
            analysis_method=method,
        )
        
        self.logger.info(
            f"[{symbol}] Sentiment score: {aggregated_score:.1f}/10 ({label}) | "
            f"Articles: +{positive_count} ={neutral_count} -{negative_count} | "
            f"Method: {method}"
        )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache_data = output.__dict__.copy()
        cache_data["article_sentiments"] = [a.__dict__ for a in article_sentiments]
        
        cache.set(cache_key, cache_data, ttl=1800)  # 30 minutes
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "score": aggregated_score,
                "label": label,
                "method": method,
                "articles": len(articles),
            }
        )
    
    # ── Groq Analysis ──────────────────────────────────────────────────────
    
    def _analyze_with_groq(
        self,
        articles: List[NewsArticle],
    ) -> tuple[List[ArticleSentiment], str]:
        """
        Analyzes sentiment using Groq's Llama 3.3 70B.
        
        Returns:
            Tuple of (article_sentiments, "groq")
        """
        from groq import Groq
        
        client = Groq(api_key=settings.GROQ_API_KEY)
        
        article_sentiments = []
        
        # Limit to top 10 most recent articles (API cost optimization)
        articles_to_analyze = articles[:10]
        
        for article in articles_to_analyze:
            try:
                sentiment = self._analyze_article_with_groq(client, article)
                article_sentiments.append(sentiment)
            except Exception as e:
                self.logger.warning(
                    f"Groq analysis failed for article '{article.title[:50]}': {e}"
                )
                # Use fallback for this article
                sentiment = self._simple_sentiment_fallback(article)
                article_sentiments.append(sentiment)
        
        return article_sentiments, "groq"
    
    def _analyze_article_with_groq(
        self,
        client,
        article: NewsArticle,
    ) -> ArticleSentiment:
        """Analyzes a single article using Groq."""
        
        # Combine title and description for analysis
        text = f"{article.title}. {article.description or ''}"
        
        prompt = f"""Analyze the sentiment of this stock market news article.

Article: "{text}"

Respond ONLY with a JSON object in this exact format (no markdown, no explanation):
{{
    "sentiment": "POSITIVE" or "NEGATIVE" or "NEUTRAL",
    "score": <number 0-10>,
    "confidence": <number 0.0-1.0>,
    "reasoning": "<brief explanation>"
}}

Guidelines:
- POSITIVE: bullish news, upgrades, strong earnings, partnerships, growth
- NEGATIVE: bearish news, downgrades, weak earnings, scandals, regulatory issues
- NEUTRAL: factual reporting without clear positive/negative bias
- Score: 0=very negative, 5=neutral, 10=very positive
- Confidence: how certain you are (0.0=uncertain, 1.0=very certain)"""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a financial sentiment analysis expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=200,
        )
        
        # Parse response
        result_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()
        
        result = json.loads(result_text)
        
        return ArticleSentiment(
            title=article.title,
            sentiment=result["sentiment"],
            score=float(result["score"]),
            confidence=float(result["confidence"]),
            reasoning=result.get("reasoning"),
        )
    
    # ── FinBERT Analysis ───────────────────────────────────────────────────
    
    def _analyze_with_finbert(
        self,
        articles: List[NewsArticle],
    ) -> tuple[List[ArticleSentiment], str]:
        """
        Analyzes sentiment using FinBERT transformer model.
        
        Returns:
            Tuple of (article_sentiments, "finbert")
        """
        # Lazy load FinBERT
        if self._finbert_model is None:
            self._load_finbert()
        
        article_sentiments = []
        
        for article in articles[:20]:  # Limit to 20 for performance
            try:
                sentiment = self._analyze_article_with_finbert(article)
                article_sentiments.append(sentiment)
            except Exception as e:
                self.logger.warning(
                    f"FinBERT analysis failed for article '{article.title[:50]}': {e}"
                )
                # Use simple fallback
                sentiment = self._simple_sentiment_fallback(article)
                article_sentiments.append(sentiment)
        
        return article_sentiments, "finbert"
    
    def _load_finbert(self) -> None:
        """Loads FinBERT model (lazy initialization)."""
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch
            
            self.logger.info("Loading FinBERT model...")
            
            model_name = "ProsusAI/finbert"
            self._finbert_tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._finbert_model = AutoModelForSequenceClassification.from_pretrained(model_name)
            
            self.logger.info("FinBERT model loaded successfully")
        
        except ImportError:
            self.logger.error(
                "transformers library not installed. "
                "Install with: pip install transformers torch"
            )
            raise
    
    def _analyze_article_with_finbert(
        self,
        article: NewsArticle,
    ) -> ArticleSentiment:
        """Analyzes a single article using FinBERT."""
        import torch
        
        text = f"{article.title}. {article.description or ''}"
        
        # Tokenize
        inputs = self._finbert_tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        
        # Predict
        with torch.no_grad():
            outputs = self._finbert_model(**inputs)
            predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)
        
        # FinBERT labels: 0=positive, 1=negative, 2=neutral
        probs = predictions[0].tolist()
        pos_prob = probs[0]
        neg_prob = probs[1]
        neu_prob = probs[2]
        
        # Determine sentiment
        if pos_prob > neg_prob and pos_prob > neu_prob:
            sentiment = "POSITIVE"
            score = 5.0 + (pos_prob * 5)  # 5-10 range
            confidence = pos_prob
        elif neg_prob > pos_prob and neg_prob > neu_prob:
            sentiment = "NEGATIVE"
            score = 5.0 - (neg_prob * 5)  # 0-5 range
            confidence = neg_prob
        else:
            sentiment = "NEUTRAL"
            score = 5.0
            confidence = neu_prob
        
        return ArticleSentiment(
            title=article.title,
            sentiment=sentiment,
            score=score,
            confidence=confidence,
            reasoning=f"FinBERT: pos={pos_prob:.2f}, neg={neg_prob:.2f}, neu={neu_prob:.2f}",
        )
    
    # ── Fallback ───────────────────────────────────────────────────────────
    
    def _simple_sentiment_fallback(
        self,
        article: NewsArticle,
    ) -> ArticleSentiment:
        """
        Simple keyword-based sentiment as last resort.
        Used when both Groq and FinBERT fail.
        """
        text = f"{article.title} {article.description or ''}".lower()
        
        # Positive keywords
        positive_words = [
            "surge", "rally", "bullish", "upgrade", "beat", "growth",
            "profit", "gain", "rise", "jump", "soar", "strong", "positive",
            "buy", "outperform", "expansion", "record", "high"
        ]
        
        # Negative keywords
        negative_words = [
            "fall", "drop", "crash", "bearish", "downgrade", "miss", "loss",
            "decline", "plunge", "weak", "negative", "sell", "underperform",
            "cut", "reduce", "concern", "risk", "low"
        ]
        
        pos_count = sum(1 for word in positive_words if word in text)
        neg_count = sum(1 for word in negative_words if word in text)
        
        if pos_count > neg_count:
            sentiment = "POSITIVE"
            score = 5.5 + min(pos_count * 0.5, 3.5)
            confidence = min(pos_count / 5, 0.6)
        elif neg_count > pos_count:
            sentiment = "NEGATIVE"
            score = 4.5 - min(neg_count * 0.5, 3.5)
            confidence = min(neg_count / 5, 0.6)
        else:
            sentiment = "NEUTRAL"
            score = 5.0
            confidence = 0.3
        
        return ArticleSentiment(
            title=article.title,
            sentiment=sentiment,
            score=score,
            confidence=confidence,
            reasoning="Keyword-based fallback",
        )
    
    # ── Aggregation ────────────────────────────────────────────────────────
    
    def _aggregate_sentiment(
        self,
        article_sentiments: List[ArticleSentiment],
        articles: List[NewsArticle],
    ) -> tuple[float, str]:
        """
        Aggregates individual article sentiments into overall score.
        
        Uses recency weighting: newer articles get more weight.
        
        Returns:
            Tuple of (aggregated_score, label)
        """
        if not article_sentiments:
            return 5.0, "NEUTRAL"
        
        # Create mapping of title to article for recency weights
        title_to_article = {a.title: a for a in articles}
        
        weighted_scores = []
        
        for sentiment in article_sentiments:
            # Get recency weight from original article
            article = title_to_article.get(sentiment.title)
            weight = article.recency_weight if article else 0.5
            
            # Also weight by confidence
            weight *= sentiment.confidence
            
            weighted_scores.append(sentiment.score * weight)
        
        # Calculate weighted average
        total_weight = sum(
            (title_to_article.get(s.title).recency_weight if title_to_article.get(s.title) else 0.5)
            * s.confidence
            for s in article_sentiments
        )
        
        if total_weight > 0:
            aggregated = sum(weighted_scores) / total_weight
        else:
            aggregated = sum(s.score for s in article_sentiments) / len(article_sentiments)
        
        # Determine label
        if aggregated >= 7.5:
            label = "VERY_POSITIVE"
        elif aggregated >= 5.5:
            label = "POSITIVE"
        elif aggregated >= 4.5:
            label = "NEUTRAL"
        elif aggregated >= 2.5:
            label = "NEGATIVE"
        else:
            label = "VERY_NEGATIVE"
        
        return aggregated, label
