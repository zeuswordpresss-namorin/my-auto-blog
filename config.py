# -*- coding: utf-8 -*-
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE_PATH = os.path.join(BASE_DIR, "keywords_queue.json")

TARGET_GEO = "KR"
MAX_TRENDS_COUNT = 7

TRENDS_RSS_URLS = [
    "https://trends.google.com/trending/rss?geo=KR",
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR"
]
GOOGLE_AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"

MIN_KEYWORD_LENGTH = 2
MAX_KEYWORD_LENGTH = 30

BANNED_WORDS = ["토토", "카지노", "성인", "몰카", "불법", "마약", "조건만남"]

SCORE_WEIGHTS = {
    "trend_rank": 0.4,
    "source_bonus": 0.3,
    "cpc_bonus": 0.3
}

CPC_BONUS_WORDS = {
    "대출": 30.0, "보험": 30.0, "카드": 20.0, "주식": 15.0,
    "클라우드": 15.0, "자격증": 10.0, "정부지원금": 25.0, "창업": 15.0
}

