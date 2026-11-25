"""Personal Deal Engine: is this a genuinely good purchase for the user's own use?"""

from dealradar.engines.personal.evaluator import PersonalResult, WatchlistRelevance, evaluate

__all__ = ["PersonalResult", "WatchlistRelevance", "evaluate"]
