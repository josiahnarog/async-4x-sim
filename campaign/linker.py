"""Warp point linking — forms the galaxy network graph.

Algorithm (from rules):
  For each unlinked WP across all systems:
    a. Draw a random system (not the WP's own system).
    b. From that system, draw a random unlinked WP.
    c. If none remain in that system, try another system.
    d. If no valid partner exists anywhere, remove the WP.

All WPs can link to any other WP regardless of visibility tier.
Visibility is a per-WP property affecting detection/gameplay only.
"""

from __future__ import annotations

import random

from campaign.models import Galaxy, GalaxyEdge, SystemNode, WarpPoint


def link_galaxy(
    systems: dict[str, SystemNode],
    rng: random.Random,
) -> list[GalaxyEdge]:
    """Pair all warp points into galaxy edges.

    Mutates WarpPoint.linked_to in place and returns the edge list.
    Also removes any WP that could not be linked.
    """
    # Build flat list of (system_id, wp) for all unlinked WPs
    unlinked: list[tuple[str, WarpPoint]] = [
        (sid, wp)
        for sid, node in systems.items()
        for wp in node.warp_points
    ]
    rng.shuffle(unlinked)

    edges: list[GalaxyEdge] = []
    linked_wp_ids: set[str] = set()

    for sys_a, wp_a in unlinked:
        if wp_a.wp_id in linked_wp_ids:
            continue  # already paired in a previous iteration

        # Build candidate pool: unlinked WPs in other systems
        candidates = [
            (sys_b, wp_b)
            for sys_b, wp_b in unlinked
            if sys_b != sys_a and wp_b.wp_id not in linked_wp_ids
        ]

        if not candidates:
            # No valid partner — remove this WP
            systems[sys_a].warp_points = [
                w for w in systems[sys_a].warp_points if w.wp_id != wp_a.wp_id
            ]
            continue

        # Draw a random candidate system, then pick a random WP from it
        candidate_systems = list({sys_b for sys_b, _ in candidates})
        chosen_sys = rng.choice(candidate_systems)
        sys_candidates = [(s, w) for s, w in candidates if s == chosen_sys]
        _, wp_b = rng.choice(sys_candidates)
        sys_b = chosen_sys

        # Link them
        wp_a.linked_to = (sys_b, wp_b.wp_id)
        wp_b.linked_to = (sys_a, wp_a.wp_id)
        linked_wp_ids.add(wp_a.wp_id)
        linked_wp_ids.add(wp_b.wp_id)

        edges.append(GalaxyEdge(
            system_a=sys_a, wp_a=wp_a.wp_id,
            system_b=sys_b, wp_b=wp_b.wp_id,
        ))

    return edges


def build_galaxy(
    systems: dict[str, SystemNode],
    rng: random.Random,
) -> Galaxy:
    """Link all WPs and return a fully-connected Galaxy object."""
    from campaign.models import Galaxy
    edges = link_galaxy(systems, rng)
    return Galaxy(systems=systems, edges=edges)
