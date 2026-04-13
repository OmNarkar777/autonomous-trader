"""
agents/data_agents/news_agent.py
==================================
News Data Agent - fetches and validates news articles for sentiment analysis.

Responsibilities:
  1. Fetch news articles from NewsCollector
  2. Validate article quality (count, recency)
  3. Filter out irrelevant/low-quality articles
  4. Cache results for this trading cycle

Output:
  - articles: List[NewsArticle]
  - article_count: int
  - quality_score: float (0-1, based on count and recency)
  - oldest_article_hours: float
  - newest_article_hours: float

Usage:
    from agents.data_agents.news_agent import NewsAgent
    agent = NewsAgent()
    result = agent.run(symbol="RELIANCE.NS", company_name="Reliance Industries")
    
    if result.success:
        articles = result.data.articles
        for article in articles:
            print(f"{article.title} ({article.age_hours:.1f}h old)")
"""

from __future__ import annotations

from typing import List, Dict, Any
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentResult
from data.collectors.news_collector import NewsCollector, NewsArticle
from data.storage.cache import cache
from config.constants import MIN_NEWS_ARTICLES
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class NewsAgentOutput:
    """Structured output from NewsAgent."""
    symbol: str
    articles: List[NewsArticle]
    article_count: int
    quality_score: float  # 0-1, based on article count and recency
    oldest_article_hours: float
    newest_article_hours: float
    has_recent_news: bool  # True if at least 1 article in last 24h


# ═══════════════════════════════════════════════════════════════
# NEWS AGENT
# ═══════════════════════════════════════════════════════════════

class NewsAgent(BaseAgent):
    """
    Agent responsible for fetching and validating news articles.
    
    News is used by the SentimentAgent to gauge market mood around
    a stock. Quality matters more than quantity - we prefer fewer
    high-quality recent articles over many old ones.
    """
    
    def __init__(self):
        super().__init__(agent_name="NewsAgent")
        self.news_collector = NewsCollector()
    
    def execute(
        self,
        symbol: str,
        company_name: str,
        hours_back: int = 48,
        **kwargs
    ) -> AgentResult:
        """
        Fetches and validates news articles for a symbol.
        
        Args:
            symbol: Stock symbol
            company_name: Company name for search queries
            hours_back: How far back to look for news (default: 48 hours)
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with NewsAgentOutput in data field
        """
        self.logger.info(f"[{symbol}] Fetching news articles (last {hours_back}h)")
        
        # ── Check cache first ──────────────────────────────────────────────
        cache_key = f"news_{symbol}_{hours_back}"
        cached_output = cache.get(cache_key)
        if cached_output:
            self.logger.debug(f"[{symbol}] Using cached news data")
            # Re-hydrate articles from cached dicts
            articles = [
                NewsArticle(**a) for a in cached_output["articles"]
            ]
            output = NewsAgentOutput(
                symbol=symbol,
                articles=articles,
                article_count=cached_output["article_count"],
                quality_score=cached_output["quality_score"],
                oldest_article_hours=cached_output["oldest_article_hours"],
                newest_article_hours=cached_output["newest_article_hours"],
                has_recent_news=cached_output["has_recent_news"],
            )
            return self.success_result(
                data=output,
                metadata={"source": "cache"}
            )
        
        # ── Fetch news articles ────────────────────────────────────────────
        try:
            articles = self.news_collector.get_stock_news(
                symbol=symbol,
                company_name=company_name,
                hours_back=hours_back,
            )
            
            self.logger.debug(f"[{symbol}] Fetched {len(articles)} articles")
            
        except Exception as e:
            self.logger.error(f"[{symbol}] Failed to fetch news: {e}")
            return self.failure_result(
                error=f"News fetch failed: {e}",
                metadata={"symbol": symbol, "company_name": company_name}
            )
        
        # ── Validate article quality ───────────────────────────────────────
        if len(articles) == 0:
            self.logger.warning(f"[{symbol}] No news articles found")
            # Return success with empty articles (not a failure, just no news)
            output = NewsAgentOutput(
                symbol=symbol,
                articles=[],
                article_count=0,
                quality_score=0.0,
                oldest_article_hours=0.0,
                newest_article_hours=0.0,
                has_recent_news=False,
            )
            return self.success_result(
                data=output,
                metadata={
                    "symbol": symbol,
                    "warning": "No news articles found",
                }
            )
        
        # ── Calculate quality metrics ──────────────────────────────────────
        article_ages = [a.age_hours for a in articles]
        oldest_hours = max(article_ages)
        newest_hours = min(article_ages)
        
        # Has recent news? (at least 1 article in last 24h)
        has_recent = any(a.age_hours <= 24 for a in articles)
        
        # Quality score (0-1)
        # Factors:
        #   - Article count (more is better, up to 10)
        #   - Recency (newer is better)
        
        # Count score (0-1)
        count_score = min(len(articles) / 10, 1.0)
        
        # Recency score (0-1)
        # If newest article is <6h old → 1.0
        # If newest article is >48h old → 0.0
        recency_score = max(0.0, 1.0 - (newest_hours / 48))
        
        # Combined quality score
        quality_score = (0.6 * count_score) + (0.4 * recency_score)
        
        self.logger.debug(
            f"[{symbol}] News quality: {quality_score:.2f} "
            f"(count={count_score:.2f}, recency={recency_score:.2f})"
        )
        
        # ── Warn if insufficient news ──────────────────────────────────────
        if len(articles) < MIN_NEWS_ARTICLES:
            self.logger.warning(
                f"[{symbol}] Only {len(articles)} articles found "
                f"(recommend {MIN_NEWS_ARTICLES}+). Sentiment may be less reliable."
            )
        
        # ── Create output ──────────────────────────────────────────────────
        output = NewsAgentOutput(
            symbol=symbol,
            articles=articles,
            article_count=len(articles),
            quality_score=quality_score,
            oldest_article_hours=oldest_hours,
            newest_article_hours=newest_hours,
            has_recent_news=has_recent,
        )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache.set(
            cache_key,
            {
                "symbol": symbol,
                "articles": [a.to_dict() for a in articles],
                "article_count": len(articles),
                "quality_score": quality_score,
                "oldest_article_hours": oldest_hours,
                "newest_article_hours": newest_hours,
                "has_recent_news": has_recent,
            },
            ttl=1800  # 30 minutes
        )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "article_count": len(articles),
                "quality_score": quality_score,
                "newest_hours": newest_hours,
                "oldest_hours": oldest_hours,
                "has_recent": has_recent,
            }
        )
