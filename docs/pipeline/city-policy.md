# City policy

The common and country policies in `config/policies/cities/` pin the source
identities, accepted footprints, city parts and independent neighbours used by
city normalization.

## City granularity rules

- A city or town owns its accepted footprint. Smaller places within that
  footprint report the canonical city identity. Wards, boroughs and other
  accepted city parts roll up to that identity.
- An independent neighbouring city keeps its own identity and accepted boundary,
  including at shared edges. A connected metropolitan urban cluster may contain
  several cities; it is not one unconditional city footprint.
- Standalone villages outside city and town footprints keep their identities.
  A weak village administrative seat does not gain absorption authority without
  an established city or town footprint or an explicit country rule.
- A country, province, prefecture, township or other broad administrative
  container does not become a city merely because it shares its seat's identity.
  Accepted limits constrain expansion; city-part anchors do not compete with
  their canonical city.
- Use approved municipal polygons or pinned unions of their parts. Where a
  policy requires urban clipping, retain the connected GHSL core within the
  approved administrative extent, excluding broad rural administration.

The country policies apply these conventions to the following reviewed cases:

| Country | City convention | Independent neighbours |
| --- | --- | --- |
| India | Mumbai's 24 wards form Mumbai; New Delhi rolls up to Delhi; retain Kolkata's city limits. | Navi Mumbai, Thane, Noida and Howrah remain separate. |
| Japan | Tokyo's 23 wards form the city; the wider prefecture is not its city footprint. | Yokohama remains separate. |
| United Kingdom | London's 33 pinned members form London. | Towns outside the accepted London extent remain separate. |
| United States | New York's five boroughs report New York. | Preserve independent cities; broad township containers are not automatically city footprints. |
| Türkiye | Istanbul's approved extent is clipped to its connected urban core within the province. | Do not absorb independent cities merely because they share an urban cluster. |
| China | Beijing, Shanghai, Tianjin and Chongqing use approved municipal identities clipped to their connected urban cores. | Broad rural administration and independent settlements are not absorbed wholesale. |
| Malaysia | Kuala Lumpur owns its accepted city footprint. | Petaling Jaya remains separate. |

The YAML files retain the exact source IDs and evidence for each footprint,
part, exception and independent neighbour. These rules do not introduce new
membership, eligibility thresholds or geometry.

The policy files cite the label `docs/CITY_NORMALIZATION_PLAN.md`, the name of the
superseded plan whose rules this page now carries. The label is kept verbatim
because the policy text is part of every reviewed city unit's identity and of the
review fingerprint.
