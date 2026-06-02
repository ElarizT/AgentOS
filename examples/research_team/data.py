from .contracts import CriticReview


TOPIC = "Future of AI in Healthcare"

BENEFITS = [
    "Faster diagnosis",
    "Reduced costs",
    "Personalized medicine",
]

RISKS = [
    "Privacy concerns",
    "Bias in models",
    "Regulatory challenges",
]

MARKET_TRENDS = [
    "Growing adoption",
    "Increased investment",
    "Hospital automation",
]

CRITIC_REVIEW = CriticReview(
    score=8.7,
    strengths=[
        "Balanced coverage",
        "Multiple perspectives",
    ],
    weaknesses=[
        "Limited regulatory analysis",
    ],
    final_note=(
        "The report gives a clear introductory overview of AI in healthcare, "
        "but future versions should include deeper policy and compliance analysis."
    ),
)

