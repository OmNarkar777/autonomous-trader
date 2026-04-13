"""
tests/test_data_collectors.py
==============================
Tests for all data collectors.
"""

import pytest
from datetime import datetime, timedelta
from data.collectors.price_collector import PriceCollector
from data.collectors.news_collector import NewsCollector
from data.collectors.macro_collector import MacroCollector
from data.collectors.earnings_calendar import EarningsCalendarCollector


class TestPriceCollector:
    """Tests for PriceCollector."""
    
    @pytest.fixture
    def collector(self):
        return PriceCollector()
    
    def test_get_current_price(self, collector):
        """Test fetching current price."""
        # Use a well-known symbol that should always work
        result = collector.get_current_price("AAPL")
        
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.current_price > 0
        assert result.volume >= 0
        assert isinstance(result.timestamp, datetime)
    
    def test_get_historical_data(self, collector):
        """Test fetching historical data."""
        df = collector.get_historical_data("AAPL", period="1mo", interval="1d")
        
        assert df is not None
        assert len(df) > 0
        assert "Close" in df.columns
        assert "Volume" in df.columns
        assert df["Close"].iloc[-1] > 0
    
    def test_invalid_symbol(self, collector):
        """Test handling of invalid symbol."""
        with pytest.raises(Exception):
            collector.get_current_price("INVALID_SYMBOL_12345")


class TestNewsCollector:
    """Tests for NewsCollector."""
    
    @pytest.fixture
    def collector(self):
        return NewsCollector()
    
    def test_get_stock_news(self, collector):
        """Test fetching stock news."""
        articles = collector.get_stock_news(
            symbol="AAPL",
            company_name="Apple Inc",
            hours_back=48
        )
        
        # Should return a list (might be empty if no news)
        assert isinstance(articles, list)
        
        # If articles exist, validate structure
        if len(articles) > 0:
            article = articles[0]
            assert hasattr(article, 'title')
            assert hasattr(article, 'source')
            assert hasattr(article, 'published_at')
            assert hasattr(article, 'age_hours')
    
    def test_article_age_calculation(self, collector):
        """Test that article age is calculated correctly."""
        articles = collector.get_stock_news(
            symbol="TSLA",
            company_name="Tesla",
            hours_back=24
        )
        
        if len(articles) > 0:
            for article in articles:
                assert article.age_hours >= 0
                assert article.age_hours <= 24  # Should be within requested window


class TestMacroCollector:
    """Tests for MacroCollector."""
    
    @pytest.fixture
    def collector(self):
        return MacroCollector()
    
    def test_get_market_regime(self, collector):
        """Test market regime determination."""
        regime = collector.get_market_regime()
        
        assert regime is not None
        assert regime.regime in ["STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "STRONG_BEAR"]
        assert 0.0 <= regime.regime_position_multiplier <= 1.0
        assert regime.vix_signal in ["LOW_FEAR", "NORMAL", "ELEVATED_FEAR", "HIGH_FEAR", "EXTREME_FEAR"]
    
    def test_get_sector_rotation(self, collector):
        """Test sector rotation signals."""
        signals = collector.get_sector_rotation()
        
        assert isinstance(signals, dict)
        # Should have some sectors
        assert len(signals) > 0
        
        # All signals should be valid
        for sector, signal in signals.items():
            assert signal in ["BULLISH", "NEUTRAL", "BEARISH"]
    
    def test_get_sector_for_symbol(self, collector):
        """Test getting sector for a symbol."""
        sector = collector.get_sector_for_symbol("AAPL")
        
        assert sector is not None
        assert isinstance(sector, str)
        assert len(sector) > 0


class TestEarningsCalendarCollector:
    """Tests for EarningsCalendarCollector."""
    
    @pytest.fixture
    def collector(self):
        return EarningsCalendarCollector()
    
    def test_has_earnings_risk(self, collector):
        """Test earnings risk detection."""
        result = collector.has_earnings_risk("AAPL")
        
        assert result is not None
        assert result.risk_level in ["NONE", "LOW", "HIGH", "BLOCK"]
        assert 0.0 <= result.position_size_multiplier <= 1.0
        assert isinstance(result.reasoning, str)
    
    def test_risk_level_consistency(self, collector):
        """Test that risk level matches multiplier."""
        result = collector.has_earnings_risk("TSLA")
        
        if result.risk_level == "BLOCK":
            assert result.position_size_multiplier == 0.0
        elif result.risk_level == "HIGH":
            assert result.position_size_multiplier == 0.5
        elif result.risk_level == "LOW":
            assert result.position_size_multiplier == 0.7
        else:  # NONE
            assert result.position_size_multiplier == 1.0


# Fixtures
@pytest.fixture(scope="session")
def test_symbol():
    """Common test symbol."""
    return "AAPL"


@pytest.fixture(scope="session")
def test_date_range():
    """Common test date range."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    return start_date, end_date
