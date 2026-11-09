"""Templates: routines with blanks, ready to install.

Three places, looked through in this order:

* ``~/.vidhi/catalog/*.toml`` -- templates of this computer's own: one
  written by hand, or saved from the canvas with **Save as template**;
* ``~/.vidhi/market/*.toml`` -- templates installed from a marketplace,
  each beside the reviewer's signature it came with (market.py);
* the templates that come with Vidhi (``vidhi/catalog/``): the morning
  brief, price-then-plan, and a cold-night warning.

A name found in an earlier place hides the same name in a later one, so
a person's own copy of ``morning-brief`` is the one they get.

A TEMPLATE THAT DOESN'T READ IS LEFT OUT, AND SAID. One broken file in
``~/.vidhi/catalog`` must not hide the rest; ``broken`` lists it with
why.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from vidhi import routine as rt


@dataclass
class Template:
    routine: rt.Routine
    text: str
    #: "mine", "market", or "vidhi"
    source: str
    path: str
    signed_by: str = ""

    def card(self) -> dict:
        r = self.routine
        return {"name": r.name, "title": r.title, "about": r.about, "version": r.version,
                "author": r.author, "source": self.source, "signed_by": self.signed_by,
                "cost": rt.cost(r), "touches": rt.touches(r),
                "inputs": [i.as_dict() for i in r.inputs],
                "needs": r.needs, "steps": len(r.steps)}


def places(state: Path) -> list[tuple[str, Path | None]]:
    return [("mine", Path(state) / "catalog"), ("market", Path(state) / "market"),
            ("vidhi", None)]


def templates(state: Path) -> tuple[list[Template], list[str]]:
    """(the templates, the files that didn't read and why)."""
    found: dict[str, Template] = {}
    broken: list[str] = []
    for source, folder in places(state):
        for path, text in _files(folder):
            try:
                routine = rt.parse(text)
            except rt.RoutineError as exc:
                broken.append(f"{path}: {exc}")
                continue
            if routine.name in found:
                continue
            signed_by = ""
            if source == "market":
                from vidhi.market import signer_of
                signed_by = signer_of(Path(path))
            found[routine.name] = Template(routine, text, source, str(path), signed_by)
    return sorted(found.values(), key=lambda t: t.routine.name), broken


def template(state: Path, name: str) -> Template:
    found, _ = templates(state)
    for one in found:
        if one.routine.name == name:
            return one
    raise rt.RoutineError(f"no template {name!r} (vidhi templates lists them: "
                          f"{', '.join(t.routine.name for t in found)})")


def save_mine(state: Path, text: str) -> Path:
    """A routine kept as one of this computer's own templates."""
    routine = rt.parse(text)
    folder = Path(state) / "catalog"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{routine.name}.toml"
    path.write_text(text)
    return path


def _files(folder: Path | None) -> list[tuple[str, str]]:
    if folder is None:
        root = files("vidhi") / "catalog"
        return sorted((f"vidhi:{p.name}", p.read_text()) for p in root.iterdir()
                      if p.name.endswith(".toml"))
    if not folder.is_dir():
        return []
    return sorted((str(p), p.read_text()) for p in folder.glob("*.toml"))
