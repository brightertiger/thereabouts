"""Land, coverage and administrative status policy at the original point."""

from .models import AdminMatch, LandStatus
from .pack import Pack
from .polygons import PolygonIndex


def empty_match(status: str) -> AdminMatch:
    if status == "not_applicable":
        return AdminMatch("not_applicable", None, (), "none")
    return AdminMatch("no_coverage", None, (), "none")


class AdminLookup:
    def __init__(self, pack: Pack) -> None:
        self.pack = pack
        self.country = PolygonIndex(pack, "country")
        self.admin1 = PolygonIndex(pack, "admin1")
        self.land = PolygonIndex(pack, "land")

    def _match(self, layer: str, rows: tuple[int, ...]) -> AdminMatch:
        values = tuple(
            sorted((self.pack.admin(layer, i) for i in rows), key=lambda a: a.id)
        )
        if not values:
            return empty_match("no_coverage")
        return AdminMatch(
            "matched" if len(values) == 1 else "ambiguous",
            values[0] if len(values) == 1 else None,
            values,
            "polygon",
        )

    def lookup(
        self, lat: float, lon: float
    ) -> tuple[AdminMatch, AdminMatch, LandStatus]:
        bounds = self.pack.manifest["coverage_bbox"]
        if bounds is not None:
            w, s, e, n = bounds
            if not (w <= lon <= e and s <= lat <= n):
                return empty_match("no_coverage"), empty_match("no_coverage"), "unknown"
        countries = self.country.query(lat, lon)
        subdivisions = self.admin1.query(lat, lon)
        # Administrative coverage fills inland-water holes without erasing identities.
        inside = bool(countries or subdivisions or self.land.query(lat, lon))
        if not inside:
            return (
                empty_match("not_applicable"),
                empty_match("not_applicable"),
                "outside_mask",
            )
        country = self._match("country", countries)
        admin1 = self._match("admin1", subdivisions)
        if (
            not subdivisions
            and countries
            and all(
                self.pack.arrays["countries"][i]["subdivisions"] == 1 for i in countries
            )
        ):
            admin1 = empty_match("not_applicable")
        return country, admin1, "inside_mask"

    def close(self) -> None:
        for index in (self.country, self.admin1, self.land):
            index.close()
