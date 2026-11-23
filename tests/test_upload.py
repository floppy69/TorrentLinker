import base64
import io
import json
from pathlib import Path

import pytest
import torf

from tests.fake_qbit import FakeQbit
from tests.test_upload_completeness import complete_description, complete_form
from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.matching import IgnoreList
from torrentlinker.options import OptionType, OptionValue, options_body, parse_options
from torrentlinker.reseed import TAG, VERIFYING, start_reseed
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.upload import (
    CATEGORY_3D,
    CATEGORY_EBOOK,
    PROFILES,
    EbookProfile,
    ExistingQuery,
    Judgement,
    MiB,
    Model3DProfile,
    Problem,
    Refusal,
    Subcategory3D,
    SubcategoryEbook,
    UploadRequest,
    UploadStopped,
    UploadWarning,
    bencode,
    category_name,
    default_category,
    draft_body,
    find_existing,
    make_torrent,
    missing_options,
    nfo_3d,
    piece_size,
    profile_for,
    seed_match,
    upload_files,
)

FIXTURES = Path(__file__).parent / "fixtures"  # recorded from c411, never fetched by tests
IGNORE = IgnoreList.default()
PROFILE = Model3DProfile()
ANNOUNCE = "https://c411.org/announce/secret"


def recorded_options(sub: int) -> dict[str, object]:
    return json.loads((FIXTURES / f"c411_options_{sub}.json").read_text(encoding="utf-8"))


def vise(tmp_path: Path) -> LocalItem:
    f = tmp_path / "STL" / "Petit étau de bureau.3mf"
    f.parent.mkdir()
    f.write_bytes(bytes(range(256)) * 9000)  # 2.2 Mo: three 1 MiB pieces
    return scan_item(f)


def dragon_pack(tmp_path: Path) -> LocalItem:
    root = tmp_path / "STL" / "Dragon de feu"
    (root / "Têtes").mkdir(parents=True)
    (root / "Corps entier.stl").write_bytes(b"c" * 1500)
    (root / "Têtes" / "tête ouverte.stl").write_bytes(b"t" * 700)
    (root / "Thumbs.db").write_bytes(b"ignored")
    return scan_item(root)


@pytest.mark.parametrize("packed", [False, True])
def test_c411_publication_preserves_the_upload_infohash(tmp_path: Path, packed: bool) -> None:
    item = dragon_pack(tmp_path) if packed else vise(tmp_path)
    files = upload_files(item, "Test.NOTAG.STL", IGNORE)
    torrent = torf.Torrent.read_stream(io.BytesIO(make_torrent(item, files, ANNOUNCE)))
    original_hash = torrent.infohash
    # Observed in the published desk-vise torrent: c411 inserts this source tag.
    torrent.metainfo["info"]["source"] = "C411"
    assert torrent.infohash == original_hash


def test_a_release_name_has_dotted_words_without_accents_the_source_and_the_formats(
    tmp_path: Path,
) -> None:
    item, objects, pack = vise(tmp_path), Subcategory3D.OBJECTS, Subcategory3D.PACK

    assert PROFILE.suggested_name(item, IGNORE, "", objects) == "Petit.Etau.De.Bureau.NOTAG.3MF"
    assert (
        PROFILE.suggested_name(item, IGNORE, "Printables", objects)
        == "Petit.Etau.De.Bureau.Printables.3MF"
    )
    assert (
        PROFILE.suggested_name(dragon_pack(tmp_path), IGNORE, "My Mini Factory", pack)
        == "Dragon.De.Feu.My.Mini.Factory.[PACK].STL"
    )


def test_archives_and_folders_without_a_3d_file_are_refused(tmp_path: Path) -> None:
    archive = tmp_path / "Model.rar"
    archive.write_bytes(b"r" * 10)
    assert PROFILE.refusals(scan_item(archive), IGNORE) == [
        Refusal(Problem.ARCHIVE, "rar"),
        Refusal(Problem.NO_3D_FILE),
    ]
    assert PROFILE.refusals(vise(tmp_path), IGNORE) == []


def test_3d_judgement_rules_are_warnings_never_refusals(tmp_path: Path) -> None:
    objects, pack = Subcategory3D.OBJECTS, Subcategory3D.PACK
    paid = UploadWarning(Judgement.PAID_CREATORS)
    theme = UploadWarning(Judgement.PACK_THEME)

    assert PROFILE.warnings(vise(tmp_path), IGNORE, objects) == [paid]
    dragons = dragon_pack(tmp_path)
    assert PROFILE.warnings(dragons, IGNORE, pack) == [paid, theme]
    assert PROFILE.refusals(dragons, IGNORE) == []  # they do not block


def test_profiles_are_keyed_by_c411_category_and_a_kind_only_proposes_one(tmp_path: Path) -> None:
    assert isinstance(PROFILES[CATEGORY_3D], Model3DProfile)
    assert PROFILES[CATEGORY_3D].category == CATEGORY_3D == 10
    assert all(p.category == c for c, p in PROFILES.items())
    assert {k: default_category(k) for k in ContentKind} == {
        ContentKind.MOVIE: 1,
        ContentKind.SERIES: 1,
        ContentKind.EBOOK: 2,
        ContentKind.MUSIC: 3,
        ContentKind.GAME: 5,
        ContentKind.MODEL_3D: 10,
        ContentKind.ADULT: None,  # c411's Adult category has no upload profile
        ContentKind.OTHER: None,
    }
    assert isinstance(profile_for(ContentKind.MODEL_3D), Model3DProfile)
    assert profile_for(ContentKind.OTHER) is None
    assert category_name(1) == "Films & Vidéos" and category_name(6) == "Emulation"
    assert category_name(10) == "Imprimante 3D" and category_name(99) == "99"
    assert PROFILE.default_subcategory(vise(tmp_path), IGNORE) == Subcategory3D.OBJECTS
    assert PROFILE.default_subcategory(dragon_pack(tmp_path), IGNORE) == Subcategory3D.PACK


def test_the_description_shows_the_image_the_facts_and_a_packs_files(tmp_path: Path) -> None:
    files = upload_files(dragon_pack(tmp_path), "Dragon.NOTAG.[PACK].STL", IGNORE)

    text = PROFILE.description("Dragon.NOTAG.[PACK].STL", files, "", "https://i.example/d.png")

    assert text.startswith("[center][img]https://i.example/d.png[/img][/center]")
    assert "[b]Source :[/b] Inconnue" in text and "[b]Formats :[/b] STL" in text
    assert "[spoiler=Contenu][list]" in text and "[*]Tetes/tete.ouverte.stl" in text
    # no URL yet: a placeholder for the image the user adds on c411
    assert PROFILE.description("T", files, "", "").startswith("[center][img]…[/img][/center]")


def test_a_single_file_is_named_the_release_title_plus_its_extension(tmp_path: Path) -> None:
    item = vise(tmp_path)

    (f,) = upload_files(item, "Petit.Etau.De.Bureau.NOTAG.3MF", IGNORE)

    assert f.torrent_path == "Petit.Etau.De.Bureau.NOTAG.3MF.3mf"
    assert f.local_path == "Petit étau de bureau.3mf"


def test_a_folder_becomes_the_release_title_and_names_below_lose_accents_and_spaces(
    tmp_path: Path,
) -> None:
    files = upload_files(dragon_pack(tmp_path), "Dragon.NOTAG.[PACK].STL", IGNORE)

    assert [(f.torrent_path, f.local_path) for f in files] == [
        ("Dragon.NOTAG.[PACK].STL/Corps.entier.stl", "Dragon de feu/Corps entier.stl"),
        ("Dragon.NOTAG.[PACK].STL/Tetes/tete.ouverte.stl", "Dragon de feu/Têtes/tête ouverte.stl"),
    ]


def test_piece_size_follows_c411s_table() -> None:
    assert piece_size(4_400_000) == 1 * MiB
    assert piece_size(1_500_000_000) == 2 * MiB
    assert piece_size(2_500_000_000) == 4 * MiB
    assert piece_size(5_000_000_000) == 8 * MiB
    assert piece_size(9_000_000_000) == 16 * MiB


def test_the_torrent_is_private_announces_to_the_user_and_hashes_the_local_data(
    tmp_path: Path,
) -> None:
    item = dragon_pack(tmp_path)
    files = upload_files(item, "Dragon.NOTAG.[PACK].STL", IGNORE)

    data = make_torrent(item, files, ANNOUNCE)

    t = torf.Torrent.read_stream(io.BytesIO(data))
    assert t.private and t.trackers == [[ANNOUNCE]]
    assert t.piece_size == MiB
    assert {"/".join(f.parts): f.size for f in t.files} == {
        "Dragon.NOTAG.[PACK].STL/Corps.entier.stl": 1500,
        "Dragon.NOTAG.[PACK].STL/Tetes/tete.ouverte.stl": 700,
    }
    # The same data under the compliant names hashes the same: the torrent verifies.
    copy = tmp_path / "copy" / "Dragon.NOTAG.[PACK].STL"
    (copy / "Tetes").mkdir(parents=True)
    (copy / "Corps.entier.stl").write_bytes(b"c" * 1500)
    (copy / "Tetes" / "tete.ouverte.stl").write_bytes(b"t" * 700)
    assert t.verify(copy)


def test_a_single_file_torrent_verifies_against_the_file_under_its_compliant_name(
    tmp_path: Path,
) -> None:
    item = vise(tmp_path)
    files = upload_files(item, "Petit.Etau.De.Bureau.NOTAG.3MF", IGNORE)

    t = torf.Torrent.read_stream(io.BytesIO(make_torrent(item, files, ANNOUNCE)))

    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "Petit.Etau.De.Bureau.NOTAG.3MF.3mf").write_bytes(item.path.read_bytes())
    assert t.verify(copy / "Petit.Etau.De.Bureau.NOTAG.3MF.3mf")


def test_making_the_torrent_reports_progress_and_can_be_stopped(tmp_path: Path) -> None:
    item = vise(tmp_path)
    files = upload_files(item, "V", IGNORE)
    seen: list[tuple[int, int]] = []

    make_torrent(item, files, ANNOUNCE, report=lambda d, t: seen.append((d, t)))

    assert seen[-1] == (item.size, item.size)
    with pytest.raises(UploadStopped):
        make_torrent(item, files, ANNOUNCE, stopped=lambda: True)


def test_the_upload_seeds_from_the_local_files_renamed_inside_the_client(tmp_path: Path) -> None:
    item = dragon_pack(tmp_path)
    files = upload_files(item, "Dragon.NOTAG.[PACK].STL", IGNORE)
    meta = read_torrent(make_torrent(item, files, ANNOUNCE))
    qbit, store = FakeQbit(), Store(tmp_path / "s.db")

    h = start_reseed(qbit, store, item, meta, seed_match(files), f"upload:{meta.infohash}")

    t = qbit.torrent(h)
    assert t is not None and t.save_path == item.save_path
    assert {TAG, VERIFYING} <= t.tags
    assert set(t.files) == {
        "Dragon de feu/Corps entier.stl",
        "Dragon de feu/Têtes/tête ouverte.stl",
    }
    assert (item.path / "Corps entier.stl").exists()  # the user's files keep their names


def test_the_nfo_lists_name_count_size_formats_and_every_file(tmp_path: Path) -> None:
    files = upload_files(dragon_pack(tmp_path), "Dragon.NOTAG.[PACK].STL", IGNORE)

    nfo = nfo_3d("Dragon.NOTAG.[PACK].STL", files)

    assert "Fichiers ....... : 2" in nfo
    assert "Taille totale .. : 2.1 Ko" in nfo
    assert "Format ......... : STL" in nfo
    assert "Tetes/tete.ouverte.stl" in nfo and "Corps.entier.stl" in nfo


def test_the_draft_carries_category_files_in_base64_and_empty_metadata() -> None:
    body = draft_body("T", "D", 10, Subcategory3D.PACK, b"d4:infoe", "nfo")

    assert body["categoryId"] == 10 and body["subcategoryId"] == 53
    assert base64.b64decode(body["torrentFileData"]) == b"d4:infoe"
    assert base64.b64decode(body["nfoFileData"]) == b"nfo"
    assert body["torrentFileName"] == "T.torrent" and body["nfoFileName"] == "T.nfo"
    assert body["options"] == {} and body["tmdbData"] is None


def test_bencode_sorts_dictionary_keys() -> None:
    assert bencode({"b": 1, "a": [b"x", "y"]}) == b"d1:al1:x1:ye1:bi1ee"


def test_an_upload_keeps_its_files_saves_the_draft_then_seeds(tmp_path: Path) -> None:
    from torrentlinker.upload import create_upload, seed_upload

    item = vise(tmp_path)
    store, qbit = Store(tmp_path / "s.db"), FakeQbit()
    sent: list[dict[str, object]] = []

    def save_draft(body: dict[str, object]) -> int:
        sent.append(body)
        return 128232

    title = "Petit.Etau.De.Bureau.NOTAG.3MF"
    files = upload_files(item, title, IGNORE)
    request = UploadRequest(
        item,
        title,
        files,
        complete_form(10, 51)["nfo"],
        complete_description(text="my description"),
        10,
        51,
    )
    prepared = create_upload(
        request, ANNOUNCE, tmp_path / "uploads", save_draft, store, now=lambda: 50.0
    )
    h = seed_upload(qbit, store, item, prepared)

    assert (tmp_path / "uploads" / "Petit.Etau.De.Bureau.NOTAG.3MF.torrent").exists()
    assert (tmp_path / "uploads" / "Petit.Etau.De.Bureau.NOTAG.3MF.nfo").exists()
    assert sorted(p.name for p in item.path.parent.iterdir()) == ["Petit étau de bureau.3mf"]
    assert sent[0]["categoryId"] == 10 and sent[0]["subcategoryId"] == 51
    assert sent[0]["description"] == complete_description(text="my description")
    assert base64.b64decode(sent[0]["nfoFileData"]) == complete_form(10, 51)["nfo"].encode()  # type: ignore[arg-type]
    assert store.uploads()[0].draft_id == 128232
    assert h == prepared.meta.infohash
    t = qbit.torrent(h)
    assert t is not None and set(t.files) == {"Petit étau de bureau.3mf"}


def test_no_announce_url_means_no_upload(tmp_path: Path) -> None:
    from torrentlinker.upload import create_upload

    with pytest.raises(ValueError, match="Announce URL"):
        item = vise(tmp_path)
        request = UploadRequest(item, "T", upload_files(item, "T", IGNORE), "n", "d", 10, 51)
        create_upload(request, "", tmp_path / "uploads", lambda body: 1, Store(tmp_path / "s.db"))


def test_a_profile_queries_c411_by_the_title_words_of_its_item(tmp_path: Path) -> None:
    query = PROFILE.existing_query(vise(tmp_path), IGNORE)

    assert query == ExistingQuery("Petit étau de bureau")
    assert query.ids == {}


def test_existing_releases_are_searched_in_the_category_by_name() -> None:
    asked: list[SearchQuery] = []
    found = [Candidate("Vise.NOTAG.STL", 10, "d", seeders=1), Candidate("Vise.Pro.STL", 5, "d", 9)]

    def search(q: SearchQuery) -> list[Candidate]:
        asked.append(q)
        return found

    result = find_existing(search, ExistingQuery("Vise"), CATEGORY_3D)

    assert [q.params()["q"] for q in asked] == ["Vise"]
    assert asked[0].categories == (8010,)  # c411's 3D category, as Torznab numbers it
    assert [c.title for c in result] == ["Vise.Pro.STL", "Vise.NOTAG.STL"]  # most seeded first


def test_an_ids_query_goes_to_the_ids_lookup_when_there_is_one() -> None:
    def never(q: SearchQuery) -> list[Candidate]:
        raise AssertionError("searched by name")

    query = ExistingQuery("Dune", {"tmdbId": "438631", "tmdbType": "movie"})
    seen: list[dict[str, str]] = []

    def by_ids(ids: dict[str, str]) -> list[Candidate]:
        seen.append(ids)
        return [Candidate("Dune.2021", 1, "d")]

    assert [c.title for c in find_existing(never, query, 1, by_ids)] == ["Dune.2021"]
    assert seen == [query.ids]


def test_an_ids_query_without_a_lookup_falls_back_to_its_name() -> None:
    asked: list[SearchQuery] = []

    def search(q: SearchQuery) -> list[Candidate]:
        asked.append(q)
        return []

    find_existing(search, ExistingQuery("Dune", {"tmdbId": "1"}), 1)

    assert asked[0].params()["q"] == "Dune"


def test_the_draft_sends_the_chosen_options_and_3d_still_sends_none() -> None:
    chosen = {"1": [2], "4": 35}

    body = draft_body("T", "D", 1, 6, b"d4:infoe", "nfo", chosen)
    assert body["options"] == chosen
    assert draft_body("T", "D", 10, 51, b"d4:infoe", "nfo")["options"] == {}


def test_a_required_option_left_empty_is_a_refusal() -> None:
    langue = OptionType(1, "Langue", True, True, (OptionValue(2, "Français"),))
    genre = OptionType(5, "Genre", True, False, (OptionValue(39, "Action"),))

    assert missing_options([langue, genre], {}) == [Refusal(Problem.OPTION_MISSING, "Langue")]
    assert missing_options([langue, genre], {1: []}) == [Refusal(Problem.OPTION_MISSING, "Langue")]
    assert missing_options([langue, genre], {1: [2]}) == []
    assert missing_options([], {}) == []


def test_a_profile_suggests_no_options_unless_it_knows_them(tmp_path: Path) -> None:
    assert PROFILE.suggested_options(vise(tmp_path), IGNORE, []) == {}


def test_an_upload_sends_its_options_in_the_draft(tmp_path: Path) -> None:
    from torrentlinker.upload import create_upload

    item = vise(tmp_path)
    sent: list[dict[str, object]] = []

    def save_draft(body: dict[str, object]) -> int:
        sent.append(body)
        return 1

    files = upload_files(item, "T", IGNORE)
    request = UploadRequest(
        item,
        "T",
        files,
        complete_form(10, 51)["nfo"],
        complete_description(),
        10,
        51,
        options={"9": 3},
    )
    create_upload(request, ANNOUNCE, tmp_path / "uploads", save_draft, Store(tmp_path / "s.db"))

    assert sent[0]["options"] == {"9": 3}


# eBook profile ---------------------------------------------------------------------

EBOOK = EbookProfile()
BOOKS, BD, AUDIO, PRESS = (
    SubcategoryEbook.BOOKS,
    SubcategoryEbook.BD,
    SubcategoryEbook.AUDIO,
    SubcategoryEbook.PRESS,
)


def folder(tmp_path: Path, name: str, *files: str) -> LocalItem:
    """A Local Item folder `name` holding small files called `files` (`/` nests them)."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for rel in files:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 100)
    return scan_item(root)


def book(tmp_path: Path, name: str) -> LocalItem:
    f = tmp_path / name
    f.write_bytes(b"x" * 100)
    return scan_item(f)


def test_the_ebook_profile_is_category_2_with_its_eight_subcategories() -> None:
    assert CATEGORY_EBOOK == EBOOK.category == 2
    assert isinstance(PROFILES[CATEGORY_EBOOK], EbookProfile)
    assert isinstance(profile_for(ContentKind.EBOOK), EbookProfile)
    assert [s.id for s in EBOOK.subcategories] == [11, 12, 13, 14, 15, 16, 59, 60]


def test_comics_and_image_folders_default_to_bds_audio_to_audio_the_rest_to_livres(
    tmp_path: Path,
) -> None:
    def sub(item: LocalItem) -> int:
        return EBOOK.default_subcategory(item, IGNORE)

    assert sub(book(tmp_path, "Asterix.cbz")) == BD
    assert sub(folder(tmp_path, "A", "t1.cbr", "t2.cbr")) == BD
    assert sub(folder(tmp_path, "B", "01.jpg", "02.png")) == BD
    assert sub(folder(tmp_path, "C", "c1.mp3", "c2.mp3")) == AUDIO
    assert sub(book(tmp_path, "Dune.m4b")) == AUDIO
    assert sub(book(tmp_path, "Dune.epub")) == BOOKS
    assert sub(folder(tmp_path, "D", "Dune.pdf", "cover.jpg")) == BOOKS


def test_ebook_refusals_are_no_file_archives_and_no_accepted_format(tmp_path: Path) -> None:
    def refusals(item: LocalItem) -> list[Refusal]:
        return EBOOK.refusals(item, IGNORE)

    assert refusals(folder(tmp_path, "Vide")) == [Refusal(Problem.NO_FILE)]
    assert refusals(book(tmp_path, "Dune.epub")) == []
    assert refusals(folder(tmp_path, "Comics", "t1.cbz", "t2.cbr")) == []
    assert refusals(book(tmp_path, "Dune.rar")) == [
        Refusal(Problem.ARCHIVE, "rar"),
        Refusal(Problem.NO_EBOOK_FORMAT),
    ]
    assert refusals(folder(tmp_path, "Mix", "Dune.epub", "bonus.zip")) == [
        Refusal(Problem.ARCHIVE, "zip")
    ]
    assert refusals(book(tmp_path, "Dune.docx")) == [Refusal(Problem.NO_EBOOK_FORMAT)]
    for ext in ("pdf", "epub", "mobi", "djvu", "cbr", "cbz", "mp3", "m4a", "m4b", "flac"):
        assert refusals(book(tmp_path, f"Livre.{ext}")) == []


def test_ebook_judgement_rules_are_warnings_never_refusals(tmp_path: Path) -> None:
    french, dupes = UploadWarning(Judgement.FRENCH_ONLY), UploadWarning(Judgement.NO_DUPLICATE)
    formats = UploadWarning(Judgement.FEW_FORMATS)
    volumes = UploadWarning(Judgement.WHOLE_VOLUMES)
    every = UploadWarning(Judgement.EVERY_VOLUME)
    single = book(tmp_path, "Dune.epub")
    triple = folder(tmp_path, "Dune", "Dune.epub", "Dune.pdf", "Dune.mobi")
    pack = folder(tmp_path, "Asterix", "T01.cbz", "T02.cbz")

    assert EBOOK.warnings(single, IGNORE, BOOKS) == [french, dupes]
    assert EBOOK.warnings(triple, IGNORE, BOOKS) == [french, dupes, formats]
    assert EBOOK.warnings(pack, IGNORE, BD) == [french, dupes, volumes, every]
    assert EBOOK.warnings(pack, IGNORE, SubcategoryEbook.MANGA) == [french, dupes, volumes]
    assert EBOOK.warnings(book(tmp_path, "T01.cbz"), IGNORE, BD) == [french, dupes]
    assert EBOOK.refusals(pack, IGNORE) == [] and EBOOK.refusals(triple, IGNORE) == []


def test_a_book_is_named_title_author_language_format_and_tag(tmp_path: Path) -> None:
    item = book(tmp_path, "Frank Herbert - Dune (Édition 2021).epub")

    assert (
        EBOOK.suggested_name(item, IGNORE, "", BOOKS) == "Dune.Frank.Herbert.FRENCH.EPUB-NOTAG"
    )  # the parenthesis is dropped
    assert EBOOK.suggested_name(item, IGNORE, "Mon Équipe", BOOKS).endswith(".EPUB-MonEquipe")
    no_author = book(tmp_path, "Dune.pdf")
    assert EBOOK.suggested_name(no_author, IGNORE, "", BOOKS) == "Dune.FRENCH.PDF-NOTAG"
    two = folder(tmp_path, "Frank Herbert - Dune", "Dune.pdf", "Dune.epub")
    assert (
        EBOOK.suggested_name(two, IGNORE, "", BOOKS) == "Dune.Frank.Herbert.FRENCH.EPUB-PDF-NOTAG"
    )


def test_a_pack_of_volumes_names_its_range(tmp_path: Path) -> None:
    pack = folder(tmp_path, "Asterix", *(f"Asterix T0{n}.cbz" for n in range(1, 8)))

    assert EBOOK.suggested_name(pack, IGNORE, "", BD) == "Asterix.[T01.a.T07].FRENCH.CBZ-NOTAG"
    one = folder(tmp_path, "Tintin", "Tintin T03.cbz")
    assert EBOOK.suggested_name(one, IGNORE, "", BD) == "Tintin.FRENCH.CBZ-NOTAG"


def test_press_is_named_title_date_language_format_and_tag(tmp_path: Path) -> None:
    item = book(tmp_path, "Le Monde - 2024-03-15.pdf")

    assert EBOOK.suggested_name(item, IGNORE, "", PRESS) == "Le.Monde.2024.03.15.FRENCH.PDF-NOTAG"
    assert EBOOK.suggested_name(book(tmp_path, "Elle.pdf"), IGNORE, "", PRESS) == (
        "Elle.FRENCH.PDF-NOTAG"
    )


def test_the_nfo_lists_title_author_formats_language_count_size_and_every_file(
    tmp_path: Path,
) -> None:
    item = folder(tmp_path, "Frank Herbert - Dune", "Dune.epub", "Dune.pdf")
    name = "Dune.Frank.Herbert.FRENCH.EPUB-PDF-NOTAG"

    nfo = EBOOK.nfo(name, upload_files(item, name, IGNORE))

    assert "Titre .......... : Dune" in nfo and "Auteur ......... : Frank Herbert" in nfo
    assert "Format ......... : EPUB, PDF" in nfo and "Langue ......... : Français" not in nfo
    assert "Fichiers ....... : 2" in nfo and "Taille totale .. : 200 o" in nfo
    assert "Dune.epub" in nfo and "Dune.pdf" in nfo


def test_the_ebook_description_has_the_image_the_facts_and_a_presentation(tmp_path: Path) -> None:
    item = book(tmp_path, "Frank Herbert - Dune.epub")
    name = "Dune.Frank.Herbert.FRENCH.EPUB-NOTAG"

    text = EBOOK.description(name, upload_files(item, name, IGNORE), "", "https://i.example/d.png")

    assert text.startswith("[center][img]https://i.example/d.png[/img][/center]")
    assert "[h3]Présentation[/h3]" in text
    assert "[b]Titre :[/b] Dune" in text and "[b]Auteur :[/b] Frank Herbert" in text
    assert "[b]Format :[/b] EPUB" in text and "[b]Langue :[/b] Français" not in text
    assert "[b]Fichiers :[/b] 1" in text and "[b]Taille totale :[/b] 100 o" in text
    assert "[img]" not in EBOOK.description(name, upload_files(item, name, IGNORE), "", "")


def test_the_options_are_pre_filled_with_the_format_found_and_french(tmp_path: Path) -> None:
    types = parse_options(recorded_options(14))

    epub = EBOOK.suggested_options(book(tmp_path, "Dune.epub"), IGNORE, types)
    assert epub == {12: [190], 13: [197]}  # EPUB, Français
    comics = folder(tmp_path, "BD", "T1.cbz", "T2.cbz")
    assert EBOOK.suggested_options(comics, IGNORE, types) == {12: [187], 13: [197]}
    both = folder(tmp_path, "Both", "Dune.pdf", "Dune.epub")
    assert EBOOK.suggested_options(both, IGNORE, types)[12] == [190]  # one choice: EPUB first
    assert EBOOK.suggested_options(book(tmp_path, "x.flac"), IGNORE, types) == {13: [197]}
    assert EBOOK.suggested_options(book(tmp_path, "y.epub"), IGNORE, []) == {}


def test_the_ebook_draft_carries_category_2_and_the_chosen_options() -> None:
    types = parse_options(recorded_options(14))

    options = options_body(types, {12: [190], 13: [197]})
    body = draft_body("T", "D", 2, 14, b"d4:infoe", "nfo", options)

    assert body["categoryId"] == 2 and body["subcategoryId"] == 14
    assert body["options"] == {"12": 190, "13": 197}


def test_existing_ebook_releases_are_looked_up_by_title_words(tmp_path: Path) -> None:
    query = EBOOK.existing_query(book(tmp_path, "Frank Herbert - Dune.epub"), IGNORE)

    assert query == ExistingQuery("Frank Herbert Dune")


def test_backup_announces_preserve_infohash_and_configured_order(tmp_path):
    item = dragon_pack(tmp_path)
    files = upload_files(item, "Test.NOTAG.STL", IGNORE)
    original = torf.Torrent.read_stream(io.BytesIO(make_torrent(item, files, ANNOUNCE)))
    updated = torf.Torrent.read_stream(
        io.BytesIO(
            make_torrent(item, files, ANNOUNCE, announce_hosts=["next.c411.org", "tk.c411.tw"])
        )
    )
    assert updated.infohash == original.infohash
    assert updated.metainfo["announce"] == "https://next.c411.org/announce/secret"
    assert updated.metainfo["announce-list"] == [
        ["https://next.c411.org/announce/secret"],
        ["https://tk.c411.tw/announce/secret"],
    ]
