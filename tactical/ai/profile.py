"""AIProfile — tunable personality and difficulty parameters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AIProfile:
    """Encapsulates all tuneable parameters for an AI side.

    personality
        Reserved for future alien psychology archetypes (e.g. "aggressive",
        "cautious", "swarm").  Currently unused — all AI behaviour is driven
        by the numeric fields below.  Adding a personality system later is a
        matter of mapping personality → numeric overrides without touching
        any other AI code.

    aggression  (0.0 … 1.0)
        0.0 = strongly prefers standoff range; will avoid trading fire at
              close quarters even when it would win.
        1.0 = always tries to close to its weapons' optimal band; ignores
              incoming damage in position scoring.
        Default 0.5 — balanced, "decent human" style.

    noise  (σ of Gaussian noise added to eval scores)
        0.0  = fully deterministic; always picks the objectively best move.
        0.15 = default; introduces occasional suboptimal choices that give
               the AI a human-like feel without being obviously random.
        0.4+ = clearly exploitable; good for "easy" difficulty.

    search_depth
        0 = choose a random legal move (used only for trivial difficulty).
        1 = greedy 1-ply evaluation (default; feels like a decent human).
        2 = one round of lookahead; noticeably stronger but slower.
        Values > 2 are currently not implemented; the parameter is reserved
        for future minimax/alpha-beta expansion.

    carrier_value
        Multiplier applied to carrier ships when scoring target priority in
        fire_ai.  Higher = AI prioritises killing carriers.
    """

    personality:   str   = "balanced"   # reserved — not yet implemented
    aggression:    float = 0.5
    noise:         float = 0.15
    search_depth:  int   = 1
    carrier_value: float = 2.0

    # Squadron endurance threshold at which the AI orders recovery.
    # A squadron with endurance <= this value will be recalled if a carrier
    # is reachable.  Higher = more conservative (recalls earlier).
    squadron_recover_threshold: int = 3


# Preset profiles ---------------------------------------------------------

DEFAULT = AIProfile()                                          # balanced, decent human
EASY    = AIProfile(noise=0.40, search_depth=0)               # nearly random
HARD    = AIProfile(noise=0.02, search_depth=1, aggression=0.7)  # sharp, aggressive
