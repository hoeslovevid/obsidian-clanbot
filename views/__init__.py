"""
Views package - Discord UI views by feature domain.

All view classes are in views/_core.py.
Future planned split:
  views/_pagination.py   EmbedPaginator
  views/_utility.py      RetryView, RefreshView, ConfirmView
  views/_vc.py           SetLimitSelect, SetLimitView, VCPanelView
  views/_complaints.py   ComplaintPanel, ComplaintModView
  views/_events.py       RSVPView
  views/_trading.py      TradingPostView
  views/_giveaway.py     GiveawayView
  views/_applications.py ApplicationManageView, ApplicationPanelView
"""
from views._core import (  # noqa: F401
    EmbedPaginator,
    RetryView,
    RefreshView,
    ConfirmView,
    SetLimitSelect,
    SetLimitView,
    VCPanelView,
    ComplaintPanel,
    ComplaintModView,
    RSVPView,
    TradingPostView,
    GiveawayView,
    ApplicationManageView,
    ApplicationPanelView
)
