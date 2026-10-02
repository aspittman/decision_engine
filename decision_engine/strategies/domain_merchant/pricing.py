"""Describe observed comparable sales without inventing a resale valuation."""
from statistics import median
from .scoring import numeric


def evaluate(candidate):
    prices = [numeric(r.get('sale_price')) for r in candidate.get('comparables', [])
              if r.get('currency') == 'USD' and r.get('source') and r.get('sale_date')]
    prices = [p for p in prices if p is not None and p > 0]
    return {'strategy':'pricing','status':'REVIEW' if len(prices)>=3 else 'UNKNOWN',
            'sample_size':len(prices),'observed_median':median(prices) if prices else None,
            'observed_min':min(prices) if prices else None,'observed_max':max(prices) if prices else None,
            'recommended_listing_price':None,'currency':'USD',
            'reason':'Comparable sale statistics only; asking price requires human review and unsold-inventory evidence'}
