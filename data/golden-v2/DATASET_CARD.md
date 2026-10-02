# Golden v2

Verified country-checkpointed city normalization at H3 resolution 8.
6,875,329 places; 68,923 absorbing cities/towns; 66,226,680 compact cells.

Country/state/land membership retains the base snapshot. Policy polygons, accepted city polygons, GHSL urban allocation and optional town radii precede rural polygons/nearest settlements. Nearest answers beyond 25 km are flagged; 50 km remains the inclusive cutoff.

See quality.json and quality/<country>.json for regenerated checks, including failures; these consistency/source checks are not independent accuracy. Dhaka has an inferred urban allocation, not a verified municipal boundary. See docs/GOLDEN_V2.md for reproduction and limitations.
