from __future__ import annotations

import pytest

from kcd_mod_manager.domain import categories as cat
from kcd_mod_manager.domain import profiles as prof
from kcd_mod_manager.domain.highlight import preset
from kcd_mod_manager.domain.library_view import SortMode, matches, next_sort_mode, sort_mods, visible_mods
from kcd_mod_manager.domain.mod_order import (
    OrderEntry,
    apply_order_entries,
    move_in_scope,
    parse_mod_order,
    renumber,
    serialize_mod_order,
)
from kcd_mod_manager.domain.models import Mod, ModCategory, ModProfile
from kcd_mod_manager.domain.naming import (
    extract_mod_number,
    generate_mod_id,
    safe_file_name,
    version_from_file_name,
    version_from_nexus_folder_name,
)
from kcd_mod_manager.domain.versioning import (
    compare_app_versions,
    is_game_version_compatible,
    is_newer,
    is_not_newer,
    parse_version,
)


def mods(*ids: str) -> list[Mod]:
    return [Mod(id=i, name=i.title(), number=n) for n, i in enumerate(ids, start=1)]


class TestVersioning:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1.2", (1, 2, -1, -1)),
            ("1.2.3.4", (1, 2, 3, 4)),
            (" 1.0 ", (1, 0, -1, -1)),
            ("1", None),
            ("1.2.3.4.5", None),
            ("1.a", None),
            ("v1.2", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_matches_dotnet_version(self, text: str | None, expected: tuple[int, ...] | None) -> None:
        assert parse_version(text) == expected

    def test_missing_components_rank_lower(self) -> None:
        assert is_newer("1.0.0", "1.0")
        assert not is_newer("1.0", "1.0.0")

    def test_unparsable_versions_never_report_updates(self) -> None:
        assert not is_newer("2", "1.0")
        assert not is_newer("2.0", "N/A")

    def test_not_newer(self) -> None:
        assert is_not_newer("1.0", "1.0")
        assert is_not_newer("1.0", "1.1")
        assert not is_not_newer("1.2", "1.1")
        assert not is_not_newer("abc", "1.1")

    def test_game_compatibility(self) -> None:
        assert is_game_version_compatible(None, "1.2.3")
        assert is_game_version_compatible("1.2", "1.2.3.4")
        assert not is_game_version_compatible("1.1", "1.2.3")
        assert is_game_version_compatible("1.2", None)

    def test_app_versions(self) -> None:
        assert compare_app_versions("v5.1", "5.0.0")
        assert not compare_app_versions("v4.3", "5.0.0")
        assert not compare_app_versions("5.0", "5.0.0")


class TestModOrder:
    def test_parse_handles_comments_blank_lines_and_whitespace(self) -> None:
        entries = parse_mod_order(["mod_a", "", "  # mod_b  ", "#mod_c", "   ", "\tmod_d"])
        assert entries == [
            OrderEntry("mod_a", True),
            OrderEntry("mod_b", False),
            OrderEntry("mod_c", False),
            OrderEntry("mod_d", True),
        ]

    def test_only_one_hash_is_stripped(self) -> None:
        assert parse_mod_order(["## odd"]) == [OrderEntry("# odd", False)]

    def test_serialize_orders_by_number(self) -> None:
        items = mods("a", "b", "c")
        items[0].number, items[2].number = 3, 1
        items[1].is_enabled = True
        assert serialize_mod_order(items) == ["# c", "b", "# a"]

    def test_round_trip(self) -> None:
        items = mods("a", "b")
        items[0].is_enabled = True
        entries = parse_mod_order(serialize_mod_order(items))
        assert entries == [OrderEntry("a", True), OrderEntry("b", False)]

    def test_apply_order_puts_unlisted_last_and_enabled(self) -> None:
        items = mods("x", "a", "b")
        ordered = apply_order_entries(
            items, [OrderEntry("b", False), OrderEntry("missing", True), OrderEntry("a", True)]
        )
        assert [m.id for m in ordered] == ["b", "a", "x"]
        assert [m.is_enabled for m in ordered] == [False, True, True]
        assert ordered[2].number == 0

    def test_move_in_scope_respects_hidden_mods(self) -> None:
        items = mods("a", "b", "c", "d", "e")
        visible = [items[0], items[2], items[4]]  # a, c, e
        assert move_in_scope(items, visible, items[4], 0)
        assert [m.id for m in items] == ["e", "a", "b", "c", "d"]

    def test_move_in_scope_down(self) -> None:
        items = mods("a", "b", "c")
        a = items[0]
        assert move_in_scope(items, list(items), a, 2)
        assert [m.id for m in items] == ["b", "c", "a"]
        assert not move_in_scope(items, list(items), a, 99)

    def test_renumber(self) -> None:
        items = mods("a", "b")
        items.reverse()
        renumber(items)
        assert [(m.id, m.number) for m in items] == [("b", 1), ("a", 2)]


class TestNaming:
    def test_generate_mod_id_removes_only_invalid_characters(self) -> None:
        assert generate_mod_id("Test_Mod-Name", True) == "Test_Mod-Name"
        assert generate_mod_id('Te<s>t:"Mod"', True) == "TestMod"

    def test_generate_mod_id_fallback_is_md5_prefix(self) -> None:
        result = generate_mod_id("<>:", True)
        assert len(result) == 8
        assert result == generate_mod_id("<>:", True)

    def test_generate_mod_id_empty(self) -> None:
        assert generate_mod_id("", True) == "d41d8cd9"

    def test_generate_mod_id_without_renaming_keeps_name(self) -> None:
        assert generate_mod_id("My:Mod", False) == "My:Mod"

    def test_extract_mod_number(self) -> None:
        assert extract_mod_number("Better Swords-187-1-2-1700000000") == 187
        assert extract_mod_number("no number here") == -1
        assert extract_mod_number("mod_v2") == -1
        assert extract_mod_number("x-99999999999-1") == -1

    def test_versions_from_names(self) -> None:
        assert version_from_nexus_folder_name("Better Swords-187-1-2-1700000000") == "1.2"
        assert version_from_nexus_folder_name("plain") == "N/A"
        assert version_from_file_name("a-b-c-d") == "c"
        assert version_from_file_name("a-b") == "0"

    def test_safe_file_name(self) -> None:
        assert safe_file_name('a/b\\c:d*e?"f<g>h|') == "a_b_c_d_e__f_g_h_"


class TestLibraryView:
    def test_search_matches_name_or_version(self) -> None:
        mod = Mod(id="x", name="Better Swords", version="1.4")
        assert matches(mod, "sword", None)
        assert matches(mod, "1.4", None)
        assert not matches(mod, "armor", None)

    def test_category_filter(self) -> None:
        a = Mod(id="a", name="A", category_id="cat-1")
        b = Mod(id="b", name="B")
        assert matches(a, "", None) and matches(b, "", None)
        assert not matches(a, "", "") and matches(b, "", "")
        assert matches(a, "", "CAT-1") and not matches(b, "", "cat-1")

    def test_sort_cycle(self) -> None:
        assert next_sort_mode(SortMode.LOAD_ORDER, False) is SortMode.TITLE
        assert next_sort_mode(SortMode.TITLE, False) is SortMode.LOAD_ORDER
        assert next_sort_mode(SortMode.TITLE, True) is SortMode.CATEGORY
        assert next_sort_mode(SortMode.CATEGORY, True) is SortMode.LOAD_ORDER

    def test_category_sort(self) -> None:
        categories = [ModCategory("c2", "Second", 1), ModCategory("c1", "First", 0)]
        items = [
            Mod(id="u", name="Zed"),
            Mod(id="b", name="Beta", category_id="c2"),
            Mod(id="a", name="Alpha", category_id="c2"),
            Mod(id="f", name="Foo", category_id="c1"),
        ]
        assert [m.id for m in sort_mods(items, SortMode.CATEGORY, categories)] == ["f", "a", "b", "u"]
        assert [m.id for m in visible_mods(items, "", None, SortMode.TITLE, categories)] == [
            "a",
            "b",
            "f",
            "u",
        ]


class TestCategories:
    def test_create_rename_delete(self) -> None:
        items: list[ModCategory] = []
        first = cat.create_category(items, " Weapons ")
        second = cat.create_category(items, "Armor")
        assert first.id.startswith("cat-") and len(first.id) == 36
        assert (first.name, first.order, second.order) == ("Weapons", 0, 1)
        with pytest.raises(cat.CategoryError):
            cat.create_category(items, "weapons")
        with pytest.raises(cat.CategoryError):
            cat.rename_category(items, second.id, "WEAPONS")
        cat.rename_category(items, second.id, "Armour")
        remaining = cat.delete_category(items, first.id)
        assert [(c.name, c.order) for c in remaining] == [("Armour", 0)]


class TestProfiles:
    def test_snapshot_and_apply(self) -> None:
        items = mods("a", "b", "c")
        items[0].is_enabled = True
        items[2].is_enabled = True
        items[1].has_separator_after = True
        snap = prof.snapshot("P", items)
        assert snap.active_mods == ["a", "c"]
        assert snap.load_order == ["a", "b", "c"]
        assert snap.separators_after_mod_ids == ["b"]

        profile = ModProfile("P", active_mods=["b"], load_order=["c", "b"])
        fresh = mods("a", "b", "c", "new")
        result = prof.apply_profile(fresh, profile)
        assert [m.id for m in result] == ["c", "b", "a", "new"]
        assert [m.is_enabled for m in result] == [False, True, False, False]

    def test_rename_keeps_position(self) -> None:
        profile = ModProfile("P", active_mods=["a", "b"], load_order=["a", "b", "c"])
        assert prof.rename_mod_id(profile, "b", "z")
        assert profile.load_order == ["a", "z", "c"]
        assert profile.active_mods == ["a", "z"]

    def test_now_iso_format(self) -> None:
        value = prof.now_iso()
        assert value.endswith("Z") and len(value.split(".")[1]) == 8


def test_highlight_presets() -> None:
    color = preset(" Blue ")
    assert color is not None and color.light == "#E8F2FF" and color.dark == "#223246"
    assert preset("pink") is None
