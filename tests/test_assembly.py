"""SwAssembly against a fake COM assembly: no SolidWorks, no licence.

Every one of these paths used to be exercised only by opening the real
application, which is why assembly.py carried 377 lines at zero coverage.
The fake below answers exactly the members the module reads, in the shapes the
module reads them (member() handles both a value and a method).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from swforge.assembly import Component, SwAssembly, world_box_mm
from swforge.session import SwError

ASM_PATH = r"C:\out\stack.SLDASM"


def make_component(name: str = "bolt-1", path: str = r"C:\out\bolt.sldprt"):
    return SimpleNamespace(Name2=name, GetPathName=path, GetConstrainedStatus=2)


def make_body(lo=(0.0, 0.0, 0.0), hi=(0.02, 0.0453, 0.08)):
    return SimpleNamespace(GetBodyBox=lambda: (*lo, *hi))


class FakeAsmModel:
    """The assembly document: what add_component and friends ask of it."""

    def __init__(self, path: str = ASM_PATH, component_list=()):
        self.GetPathName = path
        self.GetTitle = Path(path).stem
        self._components = list(component_list)
        self.inserted: list[tuple] = []
        self.selected: list[tuple] = []
        self.views: list[tuple] = []
        self.mass_property = None
        self.SketchManager = None
        self.FeatureManager = None
        self.Extension = SimpleNamespace(
            SelectByID2=self._select, CreateMassProperty=None
        )

    def _select(self, *args):
        self.selected.append(args)
        return True

    def AddComponent5(self, path, *args):
        self.inserted.append((path, args))
        comp = make_component(name=f"{Path(path).stem}-{len(self.inserted)}", path=path)
        self._components.append(comp)
        return comp

    def GetComponents(self, *args):
        return tuple(self._components)

    def ClearSelection2(self, *_args):
        return True

    def ShowNamedView2(self, name, view_id):
        self.views.append(("show", name, view_id))

    def NameView(self, name):
        self.views.append(("name", name))


def test_close_closes_the_parts_it_opened_before_the_assembly(fake_app, tmp_path, fake_com):
    part = tmp_path / "bolt.sldprt"
    part.write_bytes(b"x")
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    asmb.load_part(part)
    asmb.close()
    assert fake_app.closed == [str(part.resolve()), ASM_PATH], (
        "the parts go first: once the assembly document is closed its component "
        "references are gone and the part files cannot be closed through it"
    )


def test_load_part_reuses_a_document_that_is_already_open(fake_app, tmp_path):
    part = tmp_path / "bolt.sldprt"
    part.write_bytes(b"x")
    existing = SimpleNamespace(GetPathName=str(part.resolve()), GetTitle=part.name)
    fake_app.docs.append(existing)
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    assert asmb.load_part(part) is existing, (
        "OpenDoc6 answers errors=65536 for a document that is already open, so a "
        "second open would fail on a part that visibly exists"
    )
    assert fake_app.opened == [], "reusing a document is not an open"
    asmb.close()
    assert fake_app.closed == [ASM_PATH], (
        "the ledger only holds what this assembly opened, so the reused part "
        "must not be closed behind the caller's back"
    )


def test_add_component_shifts_y_by_half_the_part_height(fake_app, tmp_path):
    part = tmp_path / "bolt.sldprt"
    part.write_bytes(b"x")
    fake_app.docs.append(make_doc_with_bodies(str(part.resolve())))
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    asmb.add_component(part, x_mm=10.0, y_mm=0.0, z_mm=20.0)
    _path, args = asmb.model.inserted[-1]
    assert args[4] == pytest.approx(0.010), "x is already a centre, metres"
    assert args[5] == pytest.approx(-0.02265), (
        "AddComponent5 centres the bounding box on the point it is given, while "
        "y means the top face: 45.3 mm tall part -> half of it hangs below"
    )
    assert args[6] == pytest.approx(0.020)


def test_add_component_refuses_a_part_that_is_not_on_disk(fake_app, tmp_path):
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    missing = tmp_path / "nope.sldprt"
    with pytest.raises(SwError, match="part does not exist"):
        asmb.add_component(missing)


def test_add_component_keeps_the_callers_instance_name(fake_app, tmp_path):
    part = tmp_path / "bolt.sldprt"
    part.write_bytes(b"x")
    fake_app.docs.append(make_doc_with_bodies(str(part.resolve())))
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    inserted = asmb.add_component(part, instance="washer-1")
    assert inserted.name == "bolt-1", "SolidWorks names it after the file on disk"
    assert asmb.find("washer-1") is inserted, (
        "the caller's name has to survive the rename, or a spec that says "
        "bolt-1 can never find its component again"
    )


def test_find_lists_what_the_assembly_does_have(fake_app):
    asmb = SwAssembly(FakeAsmModel(component_list=[make_component("plate-1")]), fake_app)
    with pytest.raises(SwError, match="no component 'washer'") as caught:
        asmb.find("washer")
    assert "plate-1" in str(caught.value), (
        "the error has to name what is there, or the caller is left guessing "
        "which component SolidWorks actually gave a different name"
    )


def test_select_plane_qualifies_with_component_and_assembly(fake_app, fake_com):
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    comp = Component("bolt-1", "bolt-1@stack", make_component(), Path(r"C:\out\bolt.sldprt"))
    qualified = asmb.select_plane(comp, "上视基准面")
    assert qualified == "上视基准面@bolt-1@stack"
    assert asmb.model.selected[-1][0] == qualified, (
        "a bare plane name selects the assembly's own plane, not the component's"
    )


def test_world_box_maps_the_local_box_through_the_transform():
    comp = Component(
        "bolt-1",
        "bolt-1@stack",
        SimpleNamespace(GetBodies2=lambda *a: [make_body()], Transform2=SimpleNamespace(ArrayData=(
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
            0.01, 0.0, 0.02,
            0.0, 0.0, 0.0, 1.0,
        ))),
        Path(r"C:\out\bolt.sldprt"),
    )
    lo, hi = world_box_mm(comp)
    assert lo == pytest.approx((10.0, 0.0, 20.0))
    assert hi == pytest.approx((30.0, 45.3, 100.0)), (
        "translation is metres in slots 9..11; the local box is metres too"
    )


def test_world_box_refuses_a_component_without_a_transform():
    comp = Component(
        "bolt-1",
        "bolt-1@stack",
        SimpleNamespace(GetBodies2=lambda *a: [make_body()], Transform2=None),
        Path(r"C:\out\bolt.sldprt"),
    )
    with pytest.raises(SwError, match="has no usable transform"):
        world_box_mm(comp)


def test_measure_refuses_an_assembly_without_components(fake_app):
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    with pytest.raises(SwError, match="mass properties are unavailable"):
        asmb.measure()


def test_name_view_stores_the_orientation_on_the_model(fake_app):
    asmb = SwAssembly(FakeAsmModel(), fake_app)
    asmb.name_view("swforge_iso", 7)
    assert asmb.model.views == [("show", "", 7), ("name", "swforge_iso")], (
        "CreateDrawViewFromModelView3 only accepts a named view, so the "
        "orientation has to be stored on the model first"
    )


def test_assembly_without_an_app_refuses_to_open_parts(tmp_path):
    asmb = SwAssembly(FakeAsmModel(), None)
    with pytest.raises(SwError, match="not bound to a SolidWorks instance"):
        asmb.load_part(tmp_path / "bolt.sldprt")


def make_doc_with_bodies(path: str):
    from conftest import make_doc

    return make_doc(path=path, GetBodies2=lambda *args: [make_body()])
