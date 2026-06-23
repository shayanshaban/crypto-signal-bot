""" src/ai/llm_confirmer.py — LLM acts only as YES/NO final decision maker. """

from src.ai.deepseek_client import DeepSeekSession
from src.trading.rule_engine import SetupCandidate
from typing import Optional
import config


class LLMConfirmer:
    """Calls LLM with structured features, expects only YES or NO."""

    with open(config.PROMPT_FILE, "r", encoding="utf-8") as fh:
        CONFIRMATION_PROMPT_TEMPLATE = fh.read()

    def __init__(self, session: Optional[DeepSeekSession] = None):
        self._session = session

    @property
    def session(self) -> DeepSeekSession:
        """Return a session (creates one if not already set)."""
        if self._session is None:
            self._session = DeepSeekSession()
        return self._session

    def confirm(self, candidate: SetupCandidate, session: Optional[DeepSeekSession] = None) -> bool:
        """
        Send candidate to LLM, return True if YES, False otherwise.

        Args:
            candidate: SetupCandidate with all features.
            session: optional existing DeepSeekSession to reuse.
        """
        prompt = self.CONFIRMATION_PROMPT_TEMPLATE.format(
            setup_type=candidate.setup_type.value,
            symbol=candidate.symbol,
            side=candidate.side,
            timeframe=candidate.timeframe,
            **candidate.features
        )

        # Use provided session or create a new one
        if session is not None:
            # session is already open (we're inside a 'with' block)
            result = session.send(prompt)
        else:
            # open a new session and close it automatically
            with self.session as s:
                result = s.send(prompt)

        if not result:
            return False

        response = result.get('response', '').strip().upper()
        return response == 'YES'