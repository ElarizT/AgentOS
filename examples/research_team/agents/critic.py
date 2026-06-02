from dataclasses import replace

from agentos import AgentProcess

from ..contracts import CriticReview, SynthesizedReport
from ..data import CRITIC_REVIEW


class CriticAgent(AgentProcess):
    name = "Critic"

    async def on_message(self, message) -> None:
        self.report_received = SynthesizedReport(**message.payload["report"])
        print("[Critic] Received synthesized report")
        self.review = self.create_review()
        print("[Critic] Generated review")
        print(f"[Critic] Quality score: {self.review.score}/10")

    def create_review(self) -> CriticReview:
        return replace(
            CRITIC_REVIEW,
            strengths=list(CRITIC_REVIEW.strengths),
            weaknesses=list(CRITIC_REVIEW.weaknesses),
        )
