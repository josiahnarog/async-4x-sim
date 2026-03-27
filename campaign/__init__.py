"""Campaign / strategic layer for the async-4x-sim.

Three-layer architecture:
  Galaxy Network  — graph of SystemNodes connected by warp-point edges.
  System Map      — hex grid (sH units) inside each node.
  Tactical Map    — existing engine (TH units); 1 sH = 2,880 TH.

Public entry points:
  campaign.generator.generate_system(rng, node_id, category) -> SystemNode
  campaign.linker.link_galaxy(systems, rng) -> list[GalaxyEdge]
"""
