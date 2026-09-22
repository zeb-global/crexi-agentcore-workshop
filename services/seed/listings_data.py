"""The fixed scenario data. Numbers here are load-bearing — the underwriting
math in underwriting/underwrite.py and the closing recommendation in the
scenario (scope-and-architecture.md §2) both depend on these exact figures.
"""

from decimal import Decimal

COLUMBUS = "columbus-oh"
MULTIFAMILY = "multifamily"

# The three properties in the scenario. NOI is deliberately NOT here — it
# only exists in the generated T-12 PDF, which is the whole point of the
# exercise (get_document_text is the only path to it).
LISTINGS = [
    {
        "listingId": "hilliard-commons",
        "name": "Hilliard Commons",
        "market": COLUMBUS,
        "assetType": MULTIFAMILY,
        "units": 84,
        "askingPrice": 9_100_000,
        "yearRenovated": 2019,
        "valueAdd": True,
        "brokerId": "marcus",
        "noi": 588_000,  # baked into the T-12 PDF text, not stored here
    },
    {
        "listingId": "grove-city-gardens",
        "name": "Grove City Gardens",
        "market": COLUMBUS,
        "assetType": MULTIFAMILY,
        "units": 96,
        "askingPrice": 11_200_000,
        "yearRenovated": 2021,
        "valueAdd": False,
        "brokerId": "marcus",
        "noi": 728_000,
    },
    {
        "listingId": "westerville-park",
        "name": "Westerville Park",
        "market": COLUMBUS,
        "assetType": MULTIFAMILY,
        "units": 72,
        "askingPrice": 8_900_000,
        "yearRenovated": 2017,
        "valueAdd": True,
        "brokerId": "marcus",
        "noi": 551_000,
    },
]

# Decoy listings so search_listings has real filtering to do.
DECOYS = [
    {"listingId": "dublin-heights", "name": "Dublin Heights", "market": COLUMBUS,
     "assetType": MULTIFAMILY, "units": 42, "askingPrice": 5_600_000, "yearRenovated": 2016,
     "valueAdd": False, "brokerId": "marcus", "noi": 350_000},
    {"listingId": "polaris-flats", "name": "Polaris Flats", "market": COLUMBUS,
     "assetType": MULTIFAMILY, "units": 160, "askingPrice": 18_500_000, "yearRenovated": 2022,
     "valueAdd": False, "brokerId": "marcus", "noi": 1_150_000},
    {"listingId": "clintonville-row", "name": "Clintonville Row", "market": COLUMBUS,
     "assetType": "retail", "units": 12, "askingPrice": 3_200_000, "yearRenovated": 2015,
     "valueAdd": True, "brokerId": "marcus", "noi": 210_000},
    {"listingId": "worthington-place", "name": "Worthington Place", "market": COLUMBUS,
     "assetType": MULTIFAMILY, "units": 200, "askingPrice": 24_000_000, "yearRenovated": 2020,
     "valueAdd": False, "brokerId": "marcus", "noi": 1_480_000},
    {"listingId": "denver-uptown", "name": "Denver Uptown Lofts", "market": "denver-co",
     "assetType": MULTIFAMILY, "units": 88, "askingPrice": 12_400_000, "yearRenovated": 2018,
     "valueAdd": True, "brokerId": "marcus", "noi": 790_000},
    {"listingId": "austin-riverside", "name": "Austin Riverside", "market": "austin-tx",
     "assetType": MULTIFAMILY, "units": 110, "askingPrice": 15_900_000, "yearRenovated": 2021,
     "valueAdd": False, "brokerId": "marcus", "noi": 980_000},
    {"listingId": "shortnorth-mixed", "name": "Short North Mixed Use", "market": COLUMBUS,
     "assetType": "mixed-use", "units": 30, "askingPrice": 7_100_000, "yearRenovated": 2014,
     "valueAdd": True, "brokerId": "marcus", "noi": 410_000},
    {"listingId": "grandview-arch", "name": "Grandview Arch", "market": COLUMBUS,
     "assetType": MULTIFAMILY, "units": 54, "askingPrice": 10_800_000, "yearRenovated": 2023,
     "valueAdd": False, "brokerId": "marcus", "noi": 690_000},
    {"listingId": "bexley-court", "name": "Bexley Court", "market": COLUMBUS,
     "assetType": MULTIFAMILY, "units": 28, "askingPrice": 4_500_000, "yearRenovated": 2012,
     "valueAdd": True, "brokerId": "marcus", "noi": 275_000},
]

ALL_LISTINGS = LISTINGS + DECOYS

# Dana's stored investor criteria — what long-term memory should recall
# without her repeating it (Checkpoint 1's personalization proof).
DANA_CRITERIA = {
    "market": COLUMBUS,
    "assetType": MULTIFAMILY,
    "unitsMin": 50,
    "unitsMax": 150,
    "valueAdd": True,
    "priceMax": 12_000_000,
    "capRateMin": 6.50,
}

# Recent Columbus multi-family comparable sales -> comps/columbus-multifamily-2025.json
MARKET_COMPS = {
    "market": COLUMBUS,
    "assetType": MULTIFAMILY,
    "asOf": "2025-Q4",
    "comps": [
        {"address": "4400 Sawmill Rd", "units": 76, "salePrice": 8_700_000, "capRate": 6.55, "closedDate": "2025-10-02"},
        {"address": "220 E Livingston Ave", "units": 64, "salePrice": 7_050_000, "capRate": 6.61, "closedDate": "2025-09-18"},
        {"address": "9800 Sancus Blvd", "units": 90, "salePrice": 10_500_000, "capRate": 6.48, "closedDate": "2025-08-30"},
        {"address": "1500 Georgesville Rd", "units": 58, "salePrice": 6_200_000, "capRate": 6.70, "closedDate": "2025-07-22"},
        {"address": "3801 Trabue Rd", "units": 102, "salePrice": 12_100_000, "capRate": 6.52, "closedDate": "2025-11-05"},
    ],
}

# Legacy deal-desk personas (mock system — see scope-and-architecture.md §4.3
# on why this is a DynamoDB lookup rather than a full OAuth 3LO exchange for
# the workshop build).
LEGACY_USERS = [
    {"username": "marcus", "role": "broker", "displayName": "Marcus Hale"},
]

# Rent roll / concessions / deferred maintenance — exists ONLY in the legacy
# deal desk, with no API. This is the data Browser has to go get.
LEGACY_RECORDS = {
    "hilliard-commons": {
        "rentRoll": {"occupiedUnits": 79, "totalUnits": 84, "avgInPlaceRent": 1145,
                     "avgMarketRent": 1210, "occupancyPct": Decimal("94.0")},
        "concessions": "One month free on 6 units signed in the last 90 days "
                        "to backfill turnover after a resident-manager transition.",
        "deferredMaintenance": "Roof on Building C is at end of useful life "
                                "(installed 2006); budget estimate $180,000 not "
                                "yet reserved. Two water heaters flagged for "
                                "replacement in the last inspection.",
    },
    "grove-city-gardens": {
        "rentRoll": {"occupiedUnits": 93, "totalUnits": 96, "avgInPlaceRent": 1280,
                     "avgMarketRent": 1295, "occupancyPct": Decimal("96.9")},
        "concessions": "None on record in the last 12 months.",
        "deferredMaintenance": "No open items. Full envelope inspection completed "
                                "Q3 2025 with no material findings.",
    },
    "westerville-park": {
        "rentRoll": {"occupiedUnits": 66, "totalUnits": 72, "avgInPlaceRent": 1310,
                     "avgMarketRent": 1350, "occupancyPct": Decimal("91.7")},
        "concessions": "Half-month free on 3 units to stabilize lease-up after "
                        "a Q2 2025 renovation phase.",
        "deferredMaintenance": "Parking lot resurfacing scheduled for spring "
                                "2026, $95,000 reserved and budgeted.",
    },
}
