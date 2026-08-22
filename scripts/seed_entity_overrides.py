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
    for raw_key, dev_id, dev_name in PROJECT_OVERRIDES:
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
