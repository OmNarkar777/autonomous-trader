"""
data/collectors/news_collector.py
===================================
Fetches financial news articles for sentiment analysis.

Source priority (per symbol):
  1. NewsAPI          — 100 req/day free, broad coverage
  2. GNews            — 100 req/day free, backup
  3. RSS feeds        — Unlimited (Reuters, ET Markets, Moneycontrol, etc.)
  4. Google News      — Unlimited via BeautifulSoup scraping (last resort)

Deduplication is applied across all sources.
All returned articles are normalised into NewsArticle dataclass objects.

Usage:
    from data.collectors.news_collector import NewsCollector
    collector = NewsCollector()
    articles = collector.get_stock_news("RELIANCE.NS", "Reliance Industries")
    market_news = collector.get_market_news(hours_back=6)
"""

from __future__ import annotations

import re
import sqlite3
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set
from urllib.parse import quote_plus

import feedparser
import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class NewsArticle:
    title: str
    description: str
    url: str
    published_at: datetime
    source: str         # "newsapi" | "gnews" | "rss_reuters" | "google_news" etc.
    symbol: Optional[str] = None
    content: str = ""
    url_hash: str = field(init=False)

    def __post_init__(self):
        # Normalise title and description
        self.title = self.title.strip() if self.title else ""
        self.description = self.description.strip() if self.description else ""
        # Create a stable hash for deduplication
        self.url_hash = hashlib.md5(self.url.encode()).hexdigest()

    @property
    def age_hours(self) -> float:
        """How old this article is in hours from now."""
        now = datetime.now(timezone.utc)
        pub = self.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return (now - pub).total_seconds() / 3600

    @property
    def recency_weight(self) -> float:
        """
        Weight multiplier based on article age.
        Newer articles are more impactful.
        """
        h = self.age_hours
        if h <= 6:
            return 1.0
        elif h <= 24:
            return 0.7
        elif h <= 72:
            return 0.4
        else:
            return 0.2

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "source": self.source,
            "symbol": self.symbol,
            "content": self.content,
        }


# ═══════════════════════════════════════════════════════════════
# RSS FEED REGISTRY
# ═══════════════════════════════════════════════════════════════

# Free RSS feeds — unlimited calls, no API key required
RSS_FEEDS = {
    # Indian markets
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "moneycontrol_market": "https://www.moneycontrol.com/rss/marketreports.xml",
    "moneycontrol_stocks": "https://www.moneycontrol.com/rss/buzzingstocks.xml",
    "livemint_market": "https://www.livemint.com/rss/markets",
    "bseindia": "https://www.bseindia.com/markets/Equity/EQReports_RSS.aspx",
    # Global / US markets
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "reuters_finance": "https://feeds.reuters.com/news/wealth",
    "cnbc_finance": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "seeking_alpha": "https://seekingalpha.com/feed.xml",
    "ft_markets": "https://www.ft.com/markets?format=rss",
}

# Indian market specific keywords to detect relevance
INDIA_MARKET_KEYWORDS = {
    "nse", "bse", "nifty", "sensex", "sebi", "rbi", "india", "indian",
    "rupee", "inr", "crore", "lakh", "mumbai", "delhi",
}

# US market keywords
US_MARKET_KEYWORDS = {
    "nasdaq", "nyse", "s&p", "dow jones", "fed", "federal reserve",
    "earnings", "ipo", "sec", "dollar", "usd",
}


# ═══════════════════════════════════════════════════════════════
# NEWS COLLECTOR
# ═══════════════════════════════════════════════════════════════

class NewsCollector:
    """
    Collects financial news from multiple free sources with automatic
    fallback, deduplication, and rate limit tracking.
    """

    _NEWSAPI_BASE = "https://newsapi.org/v2/everything"
    _GNEWS_BASE = "https://gnews.io/api/v4/search"
    _GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"

    # Conservative timeout for RSS/scraping requests
    _HTTP_TIMEOUT = 12

    # Maximum articles to return per symbol (avoid overloading sentiment agent)
    _MAX_ARTICLES_PER_SYMBOL = 20

    # Minimum characters in description to be useful for sentiment
    _MIN_DESCRIPTION_LENGTH = 30

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(settings.database_path_resolved)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })
        self._ensure_cache_table()

    # ── Internal: Cache & API tracking ─────────────────────────────────────

    def _ensure_cache_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_cache (
                    cache_key  TEXT PRIMARY KEY,
                    data_json  TEXT NOT NULL,
                    cached_at  TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_usage (
                    api_name TEXT NOT NULL,
                    date     TEXT NOT NULL,
                    calls_made INTEGER DEFAULT 0,
                    daily_limit INTEGER,
                    PRIMARY KEY (api_name, date)
                )
            """)
            conn.commit()

    def _cache_get(self, key: str) -> Optional[List[dict]]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT data_json, expires_at FROM news_cache WHERE cache_key=?",
                    (key,),
                ).fetchone()
            if row:
                expires = datetime.fromisoformat(row[1])
                if datetime.utcnow() < expires:
                    return json.loads(row[0])
        except Exception as e:
            logger.debug(f"News cache read error [{key}]: {e}")
        return None

    def _cache_set(self, key: str, articles: List[dict], ttl_seconds: int = 3600) -> None:
        try:
            now = datetime.utcnow()
            expires = now + timedelta(seconds=ttl_seconds)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO news_cache (cache_key, data_json, cached_at, expires_at)
                    VALUES (?, ?, ?, ?)
                """, (key, json.dumps(articles), now.isoformat(), expires.isoformat()))
                conn.commit()
        except Exception as e:
            logger.debug(f"News cache write error [{key}]: {e}")

    def _track_api_call(self, api_name: str, limit: int) -> None:
        try:
            today = datetime.utcnow().date().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT INTO api_usage (api_name, date, calls_made, daily_limit)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(api_name, date)
                    DO UPDATE SET calls_made = calls_made + 1
                """, (api_name, today, limit))
                conn.commit()
        except Exception:
            pass

    def _get_api_usage(self, api_name: str) -> int:
        try:
            today = datetime.utcnow().date().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT calls_made FROM api_usage WHERE api_name=? AND date=?",
                    (api_name, today),
                ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _can_call_newsapi(self) -> bool:
        return (
            bool(settings.NEWSAPI_KEY)
            and self._get_api_usage("newsapi") < 90  # 10 buffer on 100 limit
        )

    def _can_call_gnews(self) -> bool:
        return (
            bool(settings.GNEWS_API_KEY)
            and self._get_api_usage("gnews") < 90
        )

    # ── Internal: Parsing helpers ──────────────────────────────────────────

    def _parse_datetime(self, dt_str: Optional[str]) -> datetime:
        """Parses various datetime string formats into a UTC-aware datetime."""
        if not dt_str:
            return datetime.now(timezone.utc)
        formats = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(dt_str.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        # Last resort: return now
        logger.debug(f"Could not parse datetime: {dt_str!r}")
        return datetime.now(timezone.utc)

    def _clean_html(self, text: str) -> str:
        """Strips HTML tags and normalises whitespace."""
        if not text:
            return ""
        text = BeautifulSoup(text, "lxml").get_text(separator=" ")
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:500]  # Cap at 500 chars for storage efficiency

    def _deduplicate(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """
        Removes duplicate articles by URL hash and by headline similarity.
        Keeps the most recent version if duplicates exist.
        """
        seen_hashes: Set[str] = set()
        seen_titles: Set[str] = set()
        unique: List[NewsArticle] = []

        for article in sorted(articles, key=lambda a: a.published_at, reverse=True):
            # URL dedup
            if article.url_hash in seen_hashes:
                continue

            # Title similarity dedup (normalise title to lowercase words)
            title_key = " ".join(sorted(re.findall(r'\w+', article.title.lower())))
            if title_key in seen_titles:
                continue

            seen_hashes.add(article.url_hash)
            seen_titles.add(title_key)
            unique.append(article)

        return unique

    def _filter_by_age(self, articles: List[NewsArticle], hours_back: int) -> List[NewsArticle]:
        """Removes articles older than hours_back hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        result = []
        for a in articles:
            pub = a.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                result.append(a)
        return result

    def _is_relevant(self, article: NewsArticle, symbol: str, company_name: str) -> bool:
        """
        Checks if an article is relevant to a given stock symbol.
        Uses case-insensitive keyword matching on title + description.
        """
        haystack = (article.title + " " + article.description).lower()
        # Check company name words (ignore generic words like "the", "and")
        company_words = [
            w for w in company_name.lower().split()
            if len(w) > 2 and w not in {"the", "and", "ltd", "inc", "corp", "limited"}
        ]
        # Check base symbol (without .NS, .BO suffix)
        base_symbol = symbol.replace(".NS", "").replace(".BO", "").lower()

        if base_symbol in haystack:
            return True
        # Check if at least 2 significant company words appear
        matches = sum(1 for w in company_words if w in haystack)
        return matches >= min(2, len(company_words))

    def _articles_from_dicts(self, data: List[dict], symbol: Optional[str]) -> List[NewsArticle]:
        """Re-hydrates NewsArticle objects from cached dicts."""
        articles = []
        for d in data:
            try:
                articles.append(NewsArticle(
                    title=d["title"],
                    description=d["description"],
                    url=d["url"],
                    published_at=datetime.fromisoformat(d["published_at"]),
                    source=d["source"],
                    symbol=d.get("symbol") or symbol,
                    content=d.get("content", ""),
                ))
            except Exception:
                continue
        return articles

    # ── Source: NewsAPI ────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=2, max=8),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=False,
    )
    def _fetch_newsapi(
        self,
        query: str,
        hours_back: int,
        symbol: Optional[str] = None,
    ) -> List[NewsArticle]:
        """Fetches articles from NewsAPI /everything endpoint."""
        if not self._can_call_newsapi():
            logger.debug("NewsAPI: limit reached or key not set — skipping")
            return []

        from_dt = (datetime.utcnow() - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%S")
        params = {
            "q": query,
            "from": from_dt,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 20,
            "apiKey": settings.NEWSAPI_KEY,
        }
        resp = self._session.get(self._NEWSAPI_BASE, params=params, timeout=self._HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        self._track_api_call("newsapi", limit=100)

        articles = []
        for item in data.get("articles", []):
            title = item.get("title") or ""
            description = item.get("description") or item.get("content") or ""
            url = item.get("url") or ""
            if not title or not url or title == "[Removed]":
                continue
            if len(description) < self._MIN_DESCRIPTION_LENGTH:
                description = title  # Use title as fallback description

            articles.append(NewsArticle(
                title=self._clean_html(title),
                description=self._clean_html(description),
                url=url,
                published_at=self._parse_datetime(item.get("publishedAt")),
                source="newsapi",
                symbol=symbol,
                content=self._clean_html(item.get("content") or ""),
            ))
        logger.debug(f"NewsAPI: {len(articles)} articles for query '{query[:50]}'")
        return articles

    # ── Source: GNews ──────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=2, max=8),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=False,
    )
    def _fetch_gnews(
        self,
        query: str,
        hours_back: int,
        symbol: Optional[str] = None,
    ) -> List[NewsArticle]:
        """Fetches articles from GNews API."""
        if not self._can_call_gnews():
            logger.debug("GNews: limit reached or key not set — skipping")
            return []

        params = {
            "q": query,
            "lang": "en",
            "max": 10,
            "apikey": settings.GNEWS_API_KEY,
        }
        resp = self._session.get(self._GNEWS_BASE, params=params, timeout=self._HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        self._track_api_call("gnews", limit=100)

        articles = []
        for item in data.get("articles", []):
            title = item.get("title") or ""
            description = item.get("description") or ""
            url = item.get("url") or ""
            if not title or not url:
                continue
            if len(description) < self._MIN_DESCRIPTION_LENGTH:
                description = title

            articles.append(NewsArticle(
                title=self._clean_html(title),
                description=self._clean_html(description),
                url=url,
                published_at=self._parse_datetime(
                    item.get("publishedAt") or item.get("date")
                ),
                source="gnews",
                symbol=symbol,
                content=self._clean_html(item.get("content") or ""),
            ))
        logger.debug(f"GNews: {len(articles)} articles for query '{query[:50]}'")
        return articles

    # ── Source: RSS Feeds ──────────────────────────────────────────────────

    def _fetch_rss_feed(
        self,
        feed_name: str,
        feed_url: str,
        keyword_filter: Optional[str] = None,
        hours_back: int = 48,
        symbol: Optional[str] = None,
    ) -> List[NewsArticle]:
        """
        Fetches and parses a single RSS/Atom feed.
        Completely free, no rate limits.
        """
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                logger.debug(f"RSS [{feed_name}]: Parse warning (bozo) but continuing")

            articles = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

            for entry in feed.entries:
                title = entry.get("title", "")
                description = (
                    entry.get("summary", "")
                    or entry.get("description", "")
                    or entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""
                )
                url = entry.get("link", "")
                if not title or not url:
                    continue

                # Parse published date
                published_str = (
                    entry.get("published")
                    or entry.get("updated")
                    or entry.get("dc_date")
                    or ""
                )
                published_at = self._parse_datetime(published_str)

                # Age filter
                pub_aware = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
                if pub_aware < cutoff:
                    continue

                # Keyword filter (for stock-specific searches)
                if keyword_filter:
                    combined = (title + " " + description).lower()
                    if keyword_filter.lower() not in combined:
                        continue

                articles.append(NewsArticle(
                    title=self._clean_html(title),
                    description=self._clean_html(description),
                    url=url,
                    published_at=published_at,
                    source=f"rss_{feed_name}",
                    symbol=symbol,
                ))

            logger.debug(f"RSS [{feed_name}]: {len(articles)} articles")
            return articles

        except Exception as e:
            logger.debug(f"RSS [{feed_name}] failed: {e}")
            return []

    def _fetch_all_rss(
        self,
        keyword_filter: Optional[str] = None,
        hours_back: int = 48,
        symbol: Optional[str] = None,
        market: str = "india",
    ) -> List[NewsArticle]:
        """Fetches from all RSS feeds appropriate to the target market."""
        all_articles: List[NewsArticle] = []

        # Select feeds by market
        if market == "india":
            feed_names = ["et_markets", "et_stocks", "moneycontrol_market",
                          "moneycontrol_stocks", "livemint_market"]
        elif market == "us":
            feed_names = ["reuters_business", "reuters_finance", "cnbc_finance",
                          "marketwatch"]
        else:  # both
            feed_names = list(RSS_FEEDS.keys())

        for name in feed_names:
            url = RSS_FEEDS.get(name)
            if url:
                articles = self._fetch_rss_feed(
                    name, url,
                    keyword_filter=keyword_filter,
                    hours_back=hours_back,
                    symbol=symbol,
                )
                all_articles.extend(articles)
                # Small delay between RSS fetches
                time.sleep(0.2)

        return all_articles

    # ── Source: Google News (scraping fallback) ────────────────────────────

    def _fetch_google_news(
        self,
        query: str,
        hours_back: int = 48,
        symbol: Optional[str] = None,
    ) -> List[NewsArticle]:
        """
        Scrapes Google News RSS endpoint (free, no API key needed).
        Used as last-resort fallback when all other sources are exhausted.
        Google News RSS is a public endpoint that returns valid Atom XML.
        """
        try:
            encoded_query = quote_plus(query)
            url = f"{self._GOOGLE_NEWS_BASE}?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"

            feed = feedparser.parse(url)
            articles = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

            for entry in feed.entries[:15]:  # Cap at 15 from Google
                title = entry.get("title", "")
                url_entry = entry.get("link", "")
                if not title or not url_entry:
                    continue

                published_str = entry.get("published", "")
                published_at = self._parse_datetime(published_str)

                pub_aware = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
                if pub_aware < cutoff:
                    continue

                description = entry.get("summary", title)

                articles.append(NewsArticle(
                    title=self._clean_html(title),
                    description=self._clean_html(description),
                    url=url_entry,
                    published_at=published_at,
                    source="google_news",
                    symbol=symbol,
                ))

            logger.debug(f"Google News: {len(articles)} articles for '{query[:50]}'")
            return articles

        except Exception as e:
            logger.debug(f"Google News scraping failed: {e}")
            return []

    # ── Public: get_stock_news ─────────────────────────────────────────────

    def get_stock_news(
        self,
        symbol: str,
        company_name: str,
        hours_back: int = 24,
    ) -> List[NewsArticle]:
        """
        Fetches news articles relevant to a specific stock.

        Source waterfall:
          1. NewsAPI (if daily limit not hit and key is set)
          2. GNews (if daily limit not hit and key is set)
          3. RSS feeds from Indian/US financial news outlets
          4. Google News RSS (free scraping, last resort)

        Articles are deduplicated, filtered to the requested time window,
        and capped at MAX_ARTICLES_PER_SYMBOL.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS")
            company_name: Human-readable company name for search query
            hours_back: How far back to look for news (default: 24 hours)

        Returns:
            List of NewsArticle objects, sorted by recency (newest first).
            If fewer than 3 articles found, a WARNING is logged but
            an empty/small list is returned (not an exception) — the
            sentiment agent handles low-news situations gracefully.
        """
        cache_key = f"stock_news_{symbol}_{hours_back}"
        cached = self._cache_get(cache_key)
        if cached:
            articles = self._articles_from_dicts(cached, symbol)
            logger.debug(f"[{symbol}] News from cache: {len(articles)} articles")
            return articles

        all_articles: List[NewsArticle] = []
        # Build a search query that targets the specific stock
        base_symbol = symbol.replace(".NS", "").replace(".BO", "")
        query = f'"{company_name}" OR "{base_symbol}" stock'

        # Determine target market for RSS selection
        market = "india" if symbol.endswith((".NS", ".BO")) else "us"

        # ── Source 1: NewsAPI ──────────────────────────────────────────────
        try:
            newsapi_articles = self._fetch_newsapi(query, hours_back, symbol=symbol)
            all_articles.extend(newsapi_articles)
        except Exception as e:
            logger.warning(f"[{symbol}] NewsAPI fetch failed: {e}")

        # ── Source 2: GNews ────────────────────────────────────────────────
        if len(all_articles) < 5:
            try:
                gnews_articles = self._fetch_gnews(query, hours_back, symbol=symbol)
                all_articles.extend(gnews_articles)
            except Exception as e:
                logger.warning(f"[{symbol}] GNews fetch failed: {e}")

        # ── Source 3: RSS feeds (always tried — free) ─────────────────────
        # Use shorter keyword for RSS filtering (more lenient than quoted query)
        rss_keyword = company_name.split()[0]  # First word of company name
        rss_articles = self._fetch_all_rss(
            keyword_filter=rss_keyword,
            hours_back=hours_back,
            symbol=symbol,
            market=market,
        )
        all_articles.extend(rss_articles)

        # ── Source 4: Google News (if still not enough) ────────────────────
        if len(all_articles) < 3:
            logger.info(f"[{symbol}] Insufficient articles from primary sources "
                        f"({len(all_articles)}) — falling back to Google News")
            google_articles = self._fetch_google_news(
                f"{company_name} {base_symbol} stock",
                hours_back=hours_back,
                symbol=symbol,
            )
            all_articles.extend(google_articles)

        # ── Post-processing ────────────────────────────────────────────────
        # 1. Age filter
        all_articles = self._filter_by_age(all_articles, hours_back)
        # 2. Relevance filter — keep only articles mentioning the stock
        all_articles = [
            a for a in all_articles
            if self._is_relevant(a, symbol, company_name)
        ]
        # 3. Deduplication
        all_articles = self._deduplicate(all_articles)
        # 4. Sort newest first
        all_articles.sort(key=lambda a: a.published_at, reverse=True)
        # 5. Cap
        all_articles = all_articles[:self._MAX_ARTICLES_PER_SYMBOL]

        if len(all_articles) == 0:
            logger.warning(f"[{symbol}] No news articles found in last {hours_back}h. "
                           f"Sentiment will be marked as NEUTRAL/LOW_DATA.")
        elif len(all_articles) < 3:
            logger.warning(f"[{symbol}] Only {len(all_articles)} articles found "
                           f"(< 3 recommended for reliable sentiment).")
        else:
            logger.info(f"[{symbol}] Found {len(all_articles)} news articles "
                        f"(last {hours_back}h)")

        # Cache for 1 hour
        self._cache_set(cache_key, [a.to_dict() for a in all_articles], ttl_seconds=3600)
        return all_articles

    # ── Public: get_market_news ────────────────────────────────────────────

    def get_market_news(self, hours_back: int = 6) -> List[NewsArticle]:
        """
        Fetches broad market news (not stock-specific).
        Used by MacroAgent to assess overall market sentiment.

        Args:
            hours_back: How far back to look for news

        Returns:
            List of NewsArticle objects, deduped and sorted newest-first.
        """
        cache_key = f"market_news_{hours_back}"
        cached = self._cache_get(cache_key)
        if cached:
            articles = self._articles_from_dicts(cached, symbol=None)
            logger.debug(f"Market news from cache: {len(articles)} articles")
            return articles

        all_articles: List[NewsArticle] = []
        market_query = "stock market OR sensex OR nifty OR indian economy"

        # NewsAPI for market news
        try:
            newsapi_articles = self._fetch_newsapi(market_query, hours_back, symbol=None)
            all_articles.extend(newsapi_articles)
        except Exception as e:
            logger.warning(f"Market news NewsAPI failed: {e}")

        # GNews fallback
        if len(all_articles) < 5:
            try:
                gnews_articles = self._fetch_gnews(market_query, hours_back, symbol=None)
                all_articles.extend(gnews_articles)
            except Exception as e:
                logger.warning(f"Market news GNews failed: {e}")

        # RSS feeds (no keyword filter — get all market news)
        market = "india" if settings.TARGET_MARKET == "india" else "us"
        rss_articles = self._fetch_all_rss(
            keyword_filter=None,
            hours_back=hours_back,
            symbol=None,
            market=market,
        )
        all_articles.extend(rss_articles)

        # Google News fallback
        if len(all_articles) < 5:
            google_articles = self._fetch_google_news(
                "india stock market nifty sensex",
                hours_back=hours_back,
            )
            all_articles.extend(google_articles)

        # Post-process
        all_articles = self._filter_by_age(all_articles, hours_back)
        all_articles = self._deduplicate(all_articles)
        all_articles.sort(key=lambda a: a.published_at, reverse=True)
        all_articles = all_articles[:30]  # Cap market news at 30 articles

        logger.info(f"Market news: {len(all_articles)} articles (last {hours_back}h)")

        # Cache for 30 minutes (market news refreshes more often)
        self._cache_set(cache_key, [a.to_dict() for a in all_articles], ttl_seconds=1800)
        return all_articles

    # ── Public: get_news_for_watchlist ─────────────────────────────────────

    def get_news_for_watchlist(
        self,
        symbols_and_names: Dict[str, str],
        hours_back: int = 24,
    ) -> Dict[str, List[NewsArticle]]:
        """
        Fetches news for all symbols in the watchlist efficiently.
        Spaces out API calls to avoid rate limit hammering.

        Args:
            symbols_and_names: Dict mapping symbol → company name
            hours_back: How far back to look

        Returns:
            Dict mapping symbol → list of NewsArticle
        """
        results: Dict[str, List[NewsArticle]] = {}
        total = len(symbols_and_names)

        for i, (symbol, company_name) in enumerate(symbols_and_names.items(), 1):
            logger.info(f"Fetching news [{i}/{total}]: {symbol}")
            try:
                results[symbol] = self.get_stock_news(
                    symbol, company_name, hours_back=hours_back
                )
            except Exception as e:
                logger.error(f"[{symbol}] News fetch failed: {e}")
                results[symbol] = []

            # Polite delay to avoid hammering — longer delay if we used paid APIs
            if i < total:
                time.sleep(1.0)

        return results
