"""Day 18: the data.gov.sg datasets the build uses, in one place (fetch.py downloads them, scan.py checks them).

LAND is SLA's National Map Polygon (coastal outlines): Singapore's land, for its lowest SVY21 coordinates.
SCAN is the null-record check: point datasets of places people look up, from as many agencies as we could,
plus HDB's car park list, which ships raw SVY21 x_coord / y_coord columns. Chosen by hand before any were
opened, so the list is not picked for what it contains.
"""
LAND = 'd_29f066d67df3eae91df8a42f443863c8'

SCAN = [
    ('d_23f946fa557947f93a8043bbef41dd09', 'csv'),       # HDB Carpark Information (x_coord, y_coord in SVY21)
    ('d_4a086da0a5553be1d89383cd90d07ecd', 'geojson'),   # Hawker Centres (NEA)
    ('d_548c33ea2d99e29ec63a7cc9edcccedc', 'geojson'),   # CHAS Clinics (MOH)
    ('d_61eefab99958fd70e6aab17320a71f1c', 'geojson'),   # Pre-Schools Location (ECDA)
    ('d_7fe9a72b1afff18e48111772c8d0fd39', 'geojson'),   # Kindergartens (ECDA)
    ('d_5d668e3f544335f8028f546827b773b4', 'geojson'),   # Child Care Services (ECDA)
    ('d_f0fd1b3643ed8bd34bd403dedd7c1533', 'geojson'),   # Eldercare Services (MOH)
    ('d_bb92615f43de22933e4479558b1f6c36', 'geojson'),   # Retail pharmacy locations (HSA)
    ('d_654e22f14e5bb817423f0e0c9ac4f632', 'geojson'),   # Hotels (Hotels Licensing Board)
    ('d_0f2f47515425404e6c9d2a040dd87354', 'geojson'),   # Tourist Attractions (STB)
    ('d_27b8dae65d9ca1539e14d09578b17cbf', 'geojson'),   # Libraries (NLB)
    ('d_31e16b12809e66673e90d8b04fdee1b2', 'geojson'),   # Historic Sites (NHB)
    ('d_b29c230ec6b609e29ed42f71ca9a8767', 'geojson'),   # Monuments (NHB)
    ('d_644ff187b6d14d6316f47284a4a6c81f', 'geojson'),   # Heritage Trees (NParks)
    ('d_4e6b82c58a8a832f6f1fee5dfa6d47ea', 'geojson'),   # Public Access AEDs (SCDF)
    ('d_5d3d2c4f3556edb5d8c995f42e603b24', 'geojson'),   # Fire Stations (SCDF)
    ('d_3f172c6feb3f4f92a2f47d93eed2908a', 'geojson'),   # LTA Bus Stop
    ('d_b39d3a0871985372d7e1637193335da5', 'geojson'),   # LTA MRT Station Exit
    ('d_fa1896e73ded89dd513788d501d45033', 'geojson'),   # LTA Taxi Stop
    ('d_9de02d3fb33d96da1855f4fbef549a0f', 'geojson'),   # Community Club / PAssion WaVe Outlet (PA)
    ('d_4dde14826642f49eefff48b7832b90db', 'geojson'),   # Recycling Bins (NEA)
    ('d_b3ae090692ecf632116c9885cfbd3424', 'geojson'),   # Gyms@SG (HPB)
    ('d_9b87bab59d036a60fad2a91530e10773', 'geojson'),   # SportSG Sport Facilities
    ('d_d8644084f8b54f851a1acbb2f04d5089', 'geojson'),   # Wireless HotSpots (IMDA)
    ('d_f2dc6f340fcf53007e18dad9df92d229', 'geojson'),   # Locations of Money Changer (MAS)
    ('d_2925c2ccf75d1c135c2d469e0de3cee6', 'geojson'),   # Healthier Eateries (HPB)
    ('d_c1f2b991f3932fb69b48edcceef54d13', 'geojson'),   # SLA Vertical Control (survey benchmarks)
    ('d_5fdeb9dccf757dbdf698240fed29f441', 'geojson'),   # SPF Fixed Speed Cameras
    ('d_9606da8c76387bf74627b3e7797f781d', 'geojson'),   # Street and Places (NLB)
    ('d_c69e6d27d72f765fabfbeea362299378', 'geojson'),   # Singapore Police Force Establishments
]
