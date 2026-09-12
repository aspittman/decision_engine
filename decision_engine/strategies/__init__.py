from .outreach import OutreachStrategy
from .domain_acquisition import DomainAcquisitionStrategy
from .google_ads import GoogleAdsStrategy
from .landing_pages import LandingPageStrategy
from .seo import SEOStrategy


def default_strategies(config):
    return [cls(config) for cls in (OutreachStrategy, DomainAcquisitionStrategy, GoogleAdsStrategy, LandingPageStrategy, SEOStrategy)]
