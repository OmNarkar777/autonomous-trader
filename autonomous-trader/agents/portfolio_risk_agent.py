# File: agents/portfolio_risk_agent.py
# Find line ~150-200, replace check_portfolio_constraints method

def check_portfolio_constraints(self, symbol, sector, position_value):
    '''Check if new position violates portfolio constraints'''
    
    # Get CURRENT portfolio state
    current_positions = self.broker.get_positions()
    current_portfolio_value = self.broker.get_account_info().portfolio_value
    
    # Calculate NEW state AFTER adding this position
    new_portfolio_value = current_portfolio_value + position_value
    
    # Calculate NEW sector allocation
    sector_totals = {}
    for pos in current_positions:
        pos_sector = self.get_sector(pos.symbol)
        sector_totals[pos_sector] = sector_totals.get(pos_sector, 0) + pos.current_price * pos.quantity
    
    # Add new position to sector total
    sector_totals[sector] = sector_totals.get(sector, 0) + position_value
    
    # Check sector concentration in NEW state
    sector_pct = sector_totals[sector] / new_portfolio_value
    if sector_pct > MAX_SECTOR_CONCENTRATION:
        return PortfolioConstraints(
            passed=False,
            reason=f'Sector {sector} would be {sector_pct:.1%} > max {MAX_SECTOR_CONCENTRATION:.1%}'
        )
    
    # Check position size
    position_pct = position_value / current_portfolio_value
    if position_pct > MAX_POSITION_SIZE_PCT:
        return PortfolioConstraints(
            passed=False,
            reason=f'Position would be {position_pct:.1%} > max {MAX_POSITION_SIZE_PCT:.1%}'
        )
    
    return PortfolioConstraints(passed=True, reason='OK')
