"""Route planning and ship position interpolation for the campaign layer.

Public API
----------
ship_system_and_pos_at(ship, t_days) -> (system_id, q, r)
    Walk the route leg list to find where a ship is at an arbitrary game time.

build_route(galaxy, ship, dest_system_id, t_days) -> list[MoveLeg | TransitLeg]
    BFS through warp points; produce a fully-timed leg list.

find_intercept(from_q, from_r, speed, target, system_id, t_days) -> (q, r, day) | None
    Step-search for the earliest hex+time where an interceptor can meet target.

build_intercept_route(galaxy, interceptor, target, t_days) -> list[MoveLeg]
    Single MoveLeg to the computed intercept point; [] if no intercept possible.

Extension point
---------------
To allow routing from within a system view (player clicks a WP), call
build_route with a custom start position rather than reading ship.q_sh:

    advance ship position to t_days first, then call build_route normally.
    The function always reads current position via ship_system_and_pos_at,
    so advancing the snapshot before calling is sufficient.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from campaign.hex_utils import cube_round, hex_dist
from campaign.models import CampaignShip, Galaxy, GalaxyEdge, MoveLeg, TransitLeg

TRANSIT_COST_DAYS: float = 0.0  # stub; increase to add warp transit time


def ship_system_and_pos_at(
    ship: CampaignShip,
    t_days: float,
) -> tuple[str, int, int]:
    """Return (system_id, q_sh, r_sh) for ship at t_days.

    Walks the route leg list forward in time.  Legs that are fully elapsed
    are skipped; the first incomplete leg is interpolated.
    """
    system = ship.system_id
    q, r = ship.q_sh, ship.r_sh

    for leg in ship.route:
        if isinstance(leg, MoveLeg):
            if t_days < leg.arrive_day:
                total = leg.arrive_day - leg.start_day
                frac = min(1.0, (t_days - leg.start_day) / total) if total > 0 else 1.0
                q, r = cube_round(
                    leg.from_q + (leg.to_q - leg.from_q) * frac,
                    leg.from_r + (leg.to_r - leg.from_r) * frac,
                )
                return system, q, r
            q, r = leg.to_q, leg.to_r
        else:  # TransitLeg
            if t_days < leg.day:
                return system, q, r
            system = leg.to_system
            q, r   = leg.exit_q, leg.exit_r

    return system, q, r


def build_route(
    galaxy: Galaxy,
    ship: CampaignShip,
    dest_system_id: str,
    t_days: float,
) -> list[MoveLeg | TransitLeg]:
    """Build a fully-timed route from the ship's current position to dest_system_id.

    Returns [] if the ship is already in the destination system or no warp-point
    path exists.  The final leg leaves the ship at the exit WP of the last
    transit; an intra-system order can be layered on top later.
    """
    start_system, start_q, start_r = ship_system_and_pos_at(ship, t_days)

    if start_system == dest_system_id:
        return []

    path = _bfs(galaxy, start_system, dest_system_id)
    if path is None:
        return []

    legs: list[MoveLeg | TransitLeg] = []
    cur_system = start_system
    cur_q, cur_r = start_q, start_r
    cur_day = t_days

    for (exit_wp_id, edge) in path:
        node = galaxy.systems[cur_system]
        wp = next(w for w in node.warp_points if w.wp_id == exit_wp_id)

        # Intra-system leg: current position → exit WP
        dist = hex_dist(cur_q, cur_r, wp.q_sh, wp.r_sh)
        travel_days = dist / ship.sH_per_day if ship.sH_per_day > 0 else 0.0
        arrive_day = cur_day + travel_days

        if dist > 0:
            legs.append(MoveLeg(
                system_id=cur_system,
                from_q=cur_q, from_r=cur_r,
                to_q=wp.q_sh, to_r=wp.r_sh,
                start_day=cur_day,
                arrive_day=arrive_day,
            ))

        # Transit leg (instantaneous; TRANSIT_COST_DAYS is the extension stub)
        transit_day = arrive_day + TRANSIT_COST_DAYS
        dest_sys_id = edge.system_b if edge.system_a == cur_system else edge.system_a
        dest_wp_id  = edge.wp_b    if edge.system_a == cur_system else edge.wp_a
        dest_node   = galaxy.systems[dest_sys_id]
        dest_wp     = next(w for w in dest_node.warp_points if w.wp_id == dest_wp_id)

        legs.append(TransitLeg(
            from_system=cur_system,
            to_system=dest_sys_id,
            wp_from=exit_wp_id,
            wp_to=dest_wp_id,
            exit_q=dest_wp.q_sh,
            exit_r=dest_wp.r_sh,
            day=transit_day,
        ))

        cur_system = dest_sys_id
        cur_q, cur_r = dest_wp.q_sh, dest_wp.r_sh
        cur_day = transit_day

    return legs


def find_intercept(
    from_q: int,
    from_r: int,
    speed: float,
    target: CampaignShip,
    system_id: str,
    t_days: float,
    dt: float = 1 / 24,
    max_days: float = 365.0,
) -> Optional[tuple[int, int, float]]:
    """Step forward in dt increments to find the earliest intercept.

    Returns (q, r, arrive_day) of the first hex the interceptor can reach
    no later than the target occupies it.  Returns None if no intercept is
    possible within max_days or if the target leaves system_id first.
    """
    steps = int(max_days / dt)
    for i in range(steps + 1):
        t = t_days + i * dt
        sys, tq, tr = ship_system_and_pos_at(target, t)
        if sys != system_id:
            break
        dist = hex_dist(from_q, from_r, tq, tr)
        if speed > 0 and dist <= speed * i * dt:
            return tq, tr, t
    return None


def build_intercept_route(
    galaxy: Galaxy,
    interceptor: CampaignShip,
    target: CampaignShip,
    t_days: float,
) -> list:
    """Compute a single MoveLeg to intercept target within the same system.

    Returns [] if both ships are not in the same system or no intercept is
    reachable within 365 days.
    """
    cur_sys, cur_q, cur_r = ship_system_and_pos_at(interceptor, t_days)
    tgt_sys, _, _ = ship_system_and_pos_at(target, t_days)

    if cur_sys != tgt_sys:
        return []

    result = find_intercept(cur_q, cur_r, interceptor.sH_per_day, target, cur_sys, t_days)
    if result is None:
        return []

    tq, tr, arrive_day = result
    if hex_dist(cur_q, cur_r, tq, tr) == 0:
        return []

    return [MoveLeg(
        system_id=cur_sys,
        from_q=cur_q, from_r=cur_r,
        to_q=tq,      to_r=tr,
        start_day=t_days,
        arrive_day=arrive_day,
    )]


def find_path_collision(
    ship_a: CampaignShip,
    ship_b: CampaignShip,
    t_start: float,
    t_end:   float,
    dt:      float = 1 / 24,
) -> Optional[tuple[float, str, int, int]]:
    """Return (t, system_id, q, r) of the earliest hex shared by ship_a and ship_b.

    Steps in dt increments (default 1 hour) through [t_start, t_end].
    Handles ships that transition between systems during the window.
    Returns None if no collision is found.
    """
    t = t_start
    while True:
        sa, qa, ra = ship_system_and_pos_at(ship_a, t)
        sb, qb, rb = ship_system_and_pos_at(ship_b, t)
        if sa == sb and qa == qb and ra == rb:
            return (t, sa, qa, ra)
        if t >= t_end:
            break
        t = min(t + dt, t_end)
    return None


def _bfs(
    galaxy: Galaxy,
    start: str,
    dest: str,
) -> Optional[list[tuple[str, GalaxyEdge]]]:
    """BFS on the warp-point graph.

    Returns a list of (exit_wp_id, GalaxyEdge) for each hop from start to dest,
    or None if dest is unreachable.
    """
    adj: dict[str, list[tuple[str, GalaxyEdge]]] = {sid: [] for sid in galaxy.systems}
    for edge in galaxy.edges:
        adj[edge.system_a].append((edge.wp_a, edge))
        adj[edge.system_b].append((edge.wp_b, edge))

    visited: set[str] = {start}
    queue: deque[tuple[str, list[tuple[str, GalaxyEdge]]]] = deque()
    queue.append((start, []))

    while queue:
        cur, path = queue.popleft()
        for (exit_wp, edge) in adj[cur]:
            nxt = edge.system_b if edge.system_a == cur else edge.system_a
            if nxt in visited:
                continue
            new_path = path + [(exit_wp, edge)]
            if nxt == dest:
                return new_path
            visited.add(nxt)
            queue.append((nxt, new_path))

    return None
