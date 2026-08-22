#!/usr/bin/env python
"""Seeds entity_alias_overrides with a manually-reviewed batch of project
matches that the automatic fuzzy matcher (ingestion/entity_resolution.py)
can't safely resolve on its own.

Background: DLD frequently records a project under a short/umbrella name
(e.g. "BAY SQUARE") while the scraped catalog only has the more specific
building-level entry ("Bay Square Building 1"). A blanket "raw name's words
are a subset of a longer candidate" auto-match heuristic was prototyped to
catch this, but a manual audit of everything it matched also turned up real
wrong merges from coincidental token overlap — e.g. "AL FURJAN" (an entire
community's worth of DLD sales) landing on "Al Furjan Masjid", a single
mosque, purely for being the shortest candidate containing both words. That
kind of silent merge is exactly what this module's design forbids, so the
heuristic was reverted (see ingestion/entity_resolution.py).

Every row below was instead individually reviewed: raw DLD project name,
the scraped development it should resolve to, and the reasoning is that the
canonicalized raw name is a genuine contiguous substring of the candidate's
canonicalized name (never just an overlapping-words match) AND the
candidate isn't a non-residential type (mosque/school/clinic/etc). Rerun
this script (idempotent) after adding new rows, then rebuild the warehouse
(`python -c "from ingestion import warehouse; import duckdb; con=duckdb.connect('data/warehouse.duckdb'); warehouse.build_warehouse(con)"`)
for it to take effect — entity_alias_overrides always takes priority over
automatic matching.

Usage:
    python scripts/seed_entity_overrides.py [--db data/warehouse.duckdb]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent

# (raw_project_canonical_key, resolved_development_id, development_name_for_reference)
# development_name is not stored — it's here purely so this file stays
# self-documenting about what each id refers to.
PROJECT_OVERRIDES: list[tuple[str, int, str]] = [
    ("giovanni boutique", 207, "Roma by Giovanni Boutique Suites"),
    ("hockey tower", 230, "Ice Hockey Tower"),
    ("blue wave", 235, "Blue Wave Residence"),
    ("liv marina", 245, "LIV Marina Tower"),
    ("west avenue", 350, "West Avenue Tower"),
    ("stella maris", 358, "Stella Maris Tower"),
    ("five luxe", 361, "FIVE Luxe JBR Beach"),
    ("marina arcade", 362, "Marina Arcade Tower"),
    ("trident grand", 392, "Trident Grand Residence"),
    ("beach isle", 407, "Beach Isle @ Emaar Beachfront"),
    ("marina vista", 412, "Marina Vista at Emaar Beachfront"),
    ("mada in", 425, "Mada'in Tower"),
    ("damac bay", 432, "Damac Bay by Cavalli"),
    ("damac bay 2", 433, "Damac Bay 2 by Cavalli"),
    ("franck muller vanguard", 442, "Franck Muller Vanguard by London Gate"),
    ("eden blue", 463, "Eden Blue Tower"),
    ("collective 2 0", 501, "Collective 2.0 at Dubai Hills Estate"),
    ("peninsula four", 546, "Peninsula Four The Offices"),
    ("sol bay", 616, "Sol Bay Tower"),
    ("blue bay", 623, "Blue Bay Tower"),
    ("the court", 635, "The Court Tower"),
    ("sobha ivory", 652, "Sobha Ivory Tower 1"),
    ("bay square", 667, "Bay Square Building 1"),
    ("urban oasis", 685, "Urban Oasis by Missoni"),
    ("bay s edge", 686, "Damac Maison Bay's Edge"),
    ("downtown towers", 689, "Anantara Downtown Towers"),
    ("sls dubai", 715, "SLS Dubai Hotels & Residences"),
    ("al habtoor city", 771, "Al Habtoor City Tower"),
    ("urban life", 776, "Urban Life Residences"),
    ("canal heights", 780, "Canal Heights by Grisogono"),
    ("chic tower", 782, "Chic Tower by de Grisogono"),
    ("canal heights 2", 783, "Canal Heights 2 by Grisogono"),
    ("binghatti house", 945, "Binghatti House JVC"),
    ("astoria villas", 1127, "Astoria Villas North"),
    ("royal park south", 1169, "Royal Park South Villas Block 1"),
    ("park square", 1247, "One Park Square"),
    ("canal views", 1530, "Canal Views Towers"),
    ("pearl jumeirah", 1559, "Pearl Jumeirah Tower"),
    ("royal park", 1562, "Royal Park Residence"),
    ("mon reve", 1681, "Mon Reve by Credo"),
    ("bahwan tower", 1687, "Bahwan Tower Downtown"),
    ("upper crest", 1691, "Damac Maison Upper Crest"),
    ("the distinction", 1705, "Damac Maison Royale The Distinction"),
    ("m burj", 1746, "M Burj Dubai"),
    ("the mansion", 1762, "The Mansion at Burj Dubai"),
    ("the highbury", 2017, "The Highbury at MBR City"),
    ("al fouad", 2088, "Al Fouad by Sooma"),
    ("royal bay", 2204, "Royal Bay by Azizi"),
    ("golden mile", 2216, "The Palm Golden Mile 1"),
    ("zabeel saray", 2250, "Jumeirah Zabeel Saray Hotel & Royal Residences"),
    ("serenia living", 2263, "Serenia Living Tower 1"),
    ("the stella", 2292, "The Stella Villas"),
    ("creek gate", 2439, "Dubai Creek Gate"),
    ("me do re", 2586, "Me Do Re 2"),
    ("dubai star", 2617, "Dubai Star Tower"),
    ("emirates hills", 2668, "Vida Emirates Hills"),
    ("the hills", 2669, "Vida Residences The Hills"),
    ("dubai wharf", 2948, "Dubai Wharf Tower 1"),
    ("the pearl", 2983, "The Pearl Culture Village"),
    ("la boutique", 3039, "La Boutique by LMD"),
    ("creek views", 3041, "Azizi Creek Views 4"),
    ("creek heights", 3232, "Hyatt Regency Creek Heights"),
    ("sera 2", 3248, "Sera 2 at Mina Rashid"),
    ("the spirit", 3309, "The Spirit Tower"),
    ("victory heights", 3332, "Victory Heights Victory Club"),
    ("golf place", 3360, "Golf Place by Prestige One"),
    ("prime gardens", 3431, "Prime Gardens by Prescott"),
    ("the wings", 3504, "The Wings by Al Mizan"),
    ("the light", 3516, "The Light Commercial Tower"),
    ("the lx", 3558, "The LX by Mulk"),
    ("the meriva collection", 3808, "The Meriva Collection Shores"),
    ("cheval residences", 3813, "Cheval Residences Dubai Islands"),
    ("the pier", 3822, "The Pier Residence"),
    ("mar casa", 3829, "Mar Casa Residences"),
    ("the mural", 3838, "The Mural by Beyond"),
    ("il vento", 3843, "Il Vento Tower"),
    ("vento tower", 3843, "Il Vento Tower"),
    ("franck muller yachting", 3850, "Franck Muller Yachting by London Gate"),
    ("sondos lilac", 3905, "Al Sondos Lilac"),
    ("ajmal sarah", 3916, "Ajmal Sarah Tower"),
    ("phoenix tower", 3930, "Phoenix Tower DubaiLand"),
    ("safeer residences 3", 3938, "Safeer Residences 3 DubaiLand"),
    ("a 99", 3983, "A 99 Residence"),
    ("khk 31", 4004, "KHK 31 Residences"),
    ("verdania 1", 4038, "Verdania 1 Residences"),
    ("verdania 2", 4039, "Verdania 2 Residences"),
    ("park gate", 3231, "Park Gate Residences"),
    ("elz residence", 3510, "Elz Residence by Danube"),
    ("la rive", 4150, "La Rive Building 2"),
    ("beach oasis 2", 4423, "Azizi Beach Oasis 2"),
    ("the s tower", 4438, "The S Tower by Sobha"),
    ("the exchange", 4549, "The Exchange DIFC"),
    ("sol luxe", 4691, "Sol Luxe Tower"),
    ("the 50", 4736, "The 50 by Trigono"),
    ("forum 2", 4779, "Forum 2 Residences"),
    ("the haven ii", 4814, "The Haven II Residences"),
    ("o 2", 5190, "S.O.2"),
    ("axis silver", 5253, "Axis Silver One"),
    ("the vortex tower", 5414, "The Vortex Tower DSO"),
    ("al manara", 5451, "Al Manara Apartments"),
    ("fahad 2", 5703, "Al Fahad 2"),
    ("two towers", 5741, "Two Towers TECOM"),
    ("metro central", 5766, "Citadines Metro Central"),
    ("first central", 5773, "First Central Hotel Suites"),
    ("la rosa", 5923, "La Rosa Residence"),
    ("golf grove", 4372, "Golf Grove by Regent"),
    ("the haven", 4704, "The Haven Residences"),
    ("serenia district west", 6255, "Serenia District - West Residence"),
    ("serenia district east", 6259, "Serenia District East Residences"),
    ("the elysian", 6339, "The Elysian Residence"),
    ("180 degree", 6453, "180 Degree Apartments"),
    ("al jawzaa", 6540, "Al Jawzaa Tower A"),
    ("s p residence", 6605, "S.P. Residence International City"),
    ("al khail heights", 6764, "Al Khail Heights RB 5A & 5B"),
    ("design quarter", 6780, "Design Quarter Tower B"),
    ("private residences dubai", 6987, "The Four Seasons Private Residences Dubai"),
    ("expo valley views", 7337, "Dana at Expo Valley Views"),
    ("sobha central", 7489, "Eden at Sobha Central"),
    ("the woods", 7491, "The Woods at Sobha Sanctuary"),
    ("eden house the park", 8113, "Eden House The Park Building A"),
    ("classic apartments", 8586, "Sheffield Classic Apartments"),
]

# Batch 2: same review standard, generated with an additional area-scoping
# step — candidates are restricted to scraped developments within the SAME
# DLD-known area as the project's actual sales (never city-wide), and any
# raw name that is itself a recognized area/community name (e.g. "AL
# FURJAN", "MUDON") is excluded outright, since those represent a whole
# community's worth of scattered sales rather than one building. That
# combination is what caught and excluded the batch-1-style false positives
# on a second pass (a project literally named "AL FURJAN" no longer
# resolves to one arbitrary building within it).
PROJECT_OVERRIDES_BATCH_2: list[tuple[str, int, str]] = [
    ("77s", 733, "77s Tower"),
    ("aeon", 2460, "Aeon Towers"),
    ("alba", 5490, "Alba Residence"),
    ("albero", 2462, "Albero Tower"),
    ("altan", 2461, "Altan Tower"),
    ("altus", 2463, "Altus Towers"),
    ("arlo", 2457, "Arlo Tower"),
    ("avanos", 960, "Avanos Residence"),
    ("bayview", 430, "Address Bayview"),
    ("belmont", 3676, "Belmont Town Square"),
    ("burj views", 7800, "Burj Views Tower A"),
    ("business tower", 864, "DEC Business Tower"),
    ("butterfly", 3560, "Butterfly Towers"),
    ("celadon", 8123, "Celadon 1"),
    ("celeste", 3034, "Celeste Residence"),
    ("century", 746, "Century Tower"),
    ("ciel", 242, "Ciel Vignette Collection"),
    ("creek palace", 2424, "Creek Palace Residences"),
    ("d1", 2899, "D1 Tower"),
    ("eira", 4361, "Eira Residences"),
    ("electra", 1213, "Acube Electra"),
    ("elire", 740, "Elire Tower"),
    ("ellison", 3677, "Ellison Town Square"),
    ("elmora", 6191, "Elmora Residence"),
    ("elvira", 2165, "Elvira at Dubai Hills"),
    ("erantis", 1034, "Erantis Villas"),
    ("ethan", 1982, "Ethan Residences"),
    ("fiori", 3671, "Fiori Town Square"),
    ("firoza", 3730, "Firoza Residence"),
    ("genesis", 3484, "Genesis By Meraki"),
    ("ghalia", 23, "Ghalia Tower"),
    ("grande", 1696, "Grande at The Opera District"),
    ("hameni", 12, "Hameni Tower"),
    ("hillcrest", 3667, "Hillcrest Town Square"),
    ("kaia", 3787, "Kaia Residences"),
    ("karma", 5488, "Karma Residence"),
    ("lia", 3716, "Lia Residences"),
    ("liora", 3731, "Liora Residences"),
    ("liva", 3633, "Liva Apartments at Town Square"),
    ("lolena", 52, "Lolena Residence"),
    ("lunaya", 7058, "Lunaya Terraces"),
    ("majestine", 682, "Damac Maison Majestine"),
    ("manhattan", 105, "The Manhattan"),
    ("marea", 3725, "Marea Residence"),
    ("marinascape", 367, "Trident Marinascape"),
    ("monarch", 4262, "Monarch by Zane"),
    ("montiva", 2489, "Montiva by Vida"),
    ("nas3", 3556, "NAS3 Residence"),
    ("niloofar", 2919, "Niloofar Tower"),
    ("nobles", 555, "Nobles Residential Tower"),
    ("noore", 7508, "Noore Residences"),
    ("odessa", 3674, "Odessa Town Square"),
    ("olbia", 3672, "Olbia Town Square"),
    ("ora", 3659, "Ora by Nshama"),
    ("oria", 2458, "Oria Tower"),
    ("orla by omniyat", 2273, "Orla by Omniyat Dorchester Collection"),
    ("palladium", 2540, "The Palladium"),
    ("parkwood", 2166, "Parkwood at Hills Estate"),
    ("regina", 164, "Regina Tower"),
    ("rena", 3783, "Rena Residence"),
    ("rigel", 1456, "Rigel 1 & 2"),
    ("rivo", 3980, "Rivo by Grovy"),
    ("silva", 2486, "Silva Tower"),
    ("skyscape", 1954, "Skyscape Aura"),
    ("skyvue", 1955, "Skyvue Solair"),
    ("spica", 124, "Spica Residences"),
    ("stax", 1197, "Stax Towers"),
    ("sunvale", 2331, "Sunvale Residences"),
    ("tenora", 2690, "Damac Maison de Ville Tenora"),
    ("the grand", 2455, "The Grand at Dubai Creek Harbour"),
    ("trevino", 1384, "Trevino Residences"),
    ("una", 209, "Una Apartments"),
    ("v3", 2513, "V3 Tower"),
    ("valencia", 1118, "Valencia Residence"),
    ("valo", 2459, "Valo Tower"),
    ("vibe", 9118, "Vibe Building 1"),
    ("weston", 4065, "Weston by Wadan"),
    # Dropped from the auto-generated batch: ("mangrove 2", 4780, "Mangrove 2 Offices")
    # — "Offices" signals a non-residential unit type that likely doesn't
    # match what a bare "Mangrove 2" DLD sale actually is; left unmatched
    # rather than risk a wrong property-type merge.
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "data" / "warehouse.duckdb"))
    args = ap.parse_args()

    con = duckdb.connect(args.db)
    con.execute("""
        CREATE TABLE IF NOT EXISTS entity_alias_overrides (
            raw_key VARCHAR NOT NULL,
            entity_type VARCHAR NOT NULL,
            resolved_entity_id INTEGER,
            resolved_by VARCHAR NOT NULL DEFAULT 'user',
            resolved_at TIMESTAMP NOT NULL DEFAULT now(),
            note VARCHAR,
            PRIMARY KEY (raw_key, entity_type)
        )
    """)

    inserted = 0
    for raw_key, dev_id, dev_name in PROJECT_OVERRIDES + PROJECT_OVERRIDES_BATCH_2:
        con.execute(
            """
            INSERT INTO entity_alias_overrides (raw_key, entity_type, resolved_entity_id, resolved_by, note)
            VALUES (?, 'project', ?, 'manual_review_2026_08', ?)
            ON CONFLICT (raw_key, entity_type) DO UPDATE SET
                resolved_entity_id = excluded.resolved_entity_id,
                resolved_by = excluded.resolved_by,
                resolved_at = now(),
                note = excluded.note
            """,
            [raw_key, dev_id, f"Manually verified contiguous-substring match -> {dev_name}"],
        )
        inserted += 1

    con.close()
    print(f"Seeded/updated {inserted} project entity_alias_overrides rows in {args.db}")
    print("Rebuild the warehouse for these to take effect.")


if __name__ == "__main__":
    main()
