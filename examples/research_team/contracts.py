from dataclasses import dataclass


@dataclass
class ResearchAssignment:
    topic: str
    focus_area: str
    destination: str


@dataclass
class ResearchResult:
    focus_area: str
    findings: list[str]


@dataclass
class SynthesizedReport:
    topic: str
    benefits: list[str]
    risks: list[str]
    market: list[str]
    summary: str


@dataclass
class CriticReview:
    score: float
    strengths: list[str]
    weaknesses: list[str]
    final_note: str

